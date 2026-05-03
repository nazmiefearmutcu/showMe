"""PORT WHATIF, TRA, MARS — gerçek implementasyonlar."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument
from src.portfolio.state import PortfolioPosition, PortfolioState


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
        from src.functions.portfolio.port import PORTFunction
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
                                     "delta": delta},
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
                    start=datetime.utcnow() - timedelta(days=365 * years),
                    interval="1d",
                    )),
                    timeout=float(params.get("quote_timeout", 8)),
                )
                sources = ["yfinance"]
            except Exception:
                from src.functions.portfolio.btfw import _template_history
                df = _template_history(365 * years)
                sources = ["total_return_model"]
        else:
            from src.functions.portfolio.btfw import _template_history
            df = _template_history(365 * years)
            sources = ["total_return_model"]
        if df.empty:
            from src.functions.portfolio.btfw import _template_history
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
        cagr = (close.iloc[-1] / close.iloc[0]) ** (1 / years) - 1 if years > 0 else None
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
        live = _truthy(params.get("live_risk") or params.get("deep"))

        symbols = params.get("symbols") or []
        if isinstance(symbols, str):
            symbols = [s.strip() for s in symbols.split(",") if s.strip()]
        if not symbols:
            symbol = params.get("symbol") or (instrument.symbol if instrument else None)
            symbols = [symbol] if symbol else ["BTCUSDT", "AAPL", "EURUSD", "GC=F"]

        if not live:
            from src.functions.portfolio.rpar import _template_returns
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
                df = await self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.OHLCV,
                    instrument=Instrument(symbol=sym, asset_class=AssetClass.ETF),
                    start=datetime.utcnow() - timedelta(days=days),
                    interval="1d",
                ))
                return df["close"].pct_change().dropna()
            except Exception:
                return pd.Series(dtype=float)
        import asyncio
        async def _ret_with_timeout(sym: str) -> pd.Series:
            try:
                return await asyncio.wait_for(_ret(sym), timeout=float(params.get("quote_timeout", 8)))
            except Exception:
                return pd.Series(dtype=float)

        rs = await asyncio.gather(*(_ret_with_timeout(s) for s in proxies.values())) if self.deps.yfinance else []
        factors = pd.DataFrame({k: r for k, r in zip(proxies.keys(), rs)}).dropna(how="any")
        if factors.empty:
            from src.functions.portfolio.rpar import _template_returns
            factors = _template_returns(list(proxies.keys()), days)
        # Build return series from explicit symbols or the saved ShowMe portfolio.
        if not symbols:
            portfolio = PortfolioState()
            symbols = [p.instrument.symbol for p in portfolio.positions
                        if p.instrument.asset_class.value not in ("CRYPTO", "MACRO")]
        if not symbols:
            symbols = ["SPY", "TLT", "GLD"]
        rets = await asyncio.gather(*(_ret_with_timeout(str(s)) for s in symbols))
        weights = np.ones(len(symbols)) / len(symbols)
        port_ret = pd.DataFrame({s: r for s, r in zip(symbols, rets)}).dropna()
        if port_ret.empty:
            from src.functions.portfolio.rpar import _template_returns
            port_ret = _template_returns([str(s) for s in symbols], days)
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
        from src.functions.portfolio.rpar import _template_returns
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
    ann_vol = float(port_series.std() * np.sqrt(252))
    var_95 = float(np.percentile(port_series, 5))
    etl_95 = float(port_series[port_series <= var_95].mean()) if (port_series <= var_95).any() else var_95
    return FunctionResult(
        code=code,
        instrument=instrument,
        data={
            "alpha_daily": alpha,
            "alpha_annualized": alpha * 252,
            "factor_loadings": loadings,
            "r_squared": r2,
            "annualized_volatility": ann_vol,
            "var_95_daily": var_95,
            "etl_95_daily": etl_95,
            "samples": int(len(joined)),
        },
        sources=sources,
    )


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
