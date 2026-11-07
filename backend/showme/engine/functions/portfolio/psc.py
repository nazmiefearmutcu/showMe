"""PSC — Position Sizing Calculator.

From account size + risk_per_trade + entry + stop, computes the position
size; with a target the R multiple, and with a win rate as well a simple
Kelly fraction.

2026-11-07 (strict truth audit): the handler used to size a trade it made
up (account 10,000, entry 100, stop 95, target 115, win rate 0.55) whenever
an input was missing. Now nothing is invented: a missing entry is the
symbol's live last price, a missing account is the local portfolio's book
value (both labelled), a missing stop is an input error, and R / Kelly are
only reported when their inputs exist.
"""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _portfolio_book_value() -> float:
    """Local portfolio value at cost basis plus cash (0 when empty)."""
    from showme.engine.portfolio.state import PortfolioState

    state = PortfolioState()
    positions = sum(abs(p.quantity) * p.avg_cost for p in state.positions)
    cash = sum(float(v) for v in (getattr(state, "cash", {}) or {}).values())
    return positions + cash


@FunctionRegistry.register
class PSCFunction(BaseFunction):
    code = "PSC"
    name = "Position Sizing Calculator"
    category = "portfolio"
    description = "Risk-based position sizing with R-multiples and Kelly fraction."

    async def _live_last(self, instrument: Instrument | None, symbol: str | None) -> float | None:
        yf = getattr(self.deps, "yfinance", None)
        if yf is None:
            return None
        if instrument is None:
            if not symbol:
                return None
            instrument = Instrument(symbol=str(symbol).upper(), asset_class=AssetClass.EQUITY)
        try:
            quote = await asyncio.wait_for(
                yf.fetch(DataRequest(kind=DataKind.QUOTE, instrument=instrument)), timeout=4.0)
        except Exception:  # noqa: BLE001 - reported as a missing input
            return None
        last = _num(getattr(quote, "last", None)) if quote is not None else None
        return last if last and last > 0 else None

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        side = (params.get("side") or "LONG").upper()
        risk_pct = _num(params.get("risk_pct"))
        risk_pct = 0.01 if risk_pct is None else risk_pct  # 1% fixed-fractional convention
        sources = ["position_sizing_model"]
        missing: list[str] = []

        entry, entry_source = _num(params.get("entry")), "input"
        if entry is None:
            entry = await self._live_last(instrument, params.get("symbol"))
            entry_source = "live_quote"
            if entry is None:
                missing.append("entry (no live quote for the symbol)")
            else:
                sources.append("yfinance")

        account, account_source = _num(params.get("account")), "input"
        if account is None:
            book = _portfolio_book_value()
            if book > 0:
                account, account_source = book, "portfolio_book_value_at_cost"
            else:
                missing.append("account size (the local portfolio is empty)")

        stop = _num(params.get("stop"))
        if stop is None:
            missing.append("stop")

        if missing:
            return FunctionResult(
                code=self.code, instrument=instrument,
                data={
                    "status": "input_error",
                    "reason": "Position sizing needs: " + ", ".join(missing) + ".",
                    "next_actions": [
                        "Enter a stop price; entry defaults to the live price and account to the portfolio value.",
                    ],
                    "rows": [],
                    "methodology": _methodology(),
                },
                warnings=[f"missing {m}" for m in missing],
            )

        per_share_risk = abs(entry - stop)
        if per_share_risk <= 0:
            return FunctionResult(code=self.code, instrument=instrument,
                                  data={"status": "input_error",
                                        "reason": "entry == stop; can't size",
                                        "next_actions": ["Set a stop different from the entry price."],
                                        "rows": []},
                                  warnings=["entry == stop; can't size"])
        target = _num(params.get("target"))
        win_rate = _num(params.get("win_rate"))
        risk_dollars = account * risk_pct
        shares = risk_dollars / per_share_risk
        notional = shares * entry
        leverage_implied = notional / account
        reward_per_share = abs(target - entry) if target is not None else None
        rr = reward_per_share / per_share_risk if reward_per_share is not None else None
        kelly = kelly_dollars = kelly_shares = None
        if rr and rr > 0 and win_rate is not None:
            kelly = max(0.0, (win_rate * rr - (1 - win_rate)) / rr)
            kelly_dollars = account * kelly
            kelly_shares = kelly_dollars / entry if entry else 0.0

        rows = [
            {"metric": "risk budget", "value": risk_dollars, "meaning": "account * risk_pct"},
            {"metric": "unit risk", "value": per_share_risk, "meaning": "abs(entry - stop)"},
            {"metric": "shares", "value": shares, "meaning": "risk_dollars / unit risk"},
            {"metric": "notional", "value": notional, "meaning": "shares * entry"},
        ]
        if rr is not None:
            rows.append({"metric": "r multiple", "value": rr, "meaning": "reward_per_share / unit risk"})
        if kelly is not None:
            rows.append({"metric": "kelly fraction", "value": kelly, "meaning": "simple Kelly from win_rate and R multiple"})
        warnings = []
        if rr is None:
            warnings.append("No target given: R multiple and Kelly are not computed.")
        elif kelly is None:
            warnings.append("No win rate given: Kelly fraction is not computed.")
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "side": side,
                "account": account, "account_source": account_source,
                "risk_pct": risk_pct, "risk_dollars": risk_dollars,
                "entry": entry, "entry_source": entry_source,
                "stop": stop, "target": target,
                "per_share_risk": per_share_risk,
                "reward_per_share": reward_per_share,
                "r_multiple": rr,
                "shares": shares, "notional": notional,
                "leverage_implied": leverage_implied,
                "kelly_fraction": kelly,
                "kelly_dollars": kelly_dollars,
                "kelly_shares": kelly_shares,
                "rows": rows,
                "summary": {
                    "side": side,
                    "shares": shares,
                    "notional": notional,
                    "risk_dollars": risk_dollars,
                    "r_multiple": rr,
                    "kelly_fraction": kelly,
                },
                "methodology": _methodology(),
                "field_dictionary": {
                    "risk_pct": "Fraction of account equity risked if the stop is hit (default 1%).",
                    "per_share_risk": "Absolute distance between entry and stop.",
                    "r_multiple": "Reward divided by risk per unit (needs a target).",
                    "kelly_fraction": "Simple Kelly fraction (needs a target and a win rate).",
                    "entry_source": "input, or live_quote when entry was not supplied.",
                    "account_source": "input, or portfolio_book_value_at_cost when account was not supplied.",
                },
            },
            sources=sources,
            warnings=warnings,
        )


def _methodology() -> str:
    return (
        "Risk sizing: risk budget = account size * risk_pct; unit risk = abs(entry - stop); "
        "shares = risk budget / unit risk. Entry defaults to the symbol's live last price and account to "
        "the local portfolio book value (cost basis + cash); the stop is always required. R multiple needs "
        "a target and the simple Kelly fraction also a win rate."
    )
