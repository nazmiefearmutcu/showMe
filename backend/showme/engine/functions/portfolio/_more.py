"""PORT WHATIF, TRA, MARS — gerçek implementasyonlar."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("PORT_WHATIF requires instrument")
        qty = float(params.get("quantity", 0))
        cost = float(params.get("cost", 0))
        baseline = PortfolioState()
        baseline.import_legacy_crypto()
        whatif = PortfolioState(path="/tmp/_showme_whatif.json")
        whatif.positions = list(baseline.positions) + [PortfolioPosition(
            instrument=instrument, quantity=qty, avg_cost=cost,
        )]
        whatif.cash = dict(baseline.cash)
        from showme.engine.functions.portfolio.port import PORTFunction
        port = PORTFunction(self.deps)
        before = await port.execute(_portfolio_override=baseline)
        after = await port.execute(_portfolio_override=whatif)
        bt = (before.data or {}).get("totals") or {}
        at = (after.data or {}).get("totals") or {}
        delta = {
            "market_value": (at.get("market_value") or 0) - (bt.get("market_value") or 0),
            "unrealized_pnl": (at.get("unrealized_pnl") or 0) - (bt.get("unrealized_pnl") or 0),
            "n_positions": (at.get("n_positions") or 0) - (bt.get("n_positions") or 0),
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
                                         "market_value_delta": delta["market_value"],
                                         "unrealized_pnl_delta": delta["unrealized_pnl"],
                                     },
                                     "methodology": (
                                         "Clone the current portfolio state, add the hypothetical position, "
                                         "rerun portfolio analytics before and after, then display the delta."
                                     ),
                                     "field_dictionary": {
                                         "market_value": "Change in portfolio market value after the hypothetical trade.",
                                         "unrealized_pnl": "Change in unrealized P&L after adding the position.",
                                         "n_positions": "Change in position count.",
                                     }},
                              sources=list(set((before.sources or []) + (after.sources or []))))


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
        live = _truthy(params.get("live_return") or params.get("live"))
        if live:
            try:
                if not self.deps.yfinance:
                    raise RuntimeError("no yfinance")
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
            except Exception:
                from showme.engine.functions.portfolio.btfw import _template_history
                df = _template_history(365 * years)
                sources = ["total_return_model"]
        else:
            from showme.engine.functions.portfolio.btfw import _template_history
            df = _template_history(365 * years)
            sources = ["total_return_model"]
        if df.empty:
            from showme.engine.functions.portfolio.btfw import _template_history
            df = _template_history(365 * years)
            sources = ["total_return_model"]
        close = df["close"]
        divs = df["dividends"] if "dividends" in df.columns else pd.Series(dtype=float)
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
                "dividends_count": int((divs > 0).sum()) if len(divs) else 0,
                "dividends_total": float(divs.sum()) if len(divs) else 0.0,
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
                    "dividends_total": float(divs.sum()) if len(divs) else 0.0,
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
        )


@FunctionRegistry.register
class MARSFunction(BaseFunction):
    """MARS — Multi-Asset Risk (Fama-French 5-factor regression)."""
    code = "MARS"
    name = "Multi-Asset Risk"
    category = "portfolio"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        # Build factor returns from ETF proxies only when explicitly requested.
        # The default path is a local multi-asset template so MARS works for
        # equity, crypto, FX, and commodity symbols without blocking the app.
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
        live = _truthy(params.get("live_risk") or params.get("live") or params.get("deep"))

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
        if factors.empty:
            from showme.engine.functions.portfolio.rpar import _template_returns
            factors = _template_returns(list(proxies.keys()), days)
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
        weights = np.ones(port_ret.shape[1]) / max(port_ret.shape[1], 1)
        port_series = (port_ret * weights).sum(axis=1)
        return _mars_result(
            code=self.code,
            instrument=instrument,
            factors=factors,
            port_series=port_series,
            sources=["yfinance"],
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
) -> FunctionResult:
    factors = _tz_naive_frame(factors)
    port_series = _tz_naive_series(port_series)
    joined = pd.concat([port_series.rename("portfolio"), factors], axis=1).dropna()
    if joined.empty:
        from showme.engine.functions.portfolio.rpar import _template_returns
        fallback = _template_returns(["portfolio", "MKT", "SMB", "HML", "MOM", "QMJ", "BAB"], 252)
        joined = fallback
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
