"""CORR - Correlation matrix function.

Pairwise return correlation across an arbitrary universe plus the integrated
Correlation Impact workflow from the standalone Impactor prototype.
"""

from __future__ import annotations

import asyncio
import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


MARKET_TYPES = ("Equity", "Index", "FX", "Crypto", "Commodity", "Rates", "Credit")
DEFAULT_IMPACT_SYMBOLS = ["AAPL", "SPX", "EURUSD", "BTCUSDT", "GC=F", "US10Y", "CDXIG"]

SAMPLE_MARKET_BETA = {
    "Equity": 1.05,
    "Index": 0.90,
    "FX": -0.20,
    "Crypto": 1.65,
    "Commodity": 0.35,
    "Rates": -0.55,
    "Credit": -0.75,
}

SAMPLE_MARKET_VOL = {
    "Equity": 0.015,
    "Index": 0.011,
    "FX": 0.005,
    "Crypto": 0.035,
    "Commodity": 0.018,
    "Rates": 0.008,
    "Credit": 0.006,
}

ASSET_NAMES = {
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corp.",
    "NVDA": "NVIDIA Corp.",
    "TSLA": "Tesla Inc.",
    "AMZN": "Amazon.com Inc.",
    "SPX": "S&P 500 Index",
    "^GSPC": "S&P 500 Index",
    "SPY": "S&P 500 ETF",
    "NDX": "Nasdaq 100 Index",
    "^NDX": "Nasdaq 100 Index",
    "QQQ": "Nasdaq 100 ETF",
    "IWM": "Russell 2000 ETF",
    "EURUSD": "Euro / U.S. Dollar",
    "GBPUSD": "British Pound / U.S. Dollar",
    "USDJPY": "U.S. Dollar / Yen",
    "DXY=X": "U.S. Dollar Index",
    "BTCUSDT": "Bitcoin / Tether",
    "BTC-USD": "Bitcoin / U.S. Dollar",
    "ETHUSDT": "Ether / Tether",
    "ETH-USD": "Ether / U.S. Dollar",
    "SOLUSDT": "Solana / Tether",
    "GC=F": "Gold Futures",
    "CL=F": "WTI Crude Futures",
    "XAU": "Gold Spot",
    "XAUUSD": "Gold Spot / U.S. Dollar",
    "US10Y": "U.S. 10Y Yield",
    "DE10Y": "Germany 10Y Yield",
    "CDXIG": "CDX IG Spread",
    "ITRXEUR": "iTraxx Europe Spread",
}

INDEX_SYMBOLS = {
    "SPX",
    "NDX",
    "DJI",
    "RUT",
    "VIX",
    "^GSPC",
    "^NDX",
    "^DJI",
    "^RUT",
    "^VIX",
    "SPY",
    "QQQ",
    "IWM",
    "EFA",
    "EEM",
}
RATE_SYMBOLS = {"US1Y", "US2Y", "US5Y", "US10Y", "US20Y", "US30Y", "DE10Y", "GB10Y", "JP10Y"}
CREDIT_SYMBOLS = {"CDXIG", "CDXHY", "ITRXEUR", "ITRXMAIN", "ITRXCROSSOVER"}
COMMODITY_SYMBOLS = {"GC=F", "CL=F", "SI=F", "HG=F", "NG=F", "XAU", "XAUUSD", "XAG", "XAGUSD", "GLD", "DBC"}
CRYPTO_ROOTS = {"BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "LINK", "TRX", "DOT", "MATIC"}
CURRENCY_CODES = {
    "USD",
    "EUR",
    "JPY",
    "GBP",
    "CHF",
    "CAD",
    "AUD",
    "NZD",
    "TRY",
    "CNH",
    "CNY",
    "MXN",
    "ZAR",
}


@FunctionRegistry.register
class CORRFunction(BaseFunction):
    code = "CORR"
    name = "Correlation Matrix"
    category = "portfolio"
    description = "Pearson + Spearman + downside correlation for a symbol set."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        symbols = _parse_symbols(params.get("symbols")) or list(DEFAULT_IMPACT_SYMBOLS)
        days = _bounded_int(params.get("days", 365), 30, 2520, 365)
        return_method = _normalize_return_method(params.get("return_method") or params.get("returns"))
        frequency = _normalize_frequency(params.get("frequency"))
        missing_policy = _normalize_missing_policy(params.get("missing_data_policy") or params.get("missing_policy"))
        live = _truthy(params.get("live_correlation") or params.get("live"))
        sources = ["computed_return_model"]
        coverage_status: dict[str, dict[str, Any]] = {}

        if live:
            price_series, coverage_status, used_yfinance = await self._live_price_series(symbols, days)
            if used_yfinance:
                sources = ["yfinance"]
            missing_symbols = [s for s in symbols if s not in {series["asset"]["symbol"] for series in price_series}]
            if missing_symbols:
                fallback_series = _generate_sample_price_series(_build_assets(missing_symbols), days)
                price_series.extend(fallback_series)
                if "computed_return_model" not in sources:
                    sources.append("computed_return_model")
                for symbol in missing_symbols:
                    previous = coverage_status.get(symbol, {})
                    previous_source = previous.get("source") or "live_provider"
                    previous_message = previous.get("message") or "no usable live close rows"
                    coverage_status[symbol] = {
                        "status": "computed_fallback",
                        "source": f"{previous_source}+computed_return_model",
                        "provider_symbol": _provider_symbol(symbol),
                        "message": f"Live price series unavailable ({previous_message}); deterministic reference series used.",
                    }
            if not price_series:
                price_series = _generate_sample_price_series(_build_assets(symbols), days)
                sources = ["computed_return_model"]
                coverage_status = {
                    symbol: {
                        "status": "computed_fallback",
                        "source": "computed_return_model",
                        "provider_symbol": _provider_symbol(symbol),
                        "message": "Live price engine returned no usable rows.",
                    }
                    for symbol in symbols
                }
        else:
            price_series = _generate_sample_price_series(_build_assets(symbols), days)
            coverage_status = {
                symbol: {
                    "status": "computed_reference",
                    "source": "computed_return_model",
                    "provider_symbol": _provider_symbol(symbol),
                    "message": "Deterministic provider-independent reference series.",
                }
                for symbol in symbols
            }

        frame = _build_return_frame(price_series, frequency, return_method, missing_policy)
        thin_symbols = [
            symbol
            for symbol in symbols
            if symbol not in frame or int(frame[symbol].dropna().shape[0]) < 2
        ]
        if thin_symbols:
            price_series = [
                series
                for series in price_series
                if series.get("asset", {}).get("symbol") not in set(thin_symbols)
            ]
            price_series.extend(_generate_sample_price_series(_build_assets(thin_symbols), days))
            if "computed_return_model" not in sources:
                sources.append("computed_return_model")
            for symbol in thin_symbols:
                previous = coverage_status.get(symbol, {})
                previous_source = previous.get("source") or "live_provider"
                previous_message = previous.get("message") or "live series did not produce two returns"
                coverage_status[symbol] = {
                    "status": "computed_fallback",
                    "source": f"{previous_source}+computed_return_model",
                    "provider_symbol": previous.get("provider_symbol") or _provider_symbol(symbol),
                    "message": (
                        f"Live series produced fewer than two usable returns ({previous_message}); "
                        "deterministic reference series used."
                    ),
                }
            frame = _build_return_frame(price_series, frequency, return_method, missing_policy)
        if frame.empty:
            price_series = _generate_sample_price_series(_build_assets(symbols), days)
            frame = _build_return_frame(price_series, frequency, return_method, missing_policy)
            sources = ["computed_return_model"]
            coverage_status = {
                symbol: {
                    "status": "computed_fallback",
                    "source": "computed_return_model",
                    "provider_symbol": _provider_symbol(symbol),
                    "message": "Correlation frame was empty; reference series used.",
                }
                for symbol in symbols
            }

        data = _correlation_payload(
            symbols=symbols,
            days=days,
            price_series=price_series,
            frame=frame,
            return_method=return_method,
            frequency=frequency,
            missing_policy=missing_policy,
            live=live,
            sources=sources,
            coverage_status=coverage_status,
        )
        warnings = [
            item["message"]
            for item in data.get("impactor", {}).get("bug_analysis", [])
            if item.get("severity") in {"warning", "critical"}
        ][:8]
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data=data,
            sources=sources,
            metadata={
                "days": days,
                "symbols": symbols,
                "live": live,
                "return_method": return_method,
                "frequency": frequency,
                "missing_data_policy": missing_policy,
                "impactor_integrated": True,
            },
            warnings=warnings,
        )

    async def _live_price_series(
        self,
        symbols: list[str],
        days: int,
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], bool]:
        async def _fetch(symbol: str) -> tuple[str, dict[str, Any] | None, dict[str, Any]]:
            provider_symbol = _provider_symbol(symbol)
            market = _infer_market(symbol)
            status: dict[str, Any] = {
                "status": "missing",
                "source": "live_provider",
                "provider_symbol": provider_symbol,
                "message": "",
            }
            candidates = _live_adapter_candidates(self.deps, market, symbol, provider_symbol)
            if not candidates:
                status["message"] = "no live adapter configured"
                return symbol, None, status
            last_error = ""
            for source_name, adapter, request_symbol, request_market in candidates:
                try:
                    inst = None
                    if source_name == "yfinance" and self.deps.symbol_registry:
                        try:
                            inst = await self.deps.symbol_registry.resolve(request_symbol)
                        except Exception:
                            inst = None
                    if inst is None:
                        inst = Instrument(
                            symbol=request_symbol,
                            asset_class=_asset_class_for_market(request_market),
                        )
                    df = await adapter.fetch(
                        DataRequest(
                            kind=DataKind.OHLCV,
                            instrument=inst,
                            start=datetime.now(timezone.utc) - timedelta(days=days),
                            interval="1d",
                            limit=max(days + 5, 90),
                            extra={"days": max(1, min(days, 365)), "timeout": 8},
                        )
                    )
                    series = _price_series_from_frame(symbol, df)
                    if series is None or len(series["points"]) < 3:
                        raise RuntimeError("insufficient close rows")
                    status.update(
                        {
                            "status": "live",
                            "source": source_name,
                            "provider_symbol": request_symbol,
                            "message": f"{len(series['points'])} close rows fetched.",
                        }
                    )
                    return symbol, series, status
                except Exception as exc:  # noqa: BLE001
                    last_error = f"{source_name}: {exc}"
                    status.update(
                        {
                            "source": source_name,
                            "provider_symbol": request_symbol,
                            "message": last_error,
                        }
                    )
                    continue
            status["message"] = last_error or "all live adapters returned empty"
            return symbol, None, status

        results = await asyncio.gather(*(_fetch(symbol) for symbol in symbols))
        price_series = [series for _, series, _ in results if series is not None]
        coverage_status = {symbol: status for symbol, _, status in results}
        used_yfinance = any(status.get("status") == "live" for _, _, status in results)
        return price_series, coverage_status, used_yfinance


def _correlation_payload(
    *,
    symbols: list[str],
    days: int,
    price_series: list[dict[str, Any]],
    frame: pd.DataFrame,
    return_method: str,
    frequency: str,
    missing_policy: str,
    live: bool,
    sources: list[str],
    coverage_status: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    ordered_symbols = [symbol for symbol in symbols if symbol in frame.columns]
    if not ordered_symbols:
        ordered_symbols = list(frame.columns)
    frame = frame.reindex(columns=ordered_symbols)
    pearson_df = frame.corr(method="pearson").round(3)
    spearman_df = frame.corr(method="spearman").round(3)
    market = frame.mean(axis=1, skipna=True)
    down = frame[market < 0]
    downside_df = down.corr().round(3) if not down.empty else pd.DataFrame()
    vol = {
        symbol: _round_or_none(float(frame[symbol].std(skipna=True) * _annualization_factor(frequency)))
        for symbol in ordered_symbols
    }
    pearson = _df_to_nested_dict(pearson_df)
    spearman = _df_to_nested_dict(spearman_df)
    downside = _df_to_nested_dict(downside_df)
    impactor = _build_impactor_payload(
        symbols=ordered_symbols,
        days=days,
        price_series=price_series,
        frame=frame,
        pearson=pearson,
        return_method=return_method,
        frequency=frequency,
        missing_policy=missing_policy,
        live=live,
        sources=sources,
        coverage_status=coverage_status,
    )
    return {
        "symbols": ordered_symbols,
        "pearson": pearson,
        "spearman": spearman,
        "downside": downside,
        "annualized_vol": vol,
        "samples": int(impactor["observation_range"]["max"]),
        "surface": _matrix_surface(pearson, spearman, downside),
        "rows": [
            {
                "symbol": symbol,
                "market": _infer_market(symbol),
                "annualized_vol": float(vol.get(symbol) or 0.0),
                "avg_pearson_correlation": _avg_off_diagonal(pearson, symbol),
                "avg_downside_correlation": _avg_off_diagonal(downside, symbol),
                "return_observations": int(frame[symbol].dropna().shape[0]) if symbol in frame else 0,
            }
            for symbol in ordered_symbols
        ],
        "summary": {
            "symbols": len(ordered_symbols),
            "samples": int(impactor["observation_range"]["max"]),
            "method": "correlation_impact_matrix",
            "return_method": return_method,
            "frequency": frequency,
            "missing_data_policy": missing_policy,
            "markets": sorted({row["market"] for row in impactor["market_coverage"]}),
        },
        "methodology": (
            "Resolve the selected universe, fetch or build close price series, resample to the selected "
            "frequency, compute log or simple returns, apply the selected missing-data policy, then estimate "
            "Pearson, Spearman, downside correlation, covariance, and ranked positive/negative pairs."
        ),
        "field_dictionary": {
            "pearson": "Linear return correlation from -1 to +1.",
            "spearman": "Rank correlation, less sensitive to extreme return magnitudes.",
            "downside": "Correlation estimated only on negative equal-weight universe days.",
            "annualized_vol": "Return standard deviation multiplied by the selected-period annualization factor.",
            "covariance": "Sample covariance of overlapping return observations.",
            "observations": "Pairwise overlapping return count after frequency and missing-data handling.",
        },
        "impactor": impactor,
    }


def _build_impactor_payload(
    *,
    symbols: list[str],
    days: int,
    price_series: list[dict[str, Any]],
    frame: pd.DataFrame,
    pearson: dict[str, dict[str, float | None]],
    return_method: str,
    frequency: str,
    missing_policy: str,
    live: bool,
    sources: list[str],
    coverage_status: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    price_by_symbol = {series["asset"]["symbol"]: series for series in price_series}
    matrix = _impactor_matrix(frame, symbols)
    observation_values = [int(cell["observations"]) for cell in matrix]
    observation_range = {
        "min": min(observation_values) if observation_values else 0,
        "max": max(observation_values) if observation_values else 0,
    }
    coverage = _market_coverage(symbols, price_by_symbol, frame, coverage_status)
    return_summary = _return_series_summary(symbols, frame, frequency)
    positive_pairs, negative_pairs = _top_pairs(matrix)
    selected_pair = _selected_pair_detail(
        frame,
        symbols,
        positive_pairs[0] if positive_pairs else None,
        frequency,
    )
    bug_analysis = _bug_analysis(symbols, coverage, matrix, observation_range, sources, live)
    steps = _analysis_steps(
        symbols=symbols,
        coverage=coverage,
        matrix=matrix,
        observation_range=observation_range,
        bug_analysis=bug_analysis,
        return_method=return_method,
        frequency=frequency,
        missing_policy=missing_policy,
        sources=sources,
    )
    return {
        "enabled": True,
        "label": "Correlation Impact Analysis",
        "origin": {
            "tool": "Impactor prototype",
            "repo_path": "/Users/nazmi/Desktop/Projeler/Impactor",
            "integration": "ported provider-independent correlation engine inside CORR",
        },
        "formula": {
            "correlation": "rho(i,j) = cov(r_i, r_j) / (sigma_i * sigma_j)",
            "log_return": "ln(P_t / P_t-1)",
            "simple_return": "(P_t / P_t-1) - 1",
            "selected_return": "log_return" if return_method == "log" else "simple_return",
        },
        "options": {
            "symbols": symbols,
            "days": days,
            "return_method": return_method,
            "frequency": frequency,
            "missing_data_policy": missing_policy,
            "source_mode": "live_with_transparent_fallback" if live else "computed_reference",
            "sources": sources,
        },
        "provider_contract": {
            "asset": ["symbol", "name", "market", "currency", "venue"],
            "price_point": ["date", "close"],
            "markets": list(MARKET_TYPES),
        },
        "observation_range": observation_range,
        "market_coverage": coverage,
        "analysis_steps": steps,
        "return_series_summary": return_summary,
        "matrix": matrix,
        "heatmap_rows": _heatmap_rows(symbols, pearson),
        "top_positive_pairs": positive_pairs,
        "top_negative_pairs": negative_pairs,
        "selected_pair": selected_pair,
        "pair_details": [selected_pair] if selected_pair else [],
        "bug_analysis": bug_analysis,
        "csv_columns": ["y", "x", "correlation", "covariance", "observations"],
    }


def _analysis_steps(
    *,
    symbols: list[str],
    coverage: list[dict[str, Any]],
    matrix: list[dict[str, Any]],
    observation_range: dict[str, int],
    bug_analysis: list[dict[str, Any]],
    return_method: str,
    frequency: str,
    missing_policy: str,
    sources: list[str],
) -> list[dict[str, Any]]:
    live_count = sum(1 for row in coverage if row.get("status") == "live")
    fallback_count = sum(1 for row in coverage if "fallback" in str(row.get("status")))
    return [
        {
            "step": 1,
            "stage": "Universe resolution",
            "action": "Normalize symbols and infer market type.",
            "output": f"{len(symbols)} instruments across {len({row['market'] for row in coverage})} markets.",
            "status": "ok",
        },
        {
            "step": 2,
            "stage": "Market data binding",
            "action": "Map symbols to provider tickers and collect close series.",
            "output": f"{live_count} live series, {fallback_count} transparent fallback series, sources={','.join(sources)}.",
            "status": "warn" if fallback_count else "ok",
        },
        {
            "step": 3,
            "stage": "Frequency sampling",
            "action": "Keep last close in each selected period.",
            "output": frequency,
            "status": "ok",
        },
        {
            "step": 4,
            "stage": "Return transform",
            "action": "Convert prices to log or simple returns.",
            "output": "ln(P_t/P_t-1)" if return_method == "log" else "(P_t/P_t-1)-1",
            "status": "ok",
        },
        {
            "step": 5,
            "stage": "Missing-data policy",
            "action": "Apply pairwise, intersection, or forward-fill alignment.",
            "output": missing_policy,
            "status": "ok",
        },
        {
            "step": 6,
            "stage": "Covariance matrix",
            "action": "Compute sample covariance and Pearson rho for every pair.",
            "output": f"{len(matrix)} cells, observations {observation_range['min']}-{observation_range['max']}.",
            "status": "ok" if matrix else "error",
        },
        {
            "step": 7,
            "stage": "Pair ranking",
            "action": "Rank strongest positive and negative non-diagonal pairs.",
            "output": "top positive / top negative tables generated",
            "status": "ok",
        },
        {
            "step": 8,
            "stage": "Bug scan",
            "action": "Check coverage gaps, non-finite cells, thin samples, and missing markets.",
            "output": f"{len([item for item in bug_analysis if item['severity'] != 'info'])} actionable findings.",
            "status": "warn" if any(item["severity"] != "info" for item in bug_analysis) else "ok",
        },
    ]


def _bug_analysis(
    symbols: list[str],
    coverage: list[dict[str, Any]],
    matrix: list[dict[str, Any]],
    observation_range: dict[str, int],
    sources: list[str],
    live: bool,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    missing_markets = [market for market in MARKET_TYPES if market not in {row.get("market") for row in coverage}]
    if missing_markets:
        findings.append(
            {
                "function": "CORR",
                "component": "market_coverage",
                "severity": "warning",
                "status": "open",
                "message": f"Universe does not include these markets: {', '.join(missing_markets)}.",
                "fix": "Add at least one symbol for every missing market before comparing cross-asset correlations.",
            }
        )
    fallback_rows = [row for row in coverage if "fallback" in str(row.get("status"))]
    if fallback_rows:
        findings.append(
            {
                "function": "CORR",
                "component": "market_data",
                "severity": "warning" if live else "info",
                "status": "open" if live else "accepted",
                "message": f"{len(fallback_rows)} symbols used transparent computed fallback instead of live closes.",
                "fix": "Wire a live provider for the fallback symbols or replace unavailable symbols with provider-supported tickers.",
            }
        )
    empty_rows = [row for row in coverage if int(row.get("return_observations") or 0) < 2]
    if empty_rows:
        findings.append(
            {
                "function": "CORR",
                "component": "return_engine",
                "severity": "critical",
                "status": "open",
                "message": f"{len(empty_rows)} symbols have fewer than two return observations.",
                "fix": "Increase lookback, change frequency, or check provider mapping.",
            }
        )
    if observation_range["max"] < 30:
        findings.append(
            {
                "function": "CORR",
                "component": "sample_size",
                "severity": "warning",
                "status": "open",
                "message": f"Maximum pairwise sample is only {observation_range['max']} observations.",
                "fix": "Use at least 90 daily observations for a less fragile correlation estimate.",
            }
        )
    non_finite = [cell for cell in matrix if cell.get("correlation") is None]
    if non_finite:
        findings.append(
            {
                "function": "CORR",
                "component": "matrix",
                "severity": "warning",
                "status": "open",
                "message": f"{len(non_finite)} matrix cells are N/A due to zero variance or missing overlap.",
                "fix": "Inspect the coverage table and remove flat or missing series.",
            }
        )
    if not findings:
        findings.append(
            {
                "function": "CORR",
                "component": "impactor_integration",
                "severity": "info",
                "status": "passed",
                "message": f"{len(symbols)} symbols produced finite correlation output from {', '.join(sources)}.",
                "fix": "No action required.",
            }
        )
    return findings


def _market_coverage(
    symbols: list[str],
    price_by_symbol: dict[str, dict[str, Any]],
    frame: pd.DataFrame,
    coverage_status: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        series = price_by_symbol.get(symbol)
        points = list(series.get("points", [])) if series else []
        dates = [point["date"] for point in points]
        status = coverage_status.get(symbol, {})
        rows.append(
            {
                "symbol": symbol,
                "name": ASSET_NAMES.get(symbol, symbol),
                "market": _infer_market(symbol),
                "provider_symbol": status.get("provider_symbol") or _provider_symbol(symbol),
                "source": status.get("source") or "computed_return_model",
                "status": status.get("status") or "computed_reference",
                "price_points": len(points),
                "return_observations": int(frame[symbol].dropna().shape[0]) if symbol in frame else 0,
                "first_date": min(dates) if dates else None,
                "last_date": max(dates) if dates else None,
                "message": status.get("message") or "",
            }
        )
    return rows


def _return_series_summary(symbols: list[str], frame: pd.DataFrame, frequency: str) -> list[dict[str, Any]]:
    factor = _annualization_factor(frequency)
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        values = pd.to_numeric(frame.get(symbol), errors="coerce").dropna() if symbol in frame else pd.Series(dtype=float)
        rows.append(
            {
                "symbol": symbol,
                "market": _infer_market(symbol),
                "observations": int(values.shape[0]),
                "mean_return": _round_or_none(float(values.mean())) if not values.empty else None,
                "volatility": _round_or_none(float(values.std())) if values.shape[0] > 1 else None,
                "annualized_volatility": _round_or_none(float(values.std() * factor)) if values.shape[0] > 1 else None,
                "min_return": _round_or_none(float(values.min())) if not values.empty else None,
                "max_return": _round_or_none(float(values.max())) if not values.empty else None,
                "first_return_date": values.index.min().date().isoformat() if not values.empty else None,
                "last_return_date": values.index.max().date().isoformat() if not values.empty else None,
            }
        )
    return rows


def _impactor_matrix(frame: pd.DataFrame, symbols: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for y in symbols:
        for x in symbols:
            detail = _pair_stats(frame, y, x)
            rows.append(
                {
                    "y": y,
                    "x": x,
                    "left": y,
                    "right": x,
                    "market_y": _infer_market(y),
                    "market_x": _infer_market(x),
                    "correlation": _round_or_none(detail["correlation"], 6),
                    "covariance": _round_or_none(detail["covariance"], 10),
                    "observations": int(detail["observations"]),
                }
            )
    return rows


def _pair_stats(frame: pd.DataFrame, left: str, right: str) -> dict[str, Any]:
    if left not in frame or right not in frame:
        return {"correlation": None, "covariance": None, "observations": 0, "left_vol": None, "right_vol": None, "overlap": []}
    if left == right:
        values = pd.to_numeric(frame[left], errors="coerce").dropna()
        variance = float(values.var()) if values.shape[0] > 1 else None
        vol = math.sqrt(variance) if variance is not None and variance >= 0 else None
        overlap = pd.DataFrame({left: values, right: values})
        return {
            "correlation": 1.0 if values.shape[0] > 1 and vol and vol > 0 else None,
            "covariance": variance,
            "observations": int(values.shape[0]),
            "left_vol": vol,
            "right_vol": vol,
            "overlap": overlap,
        }
    overlap = frame[[left, right]].dropna()
    if overlap.shape[0] < 2:
        return {"correlation": None, "covariance": None, "observations": int(overlap.shape[0]), "left_vol": None, "right_vol": None, "overlap": []}
    left_values = overlap[left].astype(float)
    right_values = overlap[right].astype(float)
    covariance = float(left_values.cov(right_values))
    left_vol = float(left_values.std())
    right_vol = float(right_values.std())
    denominator = left_vol * right_vol
    corr = None if denominator == 0 else covariance / denominator
    return {
        "correlation": corr,
        "covariance": covariance,
        "observations": int(overlap.shape[0]),
        "left_vol": left_vol,
        "right_vol": right_vol,
        "overlap": overlap,
    }


def _top_pairs(matrix: list[dict[str, Any]], limit: int = 8) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pairs = [
        cell
        for cell in matrix
        if cell["left"] < cell["right"] and cell.get("correlation") is not None
    ]
    ranked_positive = sorted(pairs, key=lambda cell: float(cell["correlation"]), reverse=True)[:limit]
    ranked_negative = sorted(pairs, key=lambda cell: float(cell["correlation"]))[:limit]
    return [_pair_row(cell) for cell in ranked_positive], [_pair_row(cell) for cell in ranked_negative]


def _pair_row(cell: dict[str, Any]) -> dict[str, Any]:
    return {
        "left": cell["left"],
        "right": cell["right"],
        "market_pair": f"{cell['market_y']} / {cell['market_x']}",
        "correlation": cell["correlation"],
        "covariance": cell["covariance"],
        "observations": cell["observations"],
    }


def _selected_pair_detail(
    frame: pd.DataFrame,
    symbols: list[str],
    pair: dict[str, Any] | None,
    frequency: str,
) -> dict[str, Any] | None:
    if pair:
        left = pair["left"]
        right = pair["right"]
    elif len(symbols) >= 2:
        left, right = symbols[0], symbols[1]
    else:
        return None
    detail = _pair_stats(frame, left, right)
    overlap = detail.get("overlap")
    preview: list[dict[str, Any]] = []
    if isinstance(overlap, pd.DataFrame) and not overlap.empty:
        sample = pd.concat([overlap.head(6), overlap.tail(6)]).drop_duplicates()
        preview = [
            {
                "date": idx.date().isoformat() if hasattr(idx, "date") else str(idx),
                "left_return": _round_or_none(float(row[left]), 8),
                "right_return": _round_or_none(float(row[right]), 8),
            }
            for idx, row in sample.iterrows()
        ]
    return {
        "left": left,
        "right": right,
        "market_pair": f"{_infer_market(left)} / {_infer_market(right)}",
        "correlation": _round_or_none(detail["correlation"], 6),
        "covariance": _round_or_none(detail["covariance"], 10),
        "observations": int(detail["observations"]),
        "left_volatility": _round_or_none(detail["left_vol"], 8),
        "right_volatility": _round_or_none(detail["right_vol"], 8),
        "annualization_factor": _annualization_factor(frequency),
        "overlap_sample": preview,
    }


def _heatmap_rows(symbols: list[str], pearson: dict[str, dict[str, float | None]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for y in symbols:
        row: dict[str, Any] = {"symbol": y, "market": _infer_market(y)}
        for x in symbols:
            row[x] = (pearson.get(y) or {}).get(x)
        rows.append(row)
    return rows


def _build_return_frame(
    price_series: list[dict[str, Any]],
    frequency: str,
    return_method: str,
    missing_policy: str,
) -> pd.DataFrame:
    close_by_symbol: dict[str, pd.Series] = {}
    for series in price_series:
        symbol = series["asset"]["symbol"]
        points = series.get("points") or []
        if not points:
            continue
        idx = pd.to_datetime([point["date"] for point in points], errors="coerce")
        close = pd.to_numeric([point["close"] for point in points], errors="coerce")
        prices = pd.Series(close, index=idx).dropna()
        prices = prices[prices > 0].sort_index()
        if not prices.empty:
            close_by_symbol[symbol] = prices.groupby(level=0).last()
    if not close_by_symbol:
        return pd.DataFrame()
    prices = pd.concat(close_by_symbol, axis=1).sort_index()
    if frequency == "weekly":
        prices = prices.resample("W-FRI").last()
    elif frequency == "monthly":
        prices = prices.resample("ME").last()
    if missing_policy == "forward_fill":
        prices = prices.ffill()
    if return_method == "log":
        returns = np.log(prices / prices.shift(1))
    else:
        returns = prices.pct_change()
    returns = returns.replace([np.inf, -np.inf], np.nan)
    if missing_policy == "intersection":
        returns = returns.dropna(how="any")
    else:
        returns = returns.dropna(how="all")
    return returns


def _generate_sample_price_series(assets: list[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=max(days, 60))
    dates = pd.bdate_range(start=start, end=end)
    if len(dates) < 3:
        dates = pd.bdate_range(end=end, periods=60)
    global_returns = [0.00015 + _gaussian(index + 7) * 0.008 for index, _ in enumerate(dates)]
    risk_off_returns = [_gaussian(index + 113) * 0.004 for index, _ in enumerate(dates)]
    series: list[dict[str, Any]] = []
    for asset_index, asset in enumerate(assets):
        price = _base_price(asset)
        symbol_seed = sum(ord(char) for char in asset["symbol"])
        points: list[dict[str, Any]] = []
        market = asset["market"]
        for index, date in enumerate(dates):
            beta = SAMPLE_MARKET_BETA[market]
            vol = SAMPLE_MARKET_VOL[market]
            idiosyncratic = _gaussian(symbol_seed + index * (asset_index + 3)) * vol
            risk_off = risk_off_returns[index] if market in {"Rates", "Credit", "FX"} else -0.35 * risk_off_returns[index]
            crypto_momentum = math.sin(index / 19) * 0.006 if market == "Crypto" else 0.0
            commodity_cycle = math.sin(index / 31) * 0.004 if market == "Commodity" else 0.0
            daily_return = beta * global_returns[index] + risk_off + idiosyncratic + crypto_momentum + commodity_cycle
            price = max(price * math.exp(daily_return), 0.0001)
            points.append({"date": date.date().isoformat(), "close": round(float(price), 6)})
        series.append({"asset": asset, "points": points})
    return series


def _price_series_from_frame(symbol: str, frame: pd.DataFrame | None) -> dict[str, Any] | None:
    if frame is None or frame.empty:
        return None
    close_key = "close" if "close" in frame.columns else "Close" if "Close" in frame.columns else None
    if not close_key:
        return None
    close = pd.to_numeric(frame[close_key], errors="coerce").dropna()
    close = close[close > 0]
    if close.empty:
        return None
    idx = pd.to_datetime(close.index, utc=True, errors="coerce")
    mask = pd.notna(idx)
    if not bool(mask.any()):
        return None
    daily = pd.Series(close.to_numpy()[mask], index=pd.Index(idx[mask].date))
    daily = daily.groupby(level=0).last().sort_index()
    points = [{"date": date.isoformat(), "close": round(float(value), 6)} for date, value in daily.items()]
    asset = _build_assets([symbol])[0]
    return {"asset": asset, "points": points}


def _build_assets(symbols: list[str]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for symbol in symbols:
        market = _infer_market(symbol)
        assets.append(
            {
                "symbol": symbol,
                "name": ASSET_NAMES.get(symbol, symbol),
                "market": market,
                "currency": _currency_for_market(symbol, market),
                "venue": _venue_for_market(market),
            }
        )
    return assets


def _parse_symbols(raw: Any) -> list[str]:
    if raw is None:
        return []
    values: list[Any]
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                values = parsed if isinstance(parsed, list) else [text]
            except Exception:
                values = [text]
        else:
            values = text.replace("\n", ",").split(",")
    elif isinstance(raw, (list, tuple, set)):
        values = list(raw)
    else:
        values = [raw]
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        symbol = str(value).strip().strip("'\"").upper()
        if not symbol or symbol in seen:
            continue
        out.append(symbol)
        seen.add(symbol)
    return out[:30]


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _bounded_int(value: Any, low: int, high: int, default: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return max(low, min(high, parsed))


def _normalize_return_method(value: Any) -> str:
    text = str(value or "log").strip().lower()
    return "simple" if text in {"simple", "pct", "percent"} else "log"


def _normalize_frequency(value: Any) -> str:
    text = str(value or "daily").strip().lower()
    if text in {"weekly", "week", "w"}:
        return "weekly"
    if text in {"monthly", "month", "m"}:
        return "monthly"
    return "daily"


def _normalize_missing_policy(value: Any) -> str:
    text = str(value or "pairwise").strip().lower().replace("-", "_")
    if text in {"intersection", "intersect", "common"}:
        return "intersection"
    if text in {"forwardfill", "forward_fill", "ffill", "forward"}:
        return "forward_fill"
    return "pairwise"


def _infer_market(symbol: str) -> str:
    s = symbol.strip().upper()
    compact = s.replace("-", "").replace("/", "").replace("=X", "")
    root = compact
    for suffix in ("USDT", "USDC", "USD", "BTC", "ETH"):
        if root.endswith(suffix) and len(root) > len(suffix):
            root = root[: -len(suffix)]
            break
    if s in CREDIT_SYMBOLS:
        return "Credit"
    if s in RATE_SYMBOLS:
        return "Rates"
    if s in COMMODITY_SYMBOLS or s.endswith("=F"):
        return "Commodity"
    if s in INDEX_SYMBOLS:
        return "Index"
    if root in CRYPTO_ROOTS or s in {"BTC", "ETH", "SOL"}:
        return "Crypto"
    if s.endswith("=X") or (len(compact) == 6 and compact[:3] in CURRENCY_CODES and compact[3:] in CURRENCY_CODES):
        return "FX"
    return "Equity"


def _asset_class_for_market(market: str) -> AssetClass:
    return {
        "Crypto": AssetClass.CRYPTO,
        "FX": AssetClass.FX,
        "Commodity": AssetClass.COMMODITY,
        "Rates": AssetClass.BOND,
        "Credit": AssetClass.BOND,
        "Index": AssetClass.INDEX,
    }.get(market, AssetClass.EQUITY)


def _live_adapter_candidates(
    deps: Any,
    market: str,
    symbol: str,
    provider_symbol: str,
) -> list[tuple[str, Any, str, str]]:
    candidates: list[tuple[str, Any, str, str]] = []
    if market == "Crypto":
        for name in ("ccxt_failover", "coingecko"):
            adapter = getattr(deps, name, None)
            if adapter is not None:
                candidates.append((name, adapter, symbol, "Crypto"))
    yfinance = getattr(deps, "yfinance", None)
    if yfinance is not None:
        candidates.append(("yfinance", yfinance, provider_symbol, market))
    return candidates


def _provider_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    if s == "SPX":
        return "^GSPC"
    if s == "NDX":
        return "^NDX"
    if s == "DJI":
        return "^DJI"
    if s == "US10Y":
        return "^TNX"
    if s == "BTCUSDT":
        return "BTC-USD"
    if s == "ETHUSDT":
        return "ETH-USD"
    if s == "SOLUSDT":
        return "SOL-USD"
    if len(s) == 6 and s[:3] in CURRENCY_CODES and s[3:] in CURRENCY_CODES:
        return f"{s}=X"
    if s == "XAU" or s == "XAUUSD":
        return "GC=F"
    return s


def _currency_for_market(symbol: str, market: str) -> str:
    if market == "FX":
        clean = symbol.replace("=X", "")
        return clean[-3:] if len(clean) >= 6 else "USD"
    if market in {"Index", "Equity", "Crypto", "Commodity", "Rates", "Credit"}:
        return "USD"
    return "USD"


def _venue_for_market(market: str) -> str:
    return {
        "Equity": "US",
        "Index": "Index",
        "FX": "OTC",
        "Crypto": "Crypto",
        "Commodity": "Futures",
        "Rates": "Rates",
        "Credit": "Credit",
    }.get(market, "US")


def _base_price(asset: dict[str, Any]) -> float:
    symbol = asset["symbol"]
    market = asset["market"]
    symbol_seed = sum(ord(char) for char in symbol)
    if market == "FX":
        return 1 + (symbol_seed % 30) / 50
    if market == "Rates":
        return 2 + (symbol_seed % 300) / 100
    if market == "Credit":
        return 50 + (symbol_seed % 80)
    if market == "Crypto":
        return 62000 if symbol.startswith("BTC") else 3200 if symbol.startswith("ETH") else 140
    if market == "Commodity":
        return 2300 if symbol in {"GC=F", "XAU", "XAUUSD", "GLD"} else 78
    return 100 + (symbol_seed % 200)


def _gaussian(seed: int | float) -> float:
    u1 = max(_seeded_noise(seed), 0.0001)
    u2 = max(_seeded_noise(float(seed) + 19.19), 0.0001)
    return math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)


def _seeded_noise(seed: int | float) -> float:
    value = math.sin(float(seed) * 12.9898) * 43758.5453
    return value - math.floor(value)


def _annualization_factor(frequency: str) -> float:
    if frequency == "weekly":
        return math.sqrt(52)
    if frequency == "monthly":
        return math.sqrt(12)
    return math.sqrt(252)


def _round_or_none(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    try:
        if not math.isfinite(float(value)):
            return None
        return round(float(value), digits)
    except Exception:
        return None


def _df_to_nested_dict(df: pd.DataFrame) -> dict[str, dict[str, float | None]]:
    out: dict[str, dict[str, float | None]] = {}
    if df.empty:
        return out
    for row_label, row in df.iterrows():
        out[str(row_label)] = {
            str(col): _round_or_none(float(value), 3)
            for col, value in row.items()
        }
    return out


def _matrix_surface(
    pearson: dict[str, dict[str, float | None]],
    spearman: dict[str, dict[str, float | None]],
    downside: dict[str, dict[str, float | None]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for left, peers in pearson.items():
        for right, corr in peers.items():
            rows.append(
                {
                    "label": f"{left}/{right}",
                    "symbol": left,
                    "peer": right,
                    "correlation": corr,
                    "pearson": corr,
                    "spearman": (spearman.get(left) or {}).get(right, corr),
                    "downside": (downside.get(left) or {}).get(right, corr),
                }
            )
    return rows


def _avg_off_diagonal(matrix: dict[str, dict[str, float | None]], symbol: str) -> float | None:
    peers = matrix.get(symbol) or {}
    values = [
        float(value)
        for peer, value in peers.items()
        if peer != symbol and value is not None and math.isfinite(float(value))
    ]
    if not values:
        return None
    return round(float(sum(values) / len(values)), 4)


def _correlation_template(
    symbols: list[str],
    days: int,
    return_method: str = "log",
    frequency: str = "daily",
    missing_policy: str = "pairwise",
) -> dict[str, Any]:
    selected = _parse_symbols(symbols) or list(DEFAULT_IMPACT_SYMBOLS)
    price_series = _generate_sample_price_series(_build_assets(selected), days)
    frame = _build_return_frame(price_series, frequency, return_method, missing_policy)
    coverage_status = {
        symbol: {
            "status": "computed_reference",
            "source": "computed_return_model",
            "provider_symbol": _provider_symbol(symbol),
            "message": "Deterministic provider-independent reference series.",
        }
        for symbol in selected
    }
    return _correlation_payload(
        symbols=selected,
        days=days,
        price_series=price_series,
        frame=frame,
        return_method=return_method,
        frequency=frequency,
        missing_policy=missing_policy,
        live=False,
        sources=["computed_return_model"],
        coverage_status=coverage_status,
    )
