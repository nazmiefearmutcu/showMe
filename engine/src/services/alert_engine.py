"""ALRT engine — DSL kondisyon değerlendirici + event bus + tetikleme.

Plan §20.2:
    Alert(condition, action, recipients)
    Condition DSL: "AAPL.price > 200" / "BTC.RSI(1h) < 30 AND MACD.crossover()"
    Actions: notify | execute_order | run_function

Bu engine `runtime/alerts.json` üzerinden alarmları okur, periyodik
olarak verileri çeker, koşulu değerlendirir, tetiklenenleri SMTP /
WebSocket / sound üzerinden bildirir.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

_ALERTS_PATH = Path("runtime/alerts.json")
_FIRES_LOG = Path("runtime/alert_fires.jsonl")


class AlertEngine:
    """Periodic evaluator for ALRT-defined conditions."""

    def __init__(self, deps: Any | None = None,
                 notifiers: list[Callable[[dict], Any]] | None = None) -> None:
        self.deps = deps
        self.notifiers = list(notifiers or [])
        self._tick = 0
        self._task: asyncio.Task | None = None

    def add_notifier(self, fn: Callable[[dict], Any]) -> None:
        self.notifiers.append(fn)

    def load_alerts(self) -> list[dict[str, Any]]:
        if not _ALERTS_PATH.exists():
            return []
        try:
            return json.loads(_ALERTS_PATH.read_text()) or []
        except Exception:
            return []

    def save_alerts(self, alerts: list[dict[str, Any]]) -> None:
        _ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _ALERTS_PATH.write_text(json.dumps(alerts, indent=2))

    async def evaluate(self, condition: str) -> tuple[bool, dict[str, Any]]:
        """Evaluate "<SYMBOL>.<FIELD> <OP> <VAL>" against a live quote.

        Supported ops: >, >=, <, <=, ==, !=
        Supported FIELDs: price (=last), bid, ask, volume_24h, change_pct
        News form: NEWS(BTCUSDT).importance >= 70
        """
        news_match = re.match(
            r"\s*NEWS\(([^)]+)\)\.importance\s*([<>!=]=?|==)\s*(\d+(?:\.\d+)?)\s*",
            condition or "",
            flags=re.IGNORECASE,
        )
        if news_match:
            return await self._evaluate_news_alert(*news_match.groups())

        m = re.match(
            r"\s*([A-Za-z0-9._\^]+)\.(\w+)\s*([<>!=]=?|==)\s*(-?\d+(?:\.\d+)?)\s*",
            condition or "",
        )
        if not m:
            return (False, {"error": "unparseable condition"})
        sym, field, op, val_s = m.groups()
        val = float(val_s)
        # Resolve quote via DAPI surface — symbol_registry + yfinance/finnhub chain.
        if not self.deps or not self.deps.symbol_registry:
            return (False, {"error": "no deps/symbol_registry"})
        inst = await self.deps.symbol_registry.resolve(sym)
        if inst is None:
            return (False, {"error": f"unknown symbol {sym}"})
        from src.core.base_data_source import DataKind, DataRequest
        chain = []
        if inst.asset_class.value == "CRYPTO":
            chain = []  # Crypto WS handled by legacy bot; use yfinance fallback
        chain += [
            self.deps.yfinance, self.deps.finnhub, self.deps.alphavantage,
            self.deps.exchangerate_host,
        ]
        q = None
        for src in chain:
            if src is None:
                continue
            try:
                q = await src.fetch(DataRequest(kind=DataKind.QUOTE, instrument=inst))
                if q is not None:
                    break
            except Exception:
                continue
        if q is None:
            return (False, {"error": "no quote"})
        # Pull the requested field
        f = field.lower()
        if f == "price": v = q.last
        elif f == "bid": v = q.bid
        elif f == "ask": v = q.ask
        elif f == "volume": v = q.volume_24h
        elif f in ("change_pct", "chg"):
            v = ((q.last or 0) / (q.close_prev or 1) - 1) * 100 if q.close_prev else None
        else:
            return (False, {"error": f"unknown field {field}"})
        if v is None:
            return (False, {"error": f"field {field} missing"})
        ok = (
            (op == ">" and v > val) or (op == ">=" and v >= val) or
            (op == "<" and v < val) or (op == "<=" and v <= val) or
            (op in ("=", "==") and v == val) or (op == "!=" and v != val)
        )
        return (ok, {"value": v, "threshold": val, "op": op,
                     "symbol": sym, "field": field})

    async def _evaluate_news_alert(self, symbol: str, op: str, val_s: str) -> tuple[bool, dict[str, Any]]:
        if not self.deps:
            return (False, {"error": "no deps"})
        threshold = float(val_s)
        from src.core.instrument import AssetClass, Instrument
        from src.functions.news.nalrt import NewsAlertFunction

        clean_symbol = symbol.strip().upper()
        asset_class = AssetClass.CRYPTO if clean_symbol.endswith(("USDT", "USDC")) else AssetClass.EQUITY
        inst = Instrument(symbol=clean_symbol, asset_class=asset_class)
        res = await NewsAlertFunction(self.deps).execute(
            inst,
            symbol=clean_symbol,
            asset_class=asset_class.value,
            threshold=threshold,
            limit=20,
            live=True,
            news_timeout=6,
            health=False,
        )
        data = res.data if isinstance(res.data, dict) else {}
        value = float(data.get("top_importance_score") or 0)
        ok = (
            (op == ">" and value > threshold) or (op == ">=" and value >= threshold) or
            (op == "<" and value < threshold) or (op == "<=" and value <= threshold) or
            (op in ("=", "==") and value == threshold) or (op == "!=" and value != threshold)
        )
        alerts = data.get("alerts") if isinstance(data.get("alerts"), list) else []
        return (ok, {
            "value": value,
            "threshold": threshold,
            "op": op,
            "symbol": clean_symbol,
            "field": "news.importance",
            "alert_count": len(alerts),
            "top_headline": alerts[0].get("title") if alerts and isinstance(alerts[0], dict) else None,
            "sources": res.sources,
        })

    async def tick(self) -> int:
        """Run one evaluation pass over all alerts. Returns number of fires."""
        alerts = self.load_alerts()
        fires = 0
        now = datetime.utcnow()
        for a in alerts:
            if not a.get("enabled", True):
                continue
            last_fired = a.get("last_fired")
            cooldown = int(a.get("cooldown_seconds", 300))
            if last_fired:
                try:
                    last = datetime.fromisoformat(last_fired)
                    if (now - last).total_seconds() < cooldown:
                        continue
                except Exception:
                    pass
            ok, ctx = await self.evaluate(a.get("condition", ""))
            if ok:
                a["last_fired"] = now.isoformat()
                fires += 1
                event = {
                    "ts": now.isoformat(),
                    "alert_id": a.get("id"),
                    "condition": a.get("condition"),
                    "actions": a.get("actions"),
                    "context": ctx,
                }
                # Append fire log
                _FIRES_LOG.parent.mkdir(parents=True, exist_ok=True)
                with _FIRES_LOG.open("a") as f:
                    f.write(json.dumps(event) + "\n")
                # Dispatch
                for n in self.notifiers:
                    try:
                        res = n(event)
                        if asyncio.iscoroutine(res):
                            await res
                    except Exception:
                        continue
                # Optional: execute order or run function
                actions = a.get("actions") or []
                if "run:DES" in actions or any(act.startswith("run:") for act in actions):
                    pass  # left for orchestrator to handle
        if fires:
            self.save_alerts(alerts)
        self._tick += 1
        return fires

    async def loop(self, interval_seconds: int = 30) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                pass
            await asyncio.sleep(interval_seconds)

    def start(self, interval_seconds: int = 30) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.loop(interval_seconds))

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None


# ── Built-in notifiers ──
def email_notifier(event: dict[str, Any]) -> bool:
    import os
    from src.services.email_service import send_email, _smtp_configured
    if not _smtp_configured():
        return False
    to = os.environ.get("ALERT_EMAIL_TO")
    if not to:
        return False
    body = json.dumps(event, indent=2)
    return send_email(
        to=to,
        subject=f"ShowMe Alert: {event.get('condition')}",
        text=body, html=f"<pre>{body}</pre>",
    )


def stdout_notifier(event: dict[str, Any]) -> None:
    print(f"[ALERT] {event.get('condition')} — {event.get('context')}")
