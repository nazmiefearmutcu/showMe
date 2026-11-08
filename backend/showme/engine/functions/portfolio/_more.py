"""PORT WHATIF, TRA, MARS — gerçek implementasyonlar."""

from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio.return_series import align_return_series, close_to_daily_returns
from showme.engine.portfolio.state import PortfolioPosition, PortfolioState


@FunctionRegistry.register
class PORTWhatIfFunction(BaseFunction):
    """PORT WHAT-IF — add a hypothetical trade and re-compute full analytics."""
    code = "PORT_WHATIF"
    name = "Portfolio What-If"
    category = "portfolio"
    description = (
        "Hypothetical buy or sell of one symbol at a typed cost: re-prices the book before "
        "and after, debits or credits cash, merges into the held lot, and reports the change "
        "in market value, unrealized P&L, total equity and position count. Research only."
    )

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("PORT_WHATIF requires instrument")
        # No placeholder cost: a what-if P&L is only meaningful for a cost the
        # user actually typed. Missing inputs return an explicit state.
        qty, cost, problem = _whatif_inputs(params)
        if problem is not None:
            return FunctionResult(
                code=self.code, instrument=instrument,
                data={**problem, "rows": [], "methodology": (
                    "Clone the current portfolio state, add the hypothetical position, "
                    "rerun portfolio analytics before and after, then display the delta."
                )},
                sources=[], warnings=[],
            )
        baseline = PortfolioState()
        baseline.import_legacy_crypto()
        # HNT-17: the old fixed "/tmp/_showme_whatif.json" path created a
        # literal C:\tmp on Windows and was shared by concurrent calls. Use
        # a unique never-created path under the real temp dir — nothing is
        # ever saved to it (positions are assigned in memory), so uniqueness
        # is all the isolation this scratch state needs.
        whatif_path = (
            Path(tempfile.gettempdir())
            / f"_showme_whatif_{os.getpid()}_{uuid.uuid4().hex}.json"
        )
        whatif = PortfolioState(path=whatif_path)
        new_positions, trade_ccy, realized, problem = _whatif_apply_trade(
            list(baseline.positions), instrument, qty, cost,
        )
        if problem is not None:
            return FunctionResult(
                code=self.code, instrument=instrument,
                data={**problem, "rows": [], "methodology": _WHATIF_METHODOLOGY},
                sources=[], warnings=[],
            )
        whatif.positions = new_positions
        whatif.cash = dict(baseline.cash)
        # A book that tracks no cash cannot show a funded trade: no cash is
        # invented, so the equity change is withheld and the gap is reported.
        cash_tracked = bool(baseline.cash)
        cash_delta: float | None = None
        warnings: list[str] = []
        if cash_tracked:
            cash_delta = -qty * cost
            # Debit the key the book already stores (PORT upper-cases cash keys, but a
            # stored 'usd' must not gain a second 'USD' twin that replaces its balance).
            cash_key = _whatif_cash_key(whatif.cash, trade_ccy)
            cash_after = float(whatif.cash.get(cash_key) or 0.0) + cash_delta
            whatif.cash[cash_key] = cash_after
            if cash_after < 0:
                warnings.append(
                    f"scenario {trade_ccy} cash would be {cash_after:,.2f}: the trade costs more "
                    "than the cash this book holds"
                )
        else:
            warnings.append(
                "this book does not track cash, so the trade is not funded and the "
                "total equity change is not computed"
            )
        from showme.engine.functions.portfolio.port import PORTFunction
        port_deps = self.deps
        if self.deps is not None and self.deps.yfinance is not None:
            # Both PORT runs price the same symbols: one quote fetch serves both.
            import dataclasses
            port_deps = dataclasses.replace(self.deps, yfinance=_MemoQuoteAdapter(self.deps.yfinance))
        port = PORTFunction(port_deps)
        before = await port.execute(_portfolio_override=baseline)
        after = await port.execute(_portfolio_override=whatif)
        bt = (before.data or {}).get("totals") or {}
        at = (after.data or {}).get("totals") or {}
        equity_before = bt.get("total_equity")
        equity_after = at.get("total_equity")
        total_equity_delta = (
            equity_after - equity_before
            if equity_before is not None and equity_after is not None else None
        )
        delta = {
            "market_value": (at.get("market_value") or 0) - (bt.get("market_value") or 0),
            "unrealized_pnl": (at.get("unrealized_pnl") or 0) - (bt.get("unrealized_pnl") or 0),
            "n_positions": (at.get("n_positions") or 0) - (bt.get("n_positions") or 0),
            "total_equity": total_equity_delta,
        }
        return FunctionResult(code=self.code, instrument=instrument,
                              data={"hypothetical_added": {"symbol": instrument.symbol,
                                                              "qty": qty, "cost": cost},
                                     "before": before.data, "after": after.data,
                                     "delta": delta,
                                     "rows": [
                                         {"metric": key, "before": bt.get(key), "after": at.get(key), "value": value}
                                         for key, value in delta.items()
                                     ],
                                     "summary": {
                                         "symbol": instrument.symbol,
                                         "quantity": qty,
                                         "cost": cost,
                                         "trade_currency": trade_ccy,
                                         "market_value_delta": delta["market_value"],
                                         "unrealized_pnl_delta": delta["unrealized_pnl"],
                                         "total_equity_delta": total_equity_delta,
                                         "cash_delta": cash_delta,
                                         "realized_pnl_of_trade": realized,
                                     },
                                     "methodology": _WHATIF_METHODOLOGY,
                                     "field_dictionary": {
                                         "market_value": "Change in portfolio market value after the hypothetical trade.",
                                         "unrealized_pnl": "Change in unrealized P&L after the trade (merged lot at weighted cost).",
                                         "n_positions": "Change in position count (a buy into a held symbol adds no position).",
                                         "total_equity": "Change in cash plus market value; None when the book tracks no cash.",
                                         "cash_delta": "Cash paid (negative) or received (positive) in the trade currency.",
                                         "realized_pnl_of_trade": "P&L realized by a sell against the lot cost; 0 for a buy.",
                                     }},
                              sources=list(set((before.sources or []) + (after.sources or []))),
                              warnings=warnings)


def _finite_number(raw: Any) -> float | None:
    """Parse a user number; None when blank or not a finite number."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if np.isfinite(value) else None


def _whatif_cash_key(cash: dict[str, Any], ccy: str) -> str:
    """Return the key the book already uses for ``ccy`` (case-insensitive), else ``ccy``."""
    wanted = str(ccy).upper()
    for key in cash:
        if str(key).upper() == wanted:
            return key
    return ccy


def _whatif_inputs(params: dict[str, Any]) -> tuple[float, float, dict[str, Any] | None]:
    """Return (quantity, cost, problem). ``problem`` is set when a trade cannot be priced."""
    qty = _finite_number(params.get("quantity"))
    cost = _finite_number(params.get("cost"))
    raw_bad = [
        name for name in ("quantity", "cost")
        if params.get(name) not in (None, "") and _finite_number(params.get(name)) is None
    ]
    if raw_bad:
        return 0.0, 0.0, {
            "status": "input_error",
            "reason": f"non-numeric value for {', '.join(raw_bad)}",
            "missing": raw_bad,
            "next_actions": ["Enter numeric quantity and cost per share."],
        }
    missing = []
    if qty is None or qty == 0:
        missing.append("quantity")
    if cost is None or cost <= 0:
        missing.append("cost")
    if missing:
        return 0.0, 0.0, {
            "status": "needs_input",
            "reason": (
                "PORT_WHATIF needs an explicit non-zero quantity and a positive cost per "
                "share; no placeholder cost is assumed, so no P&L is computed."
            ),
            "missing": missing,
            "next_actions": [
                "Enter the hypothetical quantity and the cost per share you would pay or receive.",
            ],
        }
    return float(qty), float(cost), None


_WHATIF_METHODOLOGY = (
    "Clone the current portfolio state, apply the hypothetical trade, rerun portfolio "
    "analytics before and after, then display the delta. A buy merges into the held lot "
    "of the same symbol at a weighted-average cost; a sell reduces the lot and realizes "
    "P&L against its cost. Cash is debited (buy) or credited (sell) at the typed cost. "
    "Shorts are not modelled: a sell larger than the holding is refused."
)
_QTY_EPS = 1e-9


def _whatif_apply_trade(positions: list[Any], instrument: Instrument, qty: float,
                        cost: float) -> tuple[list[Any], str, float, dict[str, Any] | None]:
    """Return ``(positions, trade_currency, realized_pnl, problem)`` for one trade.

    Lots match by symbol and currency. A buy adds to the first matching lot at a
    weighted-average cost, or opens a lot when none is held. A sell reduces the
    matching lots first-in-first-out and realizes ``(cost - lot cost)`` on the sold
    quantity. A sell larger than the holding, or any trade on a held short lot, is
    refused, so no negative lot is ever booked.
    """
    from dataclasses import replace

    symbol = instrument.symbol
    held_idx = [
        i for i, pos in enumerate(positions)
        if pos.instrument.symbol == symbol and abs(float(pos.quantity)) > _QTY_EPS
    ]
    trade_ccy = positions[held_idx[0]].currency if held_idx else "USD"
    same = [i for i in held_idx if positions[i].currency == trade_ccy]
    if any(float(positions[i].quantity) < 0 for i in same):
        return positions, trade_ccy, 0.0, {
            "status": "input_error",
            "reason": f"{symbol} is held as a short lot; what-if trades on a short are not modelled.",
            "missing": [],
            "next_actions": ["Pick a symbol with a long holding or none."],
        }
    if qty > 0:
        if not same:
            new_lot = PortfolioPosition(instrument=instrument, quantity=qty, avg_cost=cost,
                                        currency=trade_ccy)
            return [*positions, new_lot], trade_ccy, 0.0, None
        first = same[0]
        lot = positions[first]
        lot_qty = float(lot.quantity)
        new_qty = lot_qty + qty
        new_avg = (lot_qty * float(lot.avg_cost) + qty * cost) / new_qty
        merged = list(positions)
        merged[first] = replace(lot, quantity=new_qty, avg_cost=new_avg)
        return merged, trade_ccy, 0.0, None
    sell = -qty
    held = sum(float(positions[i].quantity) for i in same)
    if sell > held + _QTY_EPS:
        return positions, trade_ccy, 0.0, {
            "status": "input_error",
            "reason": (f"selling {sell:g} {symbol} exceeds the {held:g} held; "
                       "short sales are not modelled."),
            "missing": ["quantity"],
            "next_actions": [f"Enter a sell quantity of at most {held:g}."],
        }
    remaining = sell
    realized = 0.0
    updated = list(positions)
    closed: set[int] = set()
    for i in same:
        if remaining <= _QTY_EPS:
            break
        lot = positions[i]
        taken = min(float(lot.quantity), remaining)
        realized += (cost - float(lot.avg_cost)) * taken
        remaining -= taken
        left = float(lot.quantity) - taken
        if left <= _QTY_EPS:
            closed.add(i)
        else:
            updated[i] = replace(lot, quantity=left)
    kept = [pos for i, pos in enumerate(updated) if i not in closed]
    return kept, trade_ccy, realized, None


class _MemoQuoteAdapter:
    """Serves repeat fetches of one identical request from memory within one what-if call.

    PORT runs twice (before and after the trade), so without this every quote is
    fetched twice. Concurrent identical requests (two lots of one symbol priced in
    one gather) share one in-flight fetch. A failed fetch is forgotten, so a later
    request retries it.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._memo: dict[str, asyncio.Future[Any]] = {}

    async def fetch(self, request: Any) -> Any:
        key = repr(request)
        task = self._memo.get(key)
        if task is None:
            task = asyncio.ensure_future(self._inner.fetch(request))
            self._memo[key] = task
        try:
            # shield: one caller being cancelled must not cancel the shared fetch.
            return await asyncio.shield(task)
        except Exception:
            if self._memo.get(key) is task:
                del self._memo[key]
            raise

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _twr(period_returns: list[float]) -> float:
    """Time-weighted return: ∏(1+r_i) − 1."""
    factor = 1.0
    for r in period_returns:
        factor *= (1.0 + r)
    return factor - 1.0


def _total_daily_returns(close: pd.Series, dividends: pd.Series | None) -> list[float]:
    """Daily total returns (close + dividend) / prior close - 1, dividends reinvested."""
    prev = close.shift(1)
    cash = dividends.reindex(close.index).fillna(0.0) if dividends is not None else 0.0
    ret = (close + cash) / prev - 1.0
    return [float(r) for r in ret.iloc[1:].tolist() if np.isfinite(r)]


def _max_drawdown(daily_returns: list[float]) -> float | None:
    """Most negative peak-to-trough move of the compounded index (<= 0), or None."""
    if not daily_returns:
        return None
    index = np.concatenate([[1.0], np.cumprod(1.0 + np.asarray(daily_returns, dtype=float))])
    running_peak = np.maximum.accumulate(index)
    return float((index / running_peak - 1.0).min())


def _split_factors(split_ratios: pd.Series) -> np.ndarray:
    """Cumulative split factor S_t: the product of split ratios on bars <= t.

    A bar with no split holds 0 or NaN and counts as 1; 4:1 is 4.0, 1:10 is 0.1.
    Adjusted price = raw close * S_t, so a split leaves the adjusted series
    continuous and is never read as a loss (TRA#2).
    """
    ratios = pd.to_numeric(split_ratios, errors="coerce").fillna(0.0).to_numpy(dtype=float)
    return np.cumprod(np.where(ratios > 0, ratios, 1.0))


def _unconfirmed_split_dates(close: pd.Series) -> list[Any]:
    """Bars whose one-day raw move matches a whole-number split ratio.

    Used only when the source reported no split events: it names the candidate
    so the user can verify it. Moves under 1.8x are never candidates.
    """
    raw = close.to_numpy(dtype=float)
    found: list[Any] = []
    for i in range(1, len(raw)):
        prev, cur = raw[i - 1], raw[i]
        if not (prev > 0 and cur > 0):
            continue
        move = max(prev, cur) / min(prev, cur)
        if move < 1.8:
            continue
        nearest = round(move)
        if nearest >= 2 and abs(move - nearest) / nearest <= 0.02:
            found.append(close.index[i])
    return found


def _as_percent(value: float | None) -> float | None:
    """A fraction as a percent, or None when the fraction is missing or not finite."""
    if value is None:
        return None
    number = float(value)
    return number * 100.0 if np.isfinite(number) else None


def _safe_irr(cashflows: list[tuple[datetime, float]]) -> float | None:
    """_irr that returns None instead of raising or returning a non-real rate (TRA#2)."""
    try:
        rate = _irr(cashflows)
        if rate is None:
            return None
        value = float(rate)
    except (OverflowError, ZeroDivisionError, ValueError, TypeError):
        return None
    if not np.isfinite(value) or value <= -1.0:
        return None
    return value


def _irr(cashflows: list[tuple[datetime, float]],
         guess: float = 0.05, max_iter: int = 100, tol: float = 1e-6) -> float | None:
    """XIRR — Newton-Raphson on (date, amount) pairs."""
    if not cashflows:
        return None
    sorted_cf = sorted(cashflows, key=lambda x: x[0])
    t0 = sorted_cf[0][0]
    days = [(d - t0).days / 365.25 for d, _ in sorted_cf]
    amts = [a for _, a in sorted_cf]
    rate = guess
    for _ in range(max_iter):
        f = sum(a / (1 + rate) ** t for a, t in zip(amts, days))
        df = sum(-t * a / (1 + rate) ** (t + 1) for a, t in zip(amts, days))
        if df == 0:
            return None
        new_rate = rate - f / df
        if abs(new_rate - rate) < tol:
            return new_rate
        rate = new_rate
    return rate


@FunctionRegistry.register
class TRAFunction(BaseFunction):
    """TRA — Total Return Analysis (TWR + IRR + price + dividend)."""
    code = "TRA"
    name = "Total Return Analysis"
    category = "portfolio"
    description = "Total return (dividends reinvested), IRR, CAGR, price return and max drawdown."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("TRA requires instrument")
        years = int(params.get("years", 5))
        # Default-polarity flip (2026-09-08): TRA computes from the live
        # price feed by default; ``reference=true`` opts into the labelled
        # template history. A live-feed failure may still fall back to the
        # template, but only WITH an explicit warning + honest data_mode.
        live = not _truthy(params.get("reference"))
        warnings: list[str] = []
        metadata: dict[str, Any] = {"live": False, "data_mode": "modeled"}
        if live:
            try:
                if not self.deps.yfinance:
                    raise RuntimeError("yfinance adapter unavailable")
                import asyncio
                df = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.OHLCV, instrument=instrument,
                    start=datetime.now(timezone.utc) - timedelta(days=365 * years),
                    interval="1d",
                    )),
                    timeout=float(params.get("quote_timeout", 8)),
                )
                sources = ["yfinance"]
                metadata = {"live": True, "data_mode": "live_yfinance"}
            except Exception as exc:
                from showme.engine.functions.portfolio.btfw import _template_history
                df = _template_history(365 * years)
                sources = ["total_return_model"]
                metadata = {"live": False, "fallback": True, "data_mode": "modeled"}
                warnings.append(
                    "TRA fell back to the labelled template history after the live "
                    f"price feed failed: {exc}"
                )
        else:
            from showme.engine.functions.portfolio.btfw import _template_history
            df = _template_history(365 * years)
            sources = ["total_return_model"]
        if df.empty:
            from showme.engine.functions.portfolio.btfw import _template_history
            df = _template_history(365 * years)
            sources = ["total_return_model"]
            metadata = {"live": False, "fallback": True, "data_mode": "modeled"}
            if live:
                warnings.append(
                    "Live price feed returned no usable observations; showing the "
                    "labelled template history instead."
                )
        close = df["close"]
        # A source without a dividend series (e.g. the template) must not read
        # as "no dividends paid": keep the count/total null and say so.
        dividends_known = "dividends" in df.columns
        divs = df["dividends"] if dividends_known else pd.Series(dtype=float)
        if not dividends_known:
            warnings.append(
                "Dividend events are unavailable from this data source; dividend "
                "fields are null and the IRR excludes dividends."
            )
        div_count = int((divs > 0).sum()) if dividends_known else None
        div_total = float(divs.sum()) if dividends_known else None
        # TRA#2/#3: splits are removed before any return is measured. A source
        # that reports split events gives an adjusted series; one that does not
        # is labelled, and a one-day move that looks like a split is named.
        splits_known = "splits" in df.columns
        if splits_known:
            split_factor = _split_factors(df["splits"])
            splits_count: int | None = int(
                (pd.to_numeric(df["splits"], errors="coerce").fillna(0.0) > 0).sum()
            )
        else:
            # No split column: closes stay unadjusted and split_adjusted says so.
            split_factor = np.ones(len(close), dtype=float)
            splits_count = None
            for bar in _unconfirmed_split_dates(close):
                warnings.append(
                    f"TRA: the one-day price move on {bar.strftime('%Y-%m-%d')} matches a stock "
                    "split ratio, but the source reported no split event. Verify it before "
                    "reading total return or drawdown."
                )
        adj_close = pd.Series(close.to_numpy(dtype=float) * split_factor, index=close.index)
        adj_divs = (
            pd.Series(divs.to_numpy(dtype=float) * split_factor, index=divs.index)
            if dividends_known else divs
        )
        price_ret = float(adj_close.iloc[-1] / adj_close.iloc[0] - 1)
        # TRA#2: TWR is a total return: each day compounds (close + dividend) over
        # the prior close, so dividends are reinvested at the ex-date close. With
        # no dividend series the figure is price-only and the basis says so.
        total_basis = (
            "dividends_reinvested" if dividends_known else "price_only_dividends_unavailable"
        )
        daily_returns = _total_daily_returns(adj_close, adj_divs if dividends_known else None)
        twr = _twr(daily_returns)
        # TRA#3: drawdown on the full daily total-return index, not on sampled points.
        max_dd = _max_drawdown(daily_returns)
        # MWR / IRR — buy 1 share at start, dividends as positive cashflows, sell at end
        cashflows = [(adj_close.index[0].to_pydatetime(), -float(adj_close.iloc[0]))]
        for d, amt in zip(adj_divs.index, adj_divs.values):
            if amt and amt > 0:
                cashflows.append((d.to_pydatetime(), float(amt)))
        cashflows.append((adj_close.index[-1].to_pydatetime(), float(adj_close.iloc[-1])))
        irr = _safe_irr(cashflows)
        # Audit Q3 #6: CAGR exponent must use the ACTUAL elapsed years
        # between first and last observation, not the requested window. When
        # yfinance returns 2y of history because the ticker is younger than
        # the request, using `years=5` understates CAGR by ~40%.
        try:
            actual_years = max(
                (close.index[-1] - close.index[0]).days / 365.25, 1e-6
            )
        except Exception:
            actual_years = float(years)
        # CAGR annualizes the same total-return growth factor as TWR (TRA#2).
        growth_factor = 1.0 + twr
        cagr = (
            growth_factor ** (1 / actual_years) - 1
            if actual_years > 0 and adj_close.iloc[0] > 0 and growth_factor > 0
            else None
        )
        # Chart points: every Nth bar, always including the last observation so
        # the growth readout and the "last" date agree.
        step = max(1, len(close) // 250)
        sample_positions = sorted(set(range(0, len(close), step)) | {len(close) - 1})
        base_adj = float(adj_close.iloc[0])
        cagr_out = float(cagr) if cagr is not None else None
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "price_return_total": price_ret,
                "twr_total": twr,
                "irr_annualized": irr,
                "cagr": cagr_out,
                "dividends_count": div_count,
                "dividends_total": div_total,
                "n_observations": int(len(close)),
                "first_date": close.index[0].strftime("%Y-%m-%d"),
                "last_date":  close.index[-1].strftime("%Y-%m-%d"),
                "split_adjusted": splits_known,
                "splits_count": splits_count,
                "series": [
                    {
                        "date": idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10],
                        "close": float(close.iloc[pos]),
                        "split_adjusted_close": float(adj_close.iloc[pos]),
                        "growth_of_1": float(adj_close.iloc[pos] / base_adj) if base_adj else None,
                    }
                    for pos in sample_positions
                    for idx in [close.index[pos]]
                ],
                "summary": {
                    "symbol": instrument.symbol,
                    "price_return_total": price_ret,
                    "twr_total": twr,
                    "irr_annualized": irr,
                    "cagr": cagr_out,
                    "max_drawdown": max_dd,
                    "total_return_basis": total_basis,
                    "dividends_total": div_total,
                    "split_adjusted": splits_known,
                },
                "total_return_basis": total_basis,
                "max_drawdown": max_dd,
                # TRA#4: card slots read top-level scalars; "_pct" keys hold the
                # same figures as percent (132.99 means 132.99%).
                "twr_total_pct": _as_percent(twr),
                "irr_annualized_pct": _as_percent(irr),
                "cagr_pct": _as_percent(cagr_out),
                "price_return_total_pct": _as_percent(price_ret),
                "max_drawdown_pct": _as_percent(max_dd),
                "methodology": (
                    "Compute price return from the first and last split-adjusted closes (dividends "
                    "excluded). Splits are adjusted by multiplying each close by the cumulative split "
                    "ratio up to that bar, so a split is not read as a loss. Compound daily total returns "
                    "(split-adjusted close plus split-adjusted dividend, over the prior close) for "
                    "time-weighted return, with dividends reinvested at their ex-date close. Estimate "
                    "IRR from buy, dividend, and sale cash flows. Max drawdown is measured on the full "
                    "daily total-return index. Without a dividend series, TWR and CAGR are price-only "
                    "and total_return_basis says so. Without split events, split_adjusted is false and "
                    "a one-day move that matches a split ratio is named in the warnings."
                ),
                "field_dictionary": {
                    "split_adjusted": "True when the source reported split events and closes were adjusted for them; false when no split events were available.",
                    "splits_count": "Number of split events inside the window; null when the source reported none.",
                    "split_adjusted_close": "Close multiplied by the cumulative split ratio; continuous across splits.",
                    "price_return_total": "Last split-adjusted close divided by first split-adjusted close minus one; excludes dividends.",
                    "twr_total": "Time-weighted total return from daily returns with dividends reinvested; price-only when total_return_basis says so.",
                    "irr_annualized": "Money-weighted annualized return from cash flows.",
                    "cagr": "Annualized growth of the same basis as twr_total over the observed span.",
                    "max_drawdown": "Most negative peak-to-trough move of the daily total-return index (<= 0).",
                    "total_return_basis": "dividends_reinvested when a dividend series was available, else price_only_dividends_unavailable.",
                    "growth_of_1": "Value of one invested dollar over the selected period (split-adjusted price basis, no dividends, sampled points).",
                    "twr_total_pct": "twr_total as a percent (card value).",
                    "irr_annualized_pct": "irr_annualized as a percent (card value).",
                    "cagr_pct": "cagr as a percent (card value).",
                    "price_return_total_pct": "price_return_total as a percent (card value).",
                    "max_drawdown_pct": "max_drawdown as a percent (card value).",
                },
            },
            sources=sources,
            warnings=warnings,
            metadata=metadata,
        )


@FunctionRegistry.register
class MARSFunction(BaseFunction):
    """MARS — Multi-Asset Risk (ETF-proxy factor regression, not Fama-French)."""
    code = "MARS"
    name = "Multi-Asset Risk"
    category = "portfolio"
    description = (
        "Factor-risk screen: regresses a multi-asset return series on six ETF "
        "total-return proxies (SPY, IWM, VLUE, MTUM, QUAL, USMV) and reports "
        "factor betas, R-squared, volatility and 95% VaR / ETL."
    )

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        # Build factor returns from live ETF proxies by default. ``reference=true``
        # or an explicit ``live=false`` (the PortfolioAnalytics toggle) serves the
        # local multi-asset template series.
        proxies = {
            "MKT": "SPY",      # market
            "SMB": "IWM",      # small-cap
            "HML": "VLUE",     # value
            "MOM": "MTUM",     # momentum
            "QMJ": "QUAL",     # quality
            "BAB": "USMV",     # low-vol
        }
        years = int(params.get("years", 3))
        days = 365 * years
        # Default-polarity flip (2026-09-08): MARS regresses on live ETF
        # factor proxies by default; ``reference=true`` opts into the
        # labelled template series.
        live = not _truthy(params.get("reference"))
        # ``live`` is sent by PortfolioAnalytics. The router injects live=true by
        # default, so only an explicit falsy value switches to the template.
        if params.get("live") is not None and not _truthy(params.get("live")):
            live = False

        symbols = params.get("symbols") or []
        if isinstance(symbols, str):
            symbols = [s.strip() for s in symbols.split(",") if s.strip()]
        if not symbols:
            symbol = params.get("symbol") or (instrument.symbol if instrument else None)
            symbols = [symbol] if symbol else ["BTCUSDT", "AAPL", "EURUSD", "GC=F"]

        if not live:
            from showme.engine.functions.portfolio.rpar import _template_returns
            factors = _template_returns(list(proxies.keys()), days)
            port_ret = _template_returns([str(s) for s in symbols], days)
            weights = np.ones(port_ret.shape[1]) / max(port_ret.shape[1], 1)
            port_series = (port_ret * weights).sum(axis=1)
            return _mars_result(
                code=self.code,
                instrument=instrument,
                factors=factors,
                port_series=port_series,
                sources=["multi_asset_risk_model"],
                metadata={"live": False, "data_mode": "modeled"},
                factors_are_template=True,
                portfolio_is_template=True,
            )

        async def _ret(sym):
            try:
                inst = Instrument(symbol=sym, asset_class=AssetClass.ETF)
                if self.deps.symbol_registry:
                    resolved = await self.deps.symbol_registry.resolve(sym)
                    if resolved:
                        inst = resolved
                df = await self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.OHLCV,
                    instrument=inst,
                    start=datetime.now(timezone.utc) - timedelta(days=days),
                    interval="1d",
                ))
                return close_to_daily_returns(df)
            except Exception:
                return pd.Series(dtype=float)
        import asyncio
        fetch_budget = _mars_fetch_budget(params)

        async def _ret_with_timeout(sym: str) -> pd.Series:
            try:
                return await asyncio.wait_for(_ret(sym), timeout=fetch_budget)
            except Exception:
                return pd.Series(dtype=float)

        # Factor proxies and universe legs are fetched concurrently: running them
        # back to back could exceed the router's per-function budget.
        proxy_fetch = (
            asyncio.gather(*(_ret_with_timeout(s) for s in proxies.values()))
            if self.deps.yfinance
            else asyncio.sleep(0, result=[])
        )
        symbol_fetch = asyncio.gather(*(_ret_with_timeout(str(s)) for s in symbols))
        rs, rets = await asyncio.gather(proxy_fetch, symbol_fetch)
        # Audit Q3 #7: pairwise covariance for factor regression universe.
        factors = align_return_series(zip(proxies.keys(), rs), policy="pairwise")
        warnings: list[str] = []
        # R2 M-6: ``align_return_series(policy="pairwise")`` silently drops
        # empty proxy series, so when only SOME of the six ETF factors
        # answer, the regression used to run on the survivors while wearing
        # full-live metadata with no warning. Compare the surviving columns
        # against the expected proxy set: full coverage keeps the live
        # labels; any shortfall downgrades to the labelled fallback.
        loaded_proxies = [str(c) for c in factors.columns]
        missing_proxies = sorted(set(proxies) - set(loaded_proxies))
        metadata: dict[str, Any] = {"live": True, "data_mode": "live_yfinance"}
        factors_template = False
        portfolio_template = False
        if factors.empty:
            from showme.engine.functions.portfolio.rpar import _template_returns
            factors = _template_returns(list(proxies.keys()), days)
            factors_template = True
            metadata = {"live": False, "fallback": True, "data_mode": "modeled"}
            warnings.append(
                "Live ETF factor proxies were unavailable; factor loadings are "
                "computed against the labelled template factor series."
            )
        elif missing_proxies:
            metadata = {"live": False, "fallback": True, "data_mode": "modeled"}
            warnings.append(
                "Live ETF factor proxy data was unavailable for: "
                + ", ".join(missing_proxies)
                + f"; the factor regression ran on {len(loaded_proxies)}/"
                + f"{len(proxies)} loaded proxies ("
                + ", ".join(loaded_proxies) + ") only."
            )
        metadata["factor_proxies_loaded"] = loaded_proxies
        port_ret = align_return_series(
            zip((str(s) for s in symbols), rets), policy="pairwise"
        )
        requested_legs = list(dict.fromkeys(str(s) for s in symbols))
        if port_ret.empty:
            from showme.engine.functions.portfolio.rpar import _template_returns
            port_ret = _template_returns(requested_legs, days)
            portfolio_template = True
            metadata.update({"live": False, "fallback": True, "data_mode": "modeled"})
            metadata["legs_loaded"] = []
            metadata["legs_missing"] = requested_legs
            warnings.append(
                "Live symbol return series were unavailable; portfolio legs use "
                "the labelled template series."
            )
        else:
            # The pairwise join drops any leg with no series. Disclose the drop and
            # downgrade the label, as for a partial factor-proxy shortfall.
            loaded_legs = [str(c) for c in port_ret.columns]
            missing_legs = [s for s in requested_legs if s not in loaded_legs]
            metadata["legs_loaded"] = loaded_legs
            metadata["legs_missing"] = missing_legs
            if missing_legs:
                metadata.update({"live": False, "fallback": True, "data_mode": "modeled"})
                warnings.append(
                    "Live return series unavailable for: " + ", ".join(missing_legs)
                    + f"; the portfolio was computed over the {len(loaded_legs)}/"
                    + f"{len(requested_legs)} requested legs that loaded ("
                    + ", ".join(loaded_legs) + ") only."
                )
        weights = np.ones(port_ret.shape[1]) / max(port_ret.shape[1], 1)
        port_series = (port_ret * weights).sum(axis=1)
        return _mars_result(
            code=self.code,
            instrument=instrument,
            factors=factors,
            port_series=port_series,
            sources=["yfinance"] if metadata.get("live") else ["multi_asset_risk_model"],
            warnings=warnings,
            metadata=metadata,
            factors_are_template=factors_template,
            portfolio_is_template=portfolio_template,
        )


_MARS_FETCH_BUDGET_SECONDS = 8.0


def _mars_fetch_budget(params: dict[str, Any]) -> float:
    """Per-series live fetch budget for MARS.

    The router merges a generic ``quote_timeout=3`` into every routed call,
    which is too tight for six ETF proxies plus the universe. MARS therefore
    floors its budget at 8 s; a larger explicit ``quote_timeout`` still wins.
    """
    try:
        requested = float(params.get("quote_timeout") or 0)
    except (TypeError, ValueError):
        requested = 0.0
    return max(_MARS_FETCH_BUDGET_SECONDS, requested)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _mars_result(
    *,
    code: str,
    instrument: Instrument | None,
    factors: pd.DataFrame,
    port_series: pd.Series,
    sources: list[str],
    warnings: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    factors_are_template: bool = False,
    portfolio_is_template: bool = False,
) -> FunctionResult:
    factors = _tz_naive_frame(factors)
    port_series = _tz_naive_series(port_series)
    warnings = list(warnings or [])
    metadata = dict(metadata or {})
    joined = pd.concat([port_series.rename("portfolio"), factors], axis=1).dropna()
    if joined.empty:
        # R2 H-2: when the live legs have zero overlapping dates the
        # regression silently ran on template rows while wearing the
        # caller's live metadata. The template injection is now labelled:
        # warning + fallback metadata + model source, so a disjoint-
        # calendar payload can never wear a LIVE pill.
        from showme.engine.functions.portfolio.rpar import _template_returns
        fallback = _template_returns(["portfolio", "MKT", "SMB", "HML", "MOM", "QMJ", "BAB"], 252)
        joined = fallback
        warnings.append(
            "Live factor and portfolio series had no overlapping dates; "
            "regression output uses the labelled template series."
        )
        metadata["live"] = False
        metadata["fallback"] = True
        metadata["data_mode"] = "modeled"
        sources = ["multi_asset_risk_model"]
        factors_are_template = True
        portfolio_is_template = True
    # A regression is only a statistic when both sides are real series. Against
    # the labelled template the fit is exact by construction (R2 = 1, alpha = 0),
    # so R2, alpha, loadings and the sample count are withheld and disclosed.
    regression_valid = not (factors_are_template or portfolio_is_template)
    port_series = joined["portfolio"]
    alpha: float | None = None
    loadings: dict[str, float] = {}
    r2: float | None = None
    samples: int | None = None
    vifs: dict[str, float | None] = {}
    max_vif: float | None = None
    collinearity_state = "not_estimated"
    if regression_valid:
        y = joined["portfolio"].values
        X = joined.drop(columns="portfolio").values
        Xc = np.column_stack([np.ones(X.shape[0]), X])
        beta, *_ = np.linalg.lstsq(Xc, y, rcond=None)
        alpha = float(beta[0])
        loadings = {f: float(b) for f, b in zip(joined.columns[1:], beta[1:])}
        resid = y - Xc @ beta
        ss_tot = float(((y - y.mean()) ** 2).sum())
        r2 = float(1 - (resid ** 2).sum() / ss_tot) if ss_tot else 0.0
        samples = int(len(joined))
        vifs = _factor_vifs(joined.drop(columns="portfolio"))
        finite_vifs = [v for v in vifs.values() if v is not None]
        max_vif = max(finite_vifs) if finite_vifs else None
        if any(v is None for v in vifs.values()):
            collinearity_state = "perfect"
        elif any(v > _VIF_COLLINEAR_THRESHOLD for v in finite_vifs):
            collinearity_state = "high"
        else:
            collinearity_state = "ok"
        if collinearity_state != "ok":
            flagged = [f for f, v in vifs.items() if v is None or v > _VIF_COLLINEAR_THRESHOLD]
            if collinearity_state == "perfect":
                detail = "are perfectly collinear with the other proxies"
            else:
                detail = f"are collinear (max VIF {max_vif:.1f}, threshold {_VIF_COLLINEAR_THRESHOLD:g})"
            warnings.append(
                "Factor proxies " + ", ".join(flagged) + " " + detail + ". The ETF proxies "
                "are long-only and largely move with the market, so individual betas are "
                "not separable exposures; read R-squared and alpha, not single loadings."
            )
    else:
        warnings.append(
            "Regression statistics (R-squared, alpha, factor loadings) are not "
            "estimated because the regression input is the labelled template series."
        )
    # Audit Q3 #15 — guard annualized volatility against <30-sample noise.
    if len(port_series) < 30:
        ann_vol = None
    else:
        ann_vol = float(port_series.std() * np.sqrt(252))
    # Audit Q3 #14 — VaR/ETL as POSITIVE LOSSES so the UI shows them as
    # losses without re-interpreting the sign.
    raw_quantile = float(np.percentile(port_series, 5))
    port_var_95 = -raw_quantile if raw_quantile < 0 else 0.0
    tail_returns = port_series[port_series <= raw_quantile]
    if tail_returns.empty:
        port_etl_95 = port_var_95
    else:
        mean_tail = float(tail_returns.mean())
        port_etl_95 = -mean_tail if mean_tail < 0 else 0.0
    # Retain historical *signed* fields for backward compatibility.
    var_95 = raw_quantile
    etl_95 = float(tail_returns.mean()) if not tail_returns.empty else raw_quantile
    return FunctionResult(
        code=code,
        instrument=instrument,
        data={
            "alpha_daily": alpha,
            "alpha_annualized": alpha * 252 if alpha is not None else None,
            "factor_loadings": loadings,
            "rows": [
                {
                    "factor": factor,
                    "loading": loading,
                    "abs_loading": abs(loading),
                    "meaning": _factor_meaning(factor),
                }
                for factor, loading in loadings.items()
            ],
            "r_squared": r2,
            "regression_state": "estimated" if regression_valid else "not_estimated_template",
            "factor_vif": vifs,
            "max_vif": max_vif,
            "collinearity_state": collinearity_state,
            # Basis of the volatility and VaR figures: the portfolio series actually used.
            "risk_basis": "template_series" if portfolio_is_template else "live_series",
            "annualized_volatility": ann_vol,
            "var_95_daily": var_95,
            "etl_95_daily": etl_95,
            # Audit Q3 #14 + #15: positive-loss fields, prefer these in UI.
            "var_95_daily_loss": port_var_95,
            "etl_95_daily_loss": port_etl_95,
            "annualized_volatility_data_state": (
                "ok" if ann_vol is not None else "insufficient_samples"
            ),
            "samples": samples,
            "summary": {
                "r_squared": r2,
                "annualized_volatility": ann_vol,
                "var_95_daily": var_95,
                "var_95_daily_loss": port_var_95,
                "samples": samples,
            },
            "methodology": (
                "Regress the selected multi-asset portfolio return series on ETF factor proxies. "
                "Loadings measure sensitivity to market, size, value, momentum, quality, and low-volatility "
                "factors; VaR/ETL are estimated from daily portfolio returns."
            ),
            "field_dictionary": {
                "loading": "Regression beta to the named factor return.",
                "r_squared": "Share of portfolio return variance explained by the factor model.",
                "var_95_daily": "5th percentile daily portfolio return.",
                "etl_95_daily": "Average daily return on days worse than VaR.",
            },
        },
        sources=sources,
        warnings=warnings or [],
        metadata=metadata or {},
    )


def _factor_meaning(factor: str) -> str:
    # Each label names the ETF whose total return is the regressor. These are
    # long-only proxies, so a beta is sensitivity to that ETF, not a long-short
    # size, value or momentum premium.
    return {
        "MKT": "Beta to SPY total return (broad US equity proxy).",
        "SMB": "Beta to IWM total return (small-cap ETF proxy, not a long-short size premium).",
        "HML": "Beta to VLUE total return (value ETF proxy, not a long-short value premium).",
        "MOM": "Beta to MTUM total return (momentum ETF proxy).",
        "QMJ": "Beta to QUAL total return (quality ETF proxy).",
        "BAB": "Beta to USMV total return (low-volatility ETF proxy).",
    }.get(factor, "Portfolio factor sensitivity.")


_VIF_COLLINEAR_THRESHOLD = 10.0


def _factor_vifs(factors: pd.DataFrame) -> dict[str, float | None]:
    """Variance inflation factor per proxy: 1 / (1 - R^2) of that proxy on the others.

    None means the proxy is an exact linear combination of the others (infinite
    VIF), which JSON cannot carry, so it is reported as None and flagged upstream.
    """
    values = factors.values.astype(float)
    out: dict[str, float | None] = {}
    for j, name in enumerate(factors.columns):
        y = values[:, j]
        others = np.delete(values, j, axis=1)
        if others.shape[1] == 0:
            out[str(name)] = 1.0
            continue
        Xo = np.column_stack([np.ones(others.shape[0]), others])
        beta, *_ = np.linalg.lstsq(Xo, y, rcond=None)
        resid = y - Xo @ beta
        ss_tot = float(((y - y.mean()) ** 2).sum())
        if ss_tot <= 0:
            out[str(name)] = None
            continue
        slack = float((resid ** 2).sum()) / ss_tot  # 1 - R^2 of proxy on the others
        out[str(name)] = None if slack <= 1e-9 else float(1.0 / slack)
    return out


def _tz_naive_series(series: pd.Series) -> pd.Series:
    out = series.copy()
    try:
        out.index = pd.to_datetime(out.index, utc=True).tz_convert(None)
    except Exception:
        try:
            out.index = pd.to_datetime(out.index).tz_localize(None)
        except Exception:
            pass
    return out


def _tz_naive_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    try:
        out.index = pd.to_datetime(out.index, utc=True).tz_convert(None)
    except Exception:
        try:
            out.index = pd.to_datetime(out.index).tz_localize(None)
        except Exception:
            pass
    return out
