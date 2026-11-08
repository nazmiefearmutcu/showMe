"""PSC — Position Sizing Calculator.

From account size + risk_per_trade + entry + stop, computes the position
size; with a target the R multiple, and with a win rate as well a simple
Kelly fraction.

2026-11-07 (strict truth audit): the handler used to size a trade it made
up (account 10,000, entry 100, stop 95, target 115, win rate 0.55) whenever
an input was missing. Now nothing is invented: a missing entry is the
symbol's live last price, a missing account is the local portfolio's USD
book value (both labelled), a missing stop is an input error, and R / Kelly
are only reported when their inputs exist. Inputs are validated: typed
garbage is an error (never silently replaced), the stop and target must be
on the correct side of the entry for LONG/SHORT, and the win rate is a
probability in [0, 1].
"""

from __future__ import annotations

import asyncio
import math
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument

_BASE_CCY = "USD"


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse(params: dict[str, Any], key: str) -> tuple[float | None, bool]:
    """(value, invalid): blank -> (None, False); typed but not a number -> (None, True)."""
    raw = params.get(key)
    if raw in (None, ""):
        return None, False
    value = _num(raw)
    return value, value is None


def _portfolio_book_value() -> tuple[float, list[str]]:
    """USD book value of the local portfolio (cost basis + USD cash).

    Returns the value and the other currencies that were left out — cash and
    positions are per currency and are never summed across currencies.
    """
    from showme.engine.portfolio.state import PortfolioState

    state = PortfolioState()
    other: set[str] = set()
    total = 0.0
    for p in state.positions:
        ccy = str(getattr(p, "currency", _BASE_CCY) or _BASE_CCY).upper()
        if ccy == _BASE_CCY:
            total += abs(p.quantity) * p.avg_cost
        else:
            other.add(ccy)
    for ccy, amount in (getattr(state, "cash", {}) or {}).items():
        if str(ccy).upper() == _BASE_CCY:
            total += float(amount)
        elif float(amount):
            other.add(str(ccy).upper())
    return total, sorted(other)


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

    def _input_error(self, instrument: Instrument | None, problems: list[str]) -> FunctionResult:
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "status": "input_error",
                "reason": "Position sizing needs: " + "; ".join(problems) + ".",
                "next_actions": [
                    "Enter a stop on the loss side of the entry; entry defaults to the live price and "
                    "account to the portfolio value.",
                ],
                "rows": [],
                "methodology": _methodology(),
            },
            warnings=problems,
        )

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        side = str(params.get("side") or "LONG").strip().upper()
        problems: list[str] = []
        warnings: list[str] = []
        sources = ["position_sizing_model"]
        if side not in {"LONG", "SHORT"}:
            problems.append(f"side must be LONG or SHORT (got {side!r})")

        values: dict[str, float | None] = {}
        for key in ("risk_pct", "entry", "account", "stop", "target", "win_rate"):
            value, invalid = _parse(params, key)
            if invalid:
                problems.append(f"{key} is not a number ({params.get(key)!r})")
            values[key] = value

        risk_pct = 0.01 if values["risk_pct"] is None else values["risk_pct"]  # 1% convention
        if not 0 < risk_pct <= 1:
            problems.append("risk_pct must be a fraction in (0, 1] (0.01 = 1%)")
        win_rate = values["win_rate"]
        if win_rate is not None and not 0 <= win_rate <= 1:
            problems.append("win_rate must be a probability in [0, 1] (0.55 = 55%)")

        entry, entry_source = values["entry"], "input"
        # The router injects a default symbol (e.g. BTCUSDT) when the caller
        # chose none and flags it __explicit_symbol=False; that symbol must
        # never become the trade's entry price (B2 finding PSC#1).
        user_symbol = params.get("__explicit_symbol", True) is not False
        if entry is None and "entry" not in {p.split(" ")[0] for p in problems}:
            if not user_symbol:
                problems.append("entry (no symbol selected, so there is no live price to use)")
            else:
                entry = await self._live_last(instrument, params.get("symbol"))
                entry_source = "live_quote"
                if entry is None:
                    problems.append("entry (no live quote for the symbol)")
                else:
                    sources.append("yfinance")
        if entry is not None and entry <= 0:
            problems.append("entry must be positive")

        account, account_source = values["account"], "input"
        if account is None and "account" not in {p.split(" ")[0] for p in problems}:
            book, other_ccy = _portfolio_book_value()
            if book > 0:
                account, account_source = book, "portfolio_book_value_at_cost"
                if other_ccy:
                    warnings.append(f"Account uses USD holdings only; {', '.join(other_ccy)} holdings were not converted.")
            else:
                problems.append("account size (the local portfolio has no USD value)")
        if account is not None and account <= 0:
            problems.append("account must be positive")

        stop, target = values["stop"], values["target"]
        if stop is None and "stop" not in {p.split(" ")[0] for p in problems}:
            problems.append("stop")
        if entry is not None and entry > 0 and stop is not None:
            if stop == entry:
                problems.append("stop equals entry; can't size")
            elif side == "LONG" and stop > entry:
                problems.append("a LONG stop must be below the entry")
            elif side == "SHORT" and stop < entry:
                problems.append("a SHORT stop must be above the entry")
            if target is not None:
                if side == "LONG" and target <= entry:
                    problems.append("a LONG target must be above the entry")
                elif side == "SHORT" and target >= entry:
                    problems.append("a SHORT target must be below the entry")
        if problems:
            return self._input_error(instrument, problems)

        per_share_risk = abs(entry - stop)
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
            kelly_shares = kelly_dollars / entry

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
                    "kelly_fraction": "Simple Kelly fraction (needs a target and a win rate in [0, 1]).",
                    "entry_source": "input, or live_quote when entry was not supplied.",
                    "account_source": "input, or portfolio_book_value_at_cost (USD) when account was not supplied.",
                },
            },
            sources=sources,
            warnings=warnings,
        )


def _methodology() -> str:
    return (
        "Risk sizing: risk budget = account size * risk_pct; unit risk = abs(entry - stop); "
        "shares = risk budget / unit risk. Entry defaults to the symbol's live last price and account to "
        "the local portfolio's USD book value (cost basis + USD cash); the stop is always required and "
        "must sit on the loss side (below a LONG entry, above a SHORT one). R multiple needs a target on "
        "the profit side; the simple Kelly fraction also needs a win rate in [0, 1]."
    )
