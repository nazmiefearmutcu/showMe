"""PSC — Position Sizing Calculator.

Verilen account_size + risk_per_trade + entry + stop'tan optimal pozisyon
boyutunu (Kelly opsiyonel) hesaplar. Çoklu hedef + R-multiple raporu.
"""

from __future__ import annotations

from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument


@FunctionRegistry.register
class PSCFunction(BaseFunction):
    code = "PSC"
    name = "Position Sizing Calculator"
    category = "portfolio"
    description = "Risk-based position sizing with R-multiples and Kelly fraction."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        account = float(params.get("account", 10000))
        risk_pct = float(params.get("risk_pct", 0.01))      # %1 default
        entry = float(params.get("entry", 100))
        stop = float(params.get("stop", 95))
        target = float(params.get("target", 115))
        win_rate = float(params.get("win_rate", 0.55))
        # Kelly assumes win/loss are R-multiples (simple form).
        side = (params.get("side") or "LONG").upper()

        risk_dollars = account * risk_pct
        per_share_risk = abs(entry - stop)
        if per_share_risk <= 0:
            return FunctionResult(code=self.code, instrument=instrument, data={},
                                  warnings=["entry == stop; can't size"])
        shares = risk_dollars / per_share_risk
        notional = shares * entry
        leverage_implied = notional / account
        reward_per_share = abs(target - entry)
        rr = reward_per_share / per_share_risk
        kelly = max(0.0, (win_rate * rr - (1 - win_rate)) / rr) if rr > 0 else 0.0
        kelly_dollars = account * kelly
        kelly_shares = (kelly_dollars / entry) if entry else 0.0
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "side": side,
                "account": account, "risk_pct": risk_pct, "risk_dollars": risk_dollars,
                "entry": entry, "stop": stop, "target": target,
                "per_share_risk": per_share_risk,
                "reward_per_share": reward_per_share,
                "r_multiple": rr,
                "shares": shares, "notional": notional,
                "leverage_implied": leverage_implied,
                "kelly_fraction": kelly,
                "kelly_dollars": kelly_dollars,
                "kelly_shares": kelly_shares,
                "rows": [
                    {"metric": "risk budget", "value": risk_dollars, "meaning": "account * risk_pct"},
                    {"metric": "unit risk", "value": per_share_risk, "meaning": "abs(entry - stop)"},
                    {"metric": "shares", "value": shares, "meaning": "risk_dollars / unit risk"},
                    {"metric": "notional", "value": notional, "meaning": "shares * entry"},
                    {"metric": "r multiple", "value": rr, "meaning": "reward_per_share / unit risk"},
                    {"metric": "kelly fraction", "value": kelly, "meaning": "simple Kelly from win_rate and R multiple"},
                ],
                "summary": {
                    "side": side,
                    "shares": shares,
                    "notional": notional,
                    "risk_dollars": risk_dollars,
                    "r_multiple": rr,
                    "kelly_fraction": kelly,
                },
                "methodology": (
                    "Risk sizing: risk budget = account size * risk_pct; unit risk = abs(entry - stop); "
                    "shares = risk budget / unit risk. R multiple and simple Kelly use the target, stop, and win-rate assumptions."
                ),
                "field_dictionary": {
                    "risk_pct": "Fraction of account equity risked if the stop is hit.",
                    "per_share_risk": "Absolute distance between entry and stop.",
                    "r_multiple": "Reward divided by risk per unit.",
                    "kelly_fraction": "Simple Kelly fraction from win-rate and reward/risk assumptions.",
                },
            },
            sources=["position_sizing_model"],
        )
