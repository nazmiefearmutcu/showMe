"""PORT WHATIF, TRA, MARS — gerçek implementasyonlar."""

from __future__ import annotations

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
    fetched twice. A failed fetch is not remembered, so the second run retries it.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._memo: dict[str, Any] = {}

    async def fetch(self, request: Any) -> Any:
        key = repr(request)
        if key not in self._memo:
            self._memo[key] = await self._inner.fetch(request)
        return self._memo[key]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _twr(period_returns: list[float]) -> float:
    """Time-weighted return: ∏(1+r_i) − 1."""
    factor = 1.0
    for r in period_returns:
        factor *= (1.0 + r)
    return factor - 1.0


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
        price_ret = float(close.iloc[-1] / close.iloc[0] - 1)
        # TWR (daily compounded)
        daily_returns = close.pct_change().dropna().tolist()
        twr = _twr(daily_returns)
        # MWR / IRR — buy 1 share at start, dividends as positive cashflows, sell at end
        cashflows = [(close.index[0].to_pydatetime(), -float(close.iloc[0]))]
        for d, amt in zip(divs.index, divs.values):
            if amt and amt > 0:
                cashflows.append((d.to_pydatetime(), float(amt)))
        cashflows.append((close.index[-1].to_pydatetime(), float(close.iloc[-1])))
        irr = _irr(cashflows)
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
        cagr = (
            (close.iloc[-1] / close.iloc[0]) ** (1 / actual_years) - 1
            if actual_years > 0 and close.iloc[0] > 0
            else None
        )
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "price_return_total": price_ret,
                "twr_total": twr,
                "irr_annualized": irr,
                "cagr": float(cagr) if cagr is not None else None,
                "dividends_count": div_count,
                "dividends_total": div_total,
                "n_observations": int(len(close)),
                "first_date": close.index[0].strftime("%Y-%m-%d"),
                "last_date":  close.index[-1].strftime("%Y-%m-%d"),
                "series": [
                    {
                        "date": idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10],
                        "close": float(value),
                        "growth_of_1": float(value / close.iloc[0]) if close.iloc[0] else None,
                    }
                    for idx, value in close.iloc[:: max(1, len(close) // 250)].items()
                ],
                "summary": {
                    "symbol": instrument.symbol,
                    "price_return_total": price_ret,
                    "twr_total": twr,
                    "irr_annualized": irr,
                    "dividends_total": div_total,
                },
                "methodology": (
                    "Compute price return from first and last adjusted closes, compound daily returns for "
                    "time-weighted return, and estimate XIRR from buy, dividend, and sale cash flows."
                ),
                "field_dictionary": {
                    "price_return_total": "Last close divided by first close minus one.",
                    "twr_total": "Time-weighted return from compounded daily returns.",
                    "irr_annualized": "Money-weighted annualized return from cash flows.",
                    "growth_of_1": "Value of one invested dollar over the selected period.",
                },
            },
            sources=sources,
            warnings=warnings,
            metadata=metadata,
        )


@FunctionRegistry.register
class MARSFunction(BaseFunction):
    """MARS — Multi-Asset Risk (Fama-French 5-factor regression)."""
    code = "MARS"
    name = "Multi-Asset Risk"
    category = "portfolio"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        # Build factor returns from live ETF proxies by default. Only
        # ``reference=true`` serves the local multi-asset template series.
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
        async def _ret_with_timeout(sym: str) -> pd.Series:
            try:
                return await asyncio.wait_for(_ret(sym), timeout=float(params.get("quote_timeout", 8)))
            except Exception:
                return pd.Series(dtype=float)

        rs = await asyncio.gather(*(_ret_with_timeout(s) for s in proxies.values())) if self.deps.yfinance else []
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
        if factors.empty:
            from showme.engine.functions.portfolio.rpar import _template_returns
            factors = _template_returns(list(proxies.keys()), days)
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
        # Build return series from explicit symbols or the saved ShowMe portfolio.
        if not symbols:
            portfolio = PortfolioState()
            symbols = [p.instrument.symbol for p in portfolio.positions
                        if p.instrument.asset_class.value not in ("CRYPTO", "MACRO")]
        if not symbols:
            symbols = ["SPY", "TLT", "GLD"]
        rets = await asyncio.gather(*(_ret_with_timeout(str(s)) for s in symbols))
        port_ret = align_return_series(
            zip((str(s) for s in symbols), rets), policy="pairwise"
        )
        if port_ret.empty:
            from showme.engine.functions.portfolio.rpar import _template_returns
            port_ret = _template_returns([str(s) for s in symbols], days)
            if "fallback" not in metadata:
                metadata = {"live": False, "fallback": True, "data_mode": "modeled"}
            warnings.append(
                "Live symbol return series were unavailable; portfolio legs use "
                "the labelled template series."
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
        )


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
    port_series = joined["portfolio"]
    y = joined["portfolio"].values
    X = joined.drop(columns="portfolio").values
    Xc = np.column_stack([np.ones(X.shape[0]), X])
    beta, *_ = np.linalg.lstsq(Xc, y, rcond=None)
    alpha = float(beta[0])
    loadings = {f: float(b) for f, b in zip(joined.columns[1:], beta[1:])}
    resid = y - Xc @ beta
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = float(1 - (resid ** 2).sum() / ss_tot) if ss_tot else 0.0
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
            "alpha_annualized": alpha * 252,
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
            "annualized_volatility": ann_vol,
            "var_95_daily": var_95,
            "etl_95_daily": etl_95,
            # Audit Q3 #14 + #15: positive-loss fields, prefer these in UI.
            "var_95_daily_loss": port_var_95,
            "etl_95_daily_loss": port_etl_95,
            "annualized_volatility_data_state": (
                "ok" if ann_vol is not None else "insufficient_samples"
            ),
            "samples": int(len(joined)),
            "summary": {
                "r_squared": r2,
                "annualized_volatility": ann_vol,
                "var_95_daily": var_95,
                "var_95_daily_loss": port_var_95,
                "samples": int(len(joined)),
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
    return {
        "MKT": "Broad equity market beta.",
        "SMB": "Small-cap versus large-cap tilt.",
        "HML": "Value versus growth tilt.",
        "MOM": "Momentum factor sensitivity.",
        "QMJ": "Quality factor sensitivity.",
        "BAB": "Low-volatility / betting-against-beta proxy.",
    }.get(factor, "Portfolio factor sensitivity.")


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
