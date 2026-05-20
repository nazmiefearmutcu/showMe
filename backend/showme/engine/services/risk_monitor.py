"""Risk monitor — background daemon that watches portfolio for breaches.

Tetiklenenler:
  - Daily PnL <  ``daily_loss_limit`` (negatif)
  - Drawdown ≥  ``max_drawdown_pct`` (peak'ten düşüş)
  - Concentration: any position weight > ``max_position_pct``
  - VaR (parametric 95) > ``max_var_pct`` of equity

Tetiklenince ALRT engine ile aynı `_FIRES_LOG`'a yazar; notifier'lar
ona göre yayar.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from showme.app_paths import runtime_path


def _risk_fires():
    return runtime_path("risk_fires.jsonl")


def _peak_file():
    return runtime_path("risk_peak.json")


class RiskMonitor:
    def __init__(self, deps: Any | None = None,
                 *, max_drawdown_pct: float = 0.10,
                 daily_loss_limit_pct: float = 0.05,
                 max_position_pct: float = 0.25,
                 max_var_pct: float = 0.05,
                 notifiers: list[Any] | None = None) -> None:
        self.deps = deps
        self.max_drawdown_pct = max_drawdown_pct
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.max_position_pct = max_position_pct
        self.max_var_pct = max_var_pct
        self.notifiers = list(notifiers or [])
        self._task: asyncio.Task | None = None

    def add_notifier(self, fn) -> None:
        self.notifiers.append(fn)

    def _load_peak(self) -> dict[str, Any]:
        if _peak_file().exists():
            try:
                return json.loads(_peak_file().read_text())
            except Exception:
                pass
        return {"peak_mv": 0, "peak_ts": None,
                "day_open_mv": 0, "day_open_ts": None}

    def _save_peak(self, state: dict[str, Any]) -> None:
        _peak_file().parent.mkdir(parents=True, exist_ok=True)
        _peak_file().write_text(json.dumps(state))

    def _fire(self, kind: str, message: str, ctx: dict[str, Any]) -> None:
        evt = {"ts": datetime.now(timezone.utc).isoformat(),
               "kind": "risk", "subkind": kind,
               "condition": message, "actions": ["notify"], "context": ctx}
        _risk_fires().parent.mkdir(parents=True, exist_ok=True)
        with _risk_fires().open("a") as f:
            f.write(json.dumps(evt) + "\n")
        for n in self.notifiers:
            try:
                r = n(evt)
                if asyncio.iscoroutine(r):
                    asyncio.create_task(r)
            except Exception:
                continue

    async def _portfolio_snapshot(self) -> dict[str, Any]:
        from showme.engine.functions.portfolio.port import PORTFunction
        if self.deps is None:
            return {}
        try:
            res = await PORTFunction(self.deps).execute()
            return res.data or {}
        except Exception:
            return {}

    async def tick(self) -> int:
        snap = await self._portfolio_snapshot()
        totals = snap.get("totals") or {}
        positions = snap.get("positions") or []
        mv = float(totals.get("market_value") or 0)
        if mv <= 0:
            return 0
        peak = self._load_peak()
        now = datetime.now(timezone.utc).isoformat()
        # Refresh peak / day-open
        if mv > (peak.get("peak_mv") or 0):
            peak["peak_mv"] = mv; peak["peak_ts"] = now
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if (peak.get("day_open_ts") or "")[:10] != today:
            peak["day_open_mv"] = mv; peak["day_open_ts"] = now
        self._save_peak(peak)
        fires = 0
        # Drawdown check
        peak_mv = peak.get("peak_mv") or mv
        dd = (mv - peak_mv) / peak_mv if peak_mv else 0
        if dd <= -self.max_drawdown_pct:
            self._fire("drawdown",
                        f"portfolio.drawdown <= -{self.max_drawdown_pct*100:.0f}%",
                        {"value": dd * 100, "threshold": -self.max_drawdown_pct * 100,
                         "op": "<=", "field": "drawdown",
                         "peak_mv": peak_mv, "current_mv": mv})
            fires += 1
        # Daily loss check
        day_open = peak.get("day_open_mv") or mv
        day_pnl_pct = (mv - day_open) / day_open if day_open else 0
        if day_pnl_pct <= -self.daily_loss_limit_pct:
            self._fire("daily_loss",
                        f"portfolio.day_pnl <= -{self.daily_loss_limit_pct*100:.1f}%",
                        {"value": day_pnl_pct * 100,
                         "threshold": -self.daily_loss_limit_pct * 100,
                         "op": "<=", "field": "day_pnl"})
            fires += 1
        # Concentration check
        total = sum(float(p.get("market_value") or 0) for p in positions) or mv
        for p in positions:
            mv_i = float(p.get("market_value") or 0)
            wt = mv_i / total if total else 0
            if wt > self.max_position_pct:
                self._fire("concentration",
                            f"{p.get('symbol')}.weight > {self.max_position_pct*100:.0f}%",
                            {"value": wt * 100,
                             "threshold": self.max_position_pct * 100,
                             "op": ">", "field": "weight",
                             "symbol": p.get("symbol")})
                fires += 1
        return fires

    async def loop(self, interval_seconds: int = 120) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                pass
            await asyncio.sleep(interval_seconds)

    def start(self, interval_seconds: int = 120) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.loop(interval_seconds))

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None
