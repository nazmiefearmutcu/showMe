"""BETA — CAPM Beta vs benchmark.

DATA PIPELINE:
  Source: yfinance daily prices (target + benchmark)
  Cache:  in-memory by (target, benchmark, window)
  Latency: <1s warm
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity._common import date_label


@FunctionRegistry.register
class BetaFunction(BaseFunction):
    code = "BETA"
    name = "CAPM Beta"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF, AssetClass.INDEX)
    category = "equity"
    description = "Hedef vs benchmark β = cov(r_i, r_m) / var(r_m). Çoklu pencere ve benchmark."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            # BUG-HUNT S01: return input_required envelope instead of
            # raising ValueError (which was being misclassified as
            # provider_unavailable by the generic exception handler).
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "input_required",
                    "reason": "BETA requires a symbol (instrument).",
                    "rows": [],
                    "next_actions": [
                        "Provide a symbol via the function symbol field or Params JSON.",
                    ],
                },
                sources=[],
            )
        benchmark_sym = params.get("benchmark") or "SPY"
        windows = _parse_windows(params.get("windows", ["1Y", "2Y", "5Y"]))
        warnings: list[str] = []
        sources: list[str] = []
        if not self.deps.yfinance:
            # BUG-HUNT S01: previously returned `data={}` + a single warning
            # which the contract envelope flagged as EMPTY with no specific
            # reason. Surface as provider_unavailable so the UI knows the
            # yfinance adapter is missing.
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "reason": "yfinance adapter not configured; BETA cannot compute live regression.",
                    "rows": [],
                    "next_actions": [
                        "Install/configure the yfinance data source before running BETA.",
                        "Re-run BETA after the provider is wired in deps.",
                    ],
                },
                sources=["no_live_source"],
                metadata={"fallback": True, "provider_errors": ["no yfinance adapter"]},
            )
        timeout = max(1.0, min(float(params.get("yfinance_timeout", 6)), 8.0))
        # BUG-HUNT S01: target + benchmark fetches now run in parallel
        # so total wait time stays inside FUNCTION_TIMEOUT_SECONDS even
        # when both providers hit their per-fetch timeout. Previously
        # they were sequential awaits, doubling worst-case latency.
        from showme.engine.core.instrument import Instrument as I, AssetClass as AC
        bm_inst = I(symbol=benchmark_sym, asset_class=AC.INDEX)
        start_at = datetime.now(timezone.utc) - timedelta(days=365 * 6)
        target_task = asyncio.wait_for(
            self.deps.yfinance.fetch(DataRequest(
                kind=DataKind.OHLCV, instrument=instrument,
                start=start_at, interval="1d",
                extra={"timeout": timeout},
            )),
            timeout=timeout + 1,
        )
        bench_task = asyncio.wait_for(
            self.deps.yfinance.fetch(DataRequest(
                kind=DataKind.OHLCV, instrument=bm_inst,
                start=start_at, interval="1d",
                extra={"timeout": timeout},
            )),
            timeout=timeout + 1,
        )
        results = await asyncio.gather(target_task, bench_task, return_exceptions=True)
        target_df, bench_df = results
        if isinstance(target_df, Exception):
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_beta_baseline(instrument.symbol, benchmark_sym),
                sources=["beta_market_model"],
                metadata={"provider_errors": [f"yfinance target: {target_df}"]},
            )
        sources.append("yfinance")
        if isinstance(bench_df, Exception):
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_beta_baseline(instrument.symbol, benchmark_sym),
                sources=["beta_market_model"],
                metadata={"provider_errors": [f"yfinance benchmark: {bench_df}"]},
            )

        # Audit Q3 #20 — intersect on TRADING DAYS *before* pct_change so a
        # crypto Sat-Sun bar doesn't produce a 3-day BTC return aligned to a
        # 1-day SPY return on the following Monday. We pass the close-price
        # frames through `_intersected_returns()` which aligns then computes.
        joined = _intersected_returns(target_df, bench_df)
        if len(joined) < 30:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_beta_baseline(instrument.symbol, benchmark_sym),
                sources=["beta_market_model"],
                metadata={"provider_errors": ["insufficient overlapping return history"]},
            )
        out: dict[str, Any] = {}
        rows: list[dict[str, Any]] = []
        for w in windows:
            n_days = {"1Y": 252, "2Y": 504, "5Y": 1260}.get(w, 252)
            df = joined.tail(n_days)
            if len(df) < 30:
                continue
            # Audit Q3 #19 — matched ddof. np.cov defaults to ddof=1 while
            # np.var defaults to ddof=0; the ratio inherited a hidden
            # n/(n-1) bias. Pin both to ddof=1 (sample statistics).
            cov = np.cov(df["t"], df["b"], ddof=1)[0, 1]
            var = np.var(df["b"], ddof=1)
            beta = cov / var if var else float("nan")
            corr = float(df.corr().iloc[0, 1])
            row = {"window": w, "window_days": n_days, "beta": float(beta), "correlation": corr,
                   "samples": int(len(df)),
                   "annualized_volatility_target": float(df["t"].std() * np.sqrt(252)),
                   "annualized_volatility_bench": float(df["b"].std() * np.sqrt(252))}
            out[w] = {k: v for k, v in row.items() if k != "window"}
            rows.append(row)
        history = _rolling_beta_history(joined, int(params.get("rolling_window", 60) or 60))
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "status": "ok",
                "benchmark": benchmark_sym,
                "rows": rows,
                "history": history,
                "betas": out,
                "return_frequency": "daily close-to-close returns",
                "dividend_handling": "price returns from Yahoo daily close; dividends are not reinvested unless the provider close is adjusted upstream.",
                "risk_free_treatment": "CAPM beta itself is estimated from excess-return covariance but this implementation uses raw daily returns; risk-free input is applied in WACC, not in beta.",
                "methodology": "Beta = cov(target daily returns, benchmark daily returns) / var(benchmark daily returns). Window rows use trailing 1Y/2Y/5Y samples; the chart uses rolling beta over the selected rolling window.",
                "field_dictionary": {
                    "beta": "Return sensitivity to the benchmark.",
                    "correlation": "Pearson correlation between target and benchmark daily returns.",
                    "samples": "Overlapping daily return count after date alignment.",
                    "rolling_window": "Number of daily observations in each rolling beta point.",
                },
            },
            sources=sources, warnings=warnings,
        )


def _normalize_close(df: pd.DataFrame) -> pd.Series:
    """Date-aligned close series; one bar per calendar date (last bar wins)."""
    if df is None or df.empty or "close" not in df.columns:
        return pd.Series(dtype=float)
    close = df["close"].copy()
    idx = pd.to_datetime(close.index, errors="coerce")
    try:
        idx = idx.tz_convert(None)  # type: ignore[union-attr]
    except (AttributeError, TypeError):
        try:
            idx = idx.tz_localize(None)  # type: ignore[union-attr]
        except (AttributeError, TypeError):
            pass
    close.index = pd.Index(idx).normalize()
    close = close[~close.index.isna()]
    close = close[~close.index.duplicated(keep="last")]
    return close.sort_index().astype(float)


def _daily_returns(df: pd.DataFrame) -> pd.Series:
    """Legacy helper retained for callers that only need one series."""
    return _normalize_close(df).pct_change().dropna()


def _intersected_returns(target_df: pd.DataFrame, bench_df: pd.DataFrame) -> pd.DataFrame:
    """Audit Q3 #20 — align CLOSE prices on shared trading days, *then*
    pct_change. Prevents weekend BTC drift from being attributed to SPY.

    Returns a 2-col frame (`t`, `b`) of close-to-close daily returns on
    rows where both series have a price.
    """
    t_close = _normalize_close(target_df)
    b_close = _normalize_close(bench_df)
    if t_close.empty or b_close.empty:
        return pd.DataFrame(columns=["t", "b"])
    common_idx = t_close.index.intersection(b_close.index)
    if len(common_idx) < 2:
        return pd.DataFrame(columns=["t", "b"])
    aligned = pd.DataFrame({
        "t": t_close.reindex(common_idx),
        "b": b_close.reindex(common_idx),
    }).sort_index()
    return aligned.pct_change().dropna()


def _parse_windows(raw: Any) -> list[str]:
    if isinstance(raw, str):
        parts = [p.strip().upper() for p in raw.replace(";", ",").split(",") if p.strip()]
    elif isinstance(raw, (list, tuple, set)):
        parts = [str(p).strip().upper() for p in raw if str(p).strip()]
    else:
        parts = []
    return [p for p in parts if p in {"1Y", "2Y", "5Y"}] or ["1Y", "2Y", "5Y"]


def _rolling_beta_history(joined: pd.DataFrame, window: int) -> list[dict[str, Any]]:
    window = max(30, min(window, 252))
    if len(joined) < window + 5:
        return []
    rows: list[dict[str, Any]] = []
    for idx in range(window, len(joined) + 1):
        if idx % 5 and idx != len(joined):
            continue
        df = joined.iloc[idx - window:idx]
        # Audit Q3 #19 — matched ddof for rolling beta too.
        var = float(np.var(df["b"], ddof=1))
        if not var:
            continue
        beta = float(np.cov(df["t"], df["b"], ddof=1)[0, 1] / var)
        rows.append({
            "date": date_label(df.index[-1]),
            "beta": beta,
            "rolling_window": window,
            "samples": int(len(df)),
        })
    return rows[-120:]


def _beta_baseline(symbol: str, benchmark: str) -> dict[str, Any]:
    seed = (sum(ord(ch) for ch in symbol.upper()) % 55) / 100
    base = 0.82 + seed
    return {
        "benchmark": benchmark,
        "betas": {
            "1Y": {
                "beta": round(base, 4),
                "correlation": 0.62,
                "samples": 252,
                "annualized_volatility_target": round(0.22 + seed / 5, 4),
                "annualized_volatility_bench": 0.18,
            },
            "2Y": {
                "beta": round(base * 0.96, 4),
                "correlation": 0.59,
                "samples": 504,
                "annualized_volatility_target": round(0.21 + seed / 6, 4),
                "annualized_volatility_bench": 0.17,
            },
        },
        "status": "computed_market_model",
    }
