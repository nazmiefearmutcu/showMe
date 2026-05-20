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
from datetime import datetime, timezone
from typing import Any, Callable

from showme.app_paths import runtime_path


def _alerts_path():
    return runtime_path("alerts.json")


def _fires_log():
    return runtime_path("alert_fires.jsonl")


def _compare(value: float, op: str, threshold: float) -> bool:
    """Shared numeric comparison used by quote + news alerts."""
    if op == ">":
        return value > threshold
    if op == ">=":
        return value >= threshold
    if op == "<":
        return value < threshold
    if op == "<=":
        return value <= threshold
    if op in ("=", "=="):
        return value == threshold
    if op == "!=":
        return value != threshold
    return False


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
        if not _alerts_path().exists():
            return []
        try:
            return json.loads(_alerts_path().read_text()) or []
        except Exception:
            return []

    def save_alerts(self, alerts: list[dict[str, Any]]) -> None:
        _alerts_path().parent.mkdir(parents=True, exist_ok=True)
        _alerts_path().write_text(json.dumps(alerts, indent=2))

    async def evaluate(self, condition: str) -> tuple[bool, dict[str, Any]]:
        """Evaluate "<SYMBOL>.<FIELD> <OP> <VAL>" against a live quote.

        Supported ops: >, >=, <, <=, ==, !=
        Supported FIELDs: price (=last), bid, ask, volume_24h, change_pct
        News form: NEWS(BTCUSDT).importance >= 70

        Per PY-LINT-04 (R3A): the rule-parse / quote-resolve / comparison
        logic now sits in three named helpers so the public method's CC
        stays under 10.
        """
        news_match = re.match(
            r"\s*NEWS\(([^)]+)\)\.importance\s*([<>!=]=?|==)\s*(\d+(?:\.\d+)?)\s*",
            condition or "",
            flags=re.IGNORECASE,
        )
        if news_match:
            return await self._evaluate_news_alert(*news_match.groups())

        parsed = self._parse_quote_rule(condition)
        if parsed is None:
            return (False, {"error": "unparseable condition"})
        sym, field, op, val = parsed
        inst, err = await self._resolve_instrument(sym)
        if err is not None:
            return (False, err)
        quote = await self._resolve_quote(inst)
        if quote is None:
            return (False, {"error": "no quote"})
        return self._compare_quote_field(sym, field, op, val, quote)

    @staticmethod
    def _parse_quote_rule(condition: str) -> tuple[str, str, str, float] | None:
        m = re.match(
            r"\s*([A-Za-z0-9._\^]+)\.(\w+)\s*([<>!=]=?|==)\s*(-?\d+(?:\.\d+)?)\s*",
            condition or "",
        )
        if not m:
            return None
        sym, field, op, val_s = m.groups()
        return sym, field, op, float(val_s)

    async def _resolve_instrument(self, sym: str) -> tuple[Any | None, dict[str, Any] | None]:
        if not self.deps or not self.deps.symbol_registry:
            return None, {"error": "no deps/symbol_registry"}
        inst = await self.deps.symbol_registry.resolve(sym)
        if inst is None:
            return None, {"error": f"unknown symbol {sym}"}
        return inst, None

    async def _resolve_quote(self, inst: Any) -> Any | None:
        from showme.engine.core.base_data_source import DataKind, DataRequest

        chain: list[Any] = []
        if inst.asset_class.value == "CRYPTO":
            chain = []  # Crypto WS handled by legacy bot; use yfinance fallback
        chain += [
            self.deps.yfinance, self.deps.finnhub, self.deps.alphavantage,
            self.deps.exchangerate_host,
        ]
        for src in chain:
            if src is None:
                continue
            try:
                q = await src.fetch(DataRequest(kind=DataKind.QUOTE, instrument=inst))
                if q is not None:
                    return q
            except Exception:
                continue
        return None

    @staticmethod
    def _compare_quote_field(
        sym: str, field: str, op: str, val: float, q: Any
    ) -> tuple[bool, dict[str, Any]]:
        f = field.lower()
        if f == "price":
            v = q.last
        elif f == "bid":
            v = q.bid
        elif f == "ask":
            v = q.ask
        elif f == "volume":
            v = q.volume_24h
        elif f in ("change_pct", "chg"):
            v = ((q.last or 0) / (q.close_prev or 1) - 1) * 100 if q.close_prev else None
        else:
            return (False, {"error": f"unknown field {field}"})
        if v is None:
            return (False, {"error": f"field {field} missing"})
        ok = _compare(v, op, val)
        return (ok, {"value": v, "threshold": val, "op": op,
                     "symbol": sym, "field": field})

    async def _evaluate_news_alert(self, symbol: str, op: str, val_s: str) -> tuple[bool, dict[str, Any]]:
        if not self.deps:
            return (False, {"error": "no deps"})
        threshold = float(val_s)
        from showme.engine.core.instrument import AssetClass, Instrument
        from showme.engine.functions.news.nalrt import NewsAlertFunction

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
        ok = _compare(value, op, threshold)
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
        """Run one evaluation pass over all alerts. Returns number of fires.

        Per PY-LINT-04: cooldown handling + fire dispatch are split into
        helpers so this stays a thin loop.
        """
        alerts = self.load_alerts()
        fires = 0
        now = datetime.now(timezone.utc)
        for a in alerts:
            if not a.get("enabled", True):
                continue
            if self._in_cooldown(a, now):
                continue
            ok, ctx = await self.evaluate(a.get("condition", ""))
            if ok:
                await self._fire(a, ctx, now)
                fires += 1
        if fires:
            self.save_alerts(alerts)
        self._tick += 1
        return fires

    @staticmethod
    def _in_cooldown(alert: dict[str, Any], now: datetime) -> bool:
        last_fired = alert.get("last_fired")
        if not last_fired:
            return False
        cooldown = int(alert.get("cooldown_seconds", 300))
        try:
            last = datetime.fromisoformat(last_fired)
        except Exception:
            return False
        return (now - last).total_seconds() < cooldown

    async def _fire(
        self, alert: dict[str, Any], ctx: dict[str, Any], now: datetime
    ) -> None:
        alert["last_fired"] = now.isoformat()
        event = {
            "ts": now.isoformat(),
            "alert_id": alert.get("id"),
            "condition": alert.get("condition"),
            "actions": alert.get("actions"),
            "context": ctx,
        }
        # Append fire log
        _fires_log().parent.mkdir(parents=True, exist_ok=True)
        with _fires_log().open("a") as f:
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
        actions = alert.get("actions") or []
        if "run:DES" in actions or any(act.startswith("run:") for act in actions):
            pass  # left for orchestrator to handle

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
    from showme.engine.services.email_service import send_email, _smtp_configured
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
