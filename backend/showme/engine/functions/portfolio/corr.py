"""CORR - Correlation matrix function.

Pairwise return correlation across an arbitrary universe plus the integrated
Correlation Impact workflow from the standalone Impactor prototype.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

LOG = logging.getLogger("showme.corr")

# B6: when a single symbol's series is dominated by NaN (illiquid name, bad
# adapter mapping, etc.) it poisons every correlation involving it. Drop the
# offender BEFORE the matrix is built so downstream cells stay finite.
NAN_DROP_THRESHOLD = 0.30

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


MARKET_TYPES = ("Equity", "Index", "FX", "Crypto", "Commodity", "Rates", "Credit")
CORRELATION_METHODS = ("pearson", "spearman", "kendall")
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
        # CORR#7: read the declared seed inputs (universe, return_type, window,
        # min_overlap) as well as the pane parameters, and never ignore them silently.
        symbols = _parse_symbols(params.get("symbols") or params.get("universe")) or list(DEFAULT_IMPACT_SYMBOLS)
        days = _resolve_days(params)
        if days is None:
            return _input_error_result(
                f"Unsupported window {params.get('window')!r}; use a day count such as 90d or a year count such as 1Y.",
                instrument,
                symbols,
            )
        # CORR#7 residual: method, as_of and provider_mode are read here. Each one is
        # either honoured or refused with an explicit input_error; none is ignored.
        method = str(params.get("method") or "pearson").strip().lower()
        if method not in CORRELATION_METHODS:
            return _input_error_result(
                f"Unsupported method {params.get('method')!r}; use pearson, spearman or kendall.",
                instrument,
                symbols,
            )
        as_of_error = _as_of_error(params.get("as_of"))
        if as_of_error:
            return _input_error_result(as_of_error, instrument, symbols)
        provider_mode_requested = str(params.get("provider_mode") or "").strip().lower() or None
        if provider_mode_requested == "cached_snapshot":
            return _input_error_result(
                "provider_mode cached_snapshot is not served by CORR (no snapshot store); "
                "use live_exchange or delayed_reference, or omit it.",
                instrument,
                symbols,
            )
        if provider_mode_requested not in (None, "live_exchange", "delayed_reference"):
            return _input_error_result(
                f"Unsupported provider_mode {params.get('provider_mode')!r}; "
                "use live_exchange or delayed_reference, or omit it.",
                instrument,
                symbols,
            )
        raw_frequency = str(params.get("frequency") or "daily").strip().lower()
        if raw_frequency in {"1h", "h", "hourly", "1hour"}:
            return _input_error_result(
                "Hourly frequency is not supported by CORR; use 1d, 1wk or 1mo.",
                instrument,
                symbols,
            )
        return_method = _normalize_return_method(
            params.get("return_method") or params.get("returns") or params.get("return_type")
        )
        frequency = _normalize_frequency(raw_frequency)
        missing_policy = _normalize_missing_policy(params.get("missing_data_policy") or params.get("missing_policy"))
        min_overlap = _bounded_int(params.get("min_overlap", 30), 10, 500, 30)
        live = _truthy(params.get("live_correlation") or params.get("live"))
        sources = ["computed_return_model"]
        coverage_status: dict[str, dict[str, Any]] = {}
        dropped_live: list[str] = []

        if live:
            price_series, coverage_status, _used_live = await self._live_price_series(symbols, days)
            missing_symbols = [s for s in symbols if s not in {series["asset"]["symbol"] for series in price_series}]
            if missing_symbols:
                # HNT-04 (2026-09-23 bug hunt): a failed live fetch used to be
                # patched with a deterministic synthetic series that then fed
                # the same heatmap/top-pairs tables as the real cells, with no
                # per-cell marker. Drop the symbol from the live matrix
                # universe instead and report it honestly in coverage_status.
                dropped_live = list(missing_symbols)
                for symbol in missing_symbols:
                    previous = coverage_status.get(symbol, {})
                    coverage_status[symbol] = {
                        "status": "dropped_live_unavailable",
                        "source": previous.get("source") or "live_provider",
                        "provider_symbol": _provider_symbol(symbol),
                        "message": (
                            "Live price series unavailable ("
                            + (previous.get("message") or "no usable live close rows")
                            + "); symbol dropped from the live correlation matrix."
                        ),
                    }
            if not price_series:
                return _live_unavailable_result(
                    symbols, days, coverage_status, instrument, frequency,
                    return_method, missing_policy,
                )
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
            if symbol not in dropped_live
            and (symbol not in frame or int(frame[symbol].dropna().shape[0]) < 2)
        ]
        if thin_symbols:
            if live:
                # HNT-04: same honesty rule for symbols whose live series
                # produced fewer than two usable returns — drop, don't
                # synthesize.
                price_series = [
                    series
                    for series in price_series
                    if series.get("asset", {}).get("symbol") not in set(thin_symbols)
                ]
                dropped_live.extend(thin_symbols)
                for symbol in thin_symbols:
                    previous = coverage_status.get(symbol, {})
                    coverage_status[symbol] = {
                        "status": "dropped_live_unavailable",
                        "source": previous.get("source") or "live_provider",
                        "provider_symbol": previous.get("provider_symbol") or _provider_symbol(symbol),
                        "message": (
                            "Live series produced fewer than two usable returns ("
                            + (previous.get("message") or "")
                            + "); symbol dropped from the live correlation matrix."
                        ),
                    }
                frame = _build_return_frame(price_series, frequency, return_method, missing_policy)
                if frame.empty:
                    return _live_unavailable_result(
                        symbols, days, coverage_status, instrument, frequency,
                        return_method, missing_policy,
                    )
            else:
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
            if live:
                return _live_unavailable_result(
                    symbols, days, coverage_status, instrument, frequency,
                    return_method, missing_policy,
                )
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

        # B6: scrub NaN-dominant columns AFTER all fallbacks have populated
        # the frame so the matrix downstream stays finite. Surface the drop
        # in coverage_status + payload so the UI is honest about it.
        # CORR#1: the threshold applies to each symbol's own missing trading
        # sessions. Weekend and holiday rows of a weekday-only series are a
        # calendar artifact, not a data gap, so they never count.
        gap_ratios = _calendar_gap_ratios(_price_frame(price_series, frequency), frequency)
        frame, dropped_symbols = _drop_nan_heavy_columns(frame, gap_ratios=gap_ratios)
        for symbol in dropped_symbols:
            previous = coverage_status.get(symbol, {})
            coverage_status[symbol] = {
                "status": "dropped_null_heavy",
                "source": previous.get("source") or "live_provider",
                "provider_symbol": previous.get("provider_symbol") or _provider_symbol(symbol),
                "message": (
                    f"More than {int(NAN_DROP_THRESHOLD * 100)}% of its expected trading sessions have "
                    "no data; removed from correlation matrix. Holidays count as missing sessions; "
                    "weekend gaps of weekday-only symbols are not counted."
                ),
            }
        active_symbols = [s for s in symbols if s not in dropped_symbols]
        # CORR#6: provenance follows the providers that served each symbol's closes.
        sources = _provenance_sources(coverage_status, live)

        data = _correlation_payload(
            symbols=active_symbols if active_symbols else symbols,
            days=days,
            price_series=price_series,
            frame=frame,
            return_method=return_method,
            frequency=frequency,
            missing_policy=missing_policy,
            live=live,
            sources=sources,
            coverage_status=coverage_status,
            min_overlap=min_overlap,
            method=method,
        )
        # B6: surface the dropped list both on the payload and as a warning
        # so the UI can render a chip.
        data["dropped_symbols"] = list(dropped_symbols)
        if dropped_live:
            data["dropped_live_symbols"] = list(dropped_live)
        warnings = [
            item["message"]
            for item in data.get("impactor", {}).get("bug_analysis", [])
            if item.get("severity") in {"warning", "critical"}
        ][:8]
        rejected_pairs = data.get("rejected_pairs") or []
        if rejected_pairs:
            warnings.insert(
                0,
                f"Rejected {len(rejected_pairs)} pair(s) with fewer than {min_overlap} overlapping "
                "observations; their correlations are null.",
            )
        if method != "pearson":
            warnings.insert(
                0,
                f"Headline correlations (impactor matrix, ranked pairs, selected pair) use the {method} "
                "kernel; the Pearson, Spearman and Downside views are unchanged.",
            )
        if not data.get("downside_observations"):
            warnings.append(
                "Downside matrix unavailable: no negative equal-weight universe days, so downside cells are null."
            )
        if dropped_live:
            warnings.insert(
                0,
                f"Dropped {len(dropped_live)} live-unavailable symbol(s): "
                f"{', '.join(dropped_live)}",
            )
        if dropped_symbols:
            warnings.insert(
                0,
                f"Dropped {len(dropped_symbols)} symbol(s) missing more than "
                f"{int(NAN_DROP_THRESHOLD * 100)}% of expected trading sessions: "
                f"{', '.join(dropped_symbols)}",
            )
        if provider_mode_requested:
            # CORR#7 review: CORR has no live-versus-delayed selector, so a requested
            # data mode is recorded and reported as not honoured, never silently ignored.
            warnings.append(
                f"provider_mode {provider_mode_requested} was requested; CORR serves from its provider "
                "chain and does not select by data mode, so the request is not honoured."
            )
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
                "correlation_method": method,
                "provider_mode_requested": provider_mode_requested,
                "provider_mode_honoured": False if provider_mode_requested else None,
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
                        except asyncio.CancelledError:
                            raise
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
                except asyncio.CancelledError:
                    # B6: never swallow cancellation; let the caller unwind.
                    raise
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


def _provenance_sources(coverage_status: dict[str, dict[str, Any]], live: bool) -> list[str]:
    """CORR#6: the real providers behind the matrix, read from per-symbol coverage.

    Live mode lists the adapter that served each live symbol (for example yfinance
    or ccxt_failover). Model mode lists only the computed reference model.
    """
    if not live:
        return ["computed_return_model"]
    names: list[str] = []
    for status in coverage_status.values():
        if status.get("status") != "live":
            continue
        source = str(status.get("source") or "")
        if source and source not in names:
            names.append(source)
    return names


def _live_unavailable_result(
    symbols: list[str],
    days: int,
    coverage_status: dict[str, dict[str, Any]],
    instrument: Instrument | None,
    frequency: str,
    return_method: str,
    missing_policy: str,
) -> FunctionResult:
    """HNT-04: total live outage → honest provider_unavailable envelope.

    Live mode never fabricates a matrix: when no requested symbol produced
    a usable close series, the payload is empty with an explicit reason and
    next_actions instead of a synthetic correlation table.
    """
    return FunctionResult(
        code="CORR",
        instrument=instrument,
        data={
            "status": "provider_unavailable",
            "reason": "Live price providers returned no usable close rows for any requested symbol.",
            "symbols": list(symbols),
            "pearson": {},
            "spearman": {},
            "downside": {},
            "annualized_vol": {},
            "surface": [],
            "rows": [],
            "samples": 0,
            "coverage_status": coverage_status,
            "dropped_symbols": list(symbols),
            "dropped_live_symbols": list(symbols),
            "next_actions": [
                "Retry once the live price provider recovers.",
                "Check that the requested symbols resolve on the configured providers.",
            ],
            "methodology": (
                "CORR live mode requires real close series; when the live providers "
                "serve none of the requested symbols, no correlation matrix is computed "
                "and the payload stays empty rather than synthetic."
            ),
            "field_dictionary": {
                "coverage_status": "Per-symbol live fetch outcome (live / dropped_live_unavailable).",
            },
        },
        sources=[],
        metadata={
            "days": days,
            "symbols": list(symbols),
            # CORR#outage: no series was served, so the envelope is not a live result.
            "live": False,
            "return_method": return_method,
            "frequency": frequency,
            "missing_data_policy": missing_policy,
            "impactor_integrated": True,
        },
        warnings=["CORR live: no usable price series for any requested symbol"],
    )


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
    min_overlap: int = 30,
    method: str = "pearson",
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
    # XCON-7: same realized factor as _return_series_summary (observation
    # density), so one symbol never shows two annualized vols in one response.
    # HEAD's per-symbol helper already applies it and returns None when undefined.
    vol = _annualized_vol_by_symbol(frame, ordered_symbols, frequency)
    pearson = _df_to_nested_dict(pearson_df)
    spearman = _df_to_nested_dict(spearman_df)
    downside = _df_to_nested_dict(downside_df)
    # CORR#7: min_overlap is enforced per pair. A pair with too few overlapping
    # observations gets null cells in every matrix and a rejected_pairs entry.
    rejected = _thin_pairs(frame, ordered_symbols, min_overlap)
    for matrix in (pearson, spearman, downside):
        _null_pairs(matrix, rejected)
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
        rejected_pairs=rejected,
        min_overlap=min_overlap,
        method=method,
    )
    return {
        "symbols": ordered_symbols,
        "correlation_method": method,
        "pearson": pearson,
        "spearman": spearman,
        "downside": downside,
        "annualized_vol": vol,
        "samples": int(impactor["observation_range"]["max"]),
        # HNT-04: per-symbol fetch outcome, including dropped_live_unavailable
        # rows for symbols removed from the live matrix universe.
        "coverage_status": coverage_status,
        "surface": _matrix_surface(pearson, spearman, downside),
        "rejected_pairs": [
            {
                "left": left,
                "right": right,
                "observations": observations,
                "reason": f"fewer than {min_overlap} overlapping observations",
            }
            for left, right, observations in rejected
        ],
        "min_overlap": min_overlap,
        "downside_observations": int(down.shape[0]),
        "rows": [
            {
                "symbol": symbol,
                "market": _infer_market(symbol),
                "annualized_vol": vol.get(symbol),
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
            "correlation_method": method,
            "return_method": return_method,
            "frequency": frequency,
            "missing_data_policy": missing_policy,
            "markets": sorted({row["market"] for row in impactor["market_coverage"]}),
        },
        "methodology": (
            "Resolve the selected universe, fetch or build close price series, resample to the selected "
            "frequency, compute log or simple returns, apply the selected missing-data policy, then estimate "
            "Pearson, Spearman, downside correlation, covariance, and ranked positive/negative pairs. "
            f"The impactor matrix and ranked pairs use the {method} correlation kernel. Every symbol is "
            "measured on one shared return calendar, so all series span the same dates."
        ),
        "field_dictionary": {
            "pearson": "Linear return correlation from -1 to +1.",
            "spearman": "Rank correlation, less sensitive to extreme return magnitudes.",
            "downside": "Correlation estimated only on negative equal-weight universe days.",
            "annualized_vol": "Return standard deviation multiplied by the realized annualization factor (sqrt of observations per year), the same factor used in return_series_summary.",
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
    rejected_pairs: list[tuple[str, str, int]] | None = None,
    min_overlap: int = 30,
    method: str = "pearson",
) -> dict[str, Any]:
    price_by_symbol = {series["asset"]["symbol"]: series for series in price_series}
    matrix = _impactor_matrix(frame, symbols, method)
    rejected_keys = {frozenset((left, right)) for left, right, _ in (rejected_pairs or [])}
    for cell in matrix:
        if cell["left"] != cell["right"] and frozenset((cell["left"], cell["right"])) in rejected_keys:
            cell["correlation"] = None
            cell["covariance"] = None
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
        method,
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
            "min_overlap": min_overlap,
            "correlation_method": method,
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
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        values = pd.to_numeric(frame.get(symbol), errors="coerce").dropna() if symbol in frame else pd.Series(dtype=float)
        # Audit Q3 #22 — annualization factor must reflect the *realized*
        # observation count, not the nominal calendar count. A weekly
        # series with holiday gaps has <52 obs/yr; using sqrt(52) inflates
        # ann vol. We compute factor as sqrt(obs/yr) from the actual span.
        factor = _realized_annualization_factor(values, frequency)
        rows.append(
            {
                "symbol": symbol,
                "market": _infer_market(symbol),
                "observations": int(values.shape[0]),
                "mean_return": _round_or_none(float(values.mean())) if not values.empty else None,
                "volatility": _round_or_none(float(values.std())) if values.shape[0] > 1 else None,
                "annualized_volatility": _round_or_none(float(values.std() * factor)) if values.shape[0] > 1 and factor is not None else None,
                "annualization_factor": _round_or_none(factor) if factor is not None else None,
                "min_return": _round_or_none(float(values.min())) if not values.empty else None,
                "max_return": _round_or_none(float(values.max())) if not values.empty else None,
                "first_return_date": values.index.min().date().isoformat() if not values.empty else None,
                "last_return_date": values.index.max().date().isoformat() if not values.empty else None,
            }
        )
    return rows


def _annualized_vol_by_symbol(
    frame: pd.DataFrame,
    symbols: list[str],
    frequency: str,
) -> dict[str, float | None]:
    """CORR#2: each symbol is annualized with its own realized observation density.

    The same factor is used by ``return_series_summary``, so the matrix diagonal,
    the rows table and the return summary agree. An undefined volatility (fewer
    than two observations) is None, never zero (CORR#8).
    """
    return {symbol: _symbol_annualized_vol(frame, symbol, frequency) for symbol in symbols}


def _realized_annualization_factor(values: pd.Series, frequency: str) -> float | None:
    """Annualization factor based on the *realized* observation density.

    Falls back to the nominal sqrt(252/52/12) when the series is too thin
    or the index is not datetime-like.
    """
    if values is None or values.empty or values.shape[0] < 2:
        return _annualization_factor(frequency)
    try:
        idx = pd.to_datetime(values.index)
        span_days = max((idx.max() - idx.min()).days, 1)
    except Exception:
        return _annualization_factor(frequency)
    span_years = span_days / 365.25
    if span_years <= 0:
        return _annualization_factor(frequency)
    obs_per_year = values.shape[0] / span_years
    if obs_per_year <= 0:
        return _annualization_factor(frequency)
    return math.sqrt(obs_per_year)


def _impactor_matrix(frame: pd.DataFrame, symbols: list[str], method: str = "pearson") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for y in symbols:
        for x in symbols:
            detail = _pair_stats(frame, y, x, method)
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


def _pair_stats(frame: pd.DataFrame, left: str, right: str, method: str = "pearson") -> dict[str, Any]:
    """Pair statistics; ``correlation`` uses the requested kernel (CORR#7).

    Covariance and volatilities stay sample moments of the overlap. Spearman and
    Kendall come from pandas on the same overlap, so the kernel is never silently
    replaced by Pearson.
    """
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
    if method == "pearson":
        corr = None if denominator == 0 else covariance / denominator
    elif method == "kendall":
        corr = _kendall_tau_b(left_values.to_numpy(dtype=float), right_values.to_numpy(dtype=float))
    else:
        rank_value = float(left_values.corr(right_values, method=method))
        corr = rank_value if math.isfinite(rank_value) else None
    return {
        "correlation": corr,
        "covariance": covariance,
        "observations": int(overlap.shape[0]),
        "left_vol": left_vol,
        "right_vol": right_vol,
        "overlap": overlap,
    }


def _kendall_tau_b(x: np.ndarray, y: np.ndarray) -> float | None:
    """Kendall tau-b with tie correction, computed with numpy only.

    pandas' kendall path needs scipy, which the sidecar does not ship, so the
    concordance sum is built from sign matrices instead. Returns None when either
    series has no variation (tau-b is undefined there).
    """
    if x.shape[0] < 2 or y.shape[0] < 2:
        return None
    dx = np.sign(x[:, None] - x[None, :]).astype(np.int8)
    dy = np.sign(y[:, None] - y[None, :]).astype(np.int8)
    # Each unordered pair appears twice in the full sign matrices; halve the sums.
    concordance = float(np.sum(dx * dy, dtype=np.int64)) / 2.0
    untied_x = float(np.sum(dx * dx, dtype=np.int64)) / 2.0
    untied_y = float(np.sum(dy * dy, dtype=np.int64)) / 2.0
    denominator = math.sqrt(untied_x * untied_y)
    if denominator == 0.0:
        return None
    tau = concordance / denominator
    return tau if math.isfinite(tau) else None


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
    method: str = "pearson",
) -> dict[str, Any] | None:
    if pair:
        left = pair["left"]
        right = pair["right"]
    elif len(symbols) >= 2:
        left, right = symbols[0], symbols[1]
    else:
        return None
    detail = _pair_stats(frame, left, right, method)
    # CORR#2 residual: each side is annualized on its own realized calendar, the same
    # factor and full-series volatility that annualized_vol uses for that symbol.
    left_annualized = _symbol_annualized_vol(frame, left, frequency)
    right_annualized = _symbol_annualized_vol(frame, right, frequency)
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
        "left_annualized_volatility": left_annualized,
        "right_annualized_volatility": right_annualized,
        "overlap_sample": preview,
    }


def _symbol_annualized_vol(frame: pd.DataFrame, symbol: str, frequency: str) -> float | None:
    """Annualized volatility of one symbol's full return series (same as annualized_vol)."""
    values = pd.to_numeric(frame[symbol], errors="coerce").dropna() if symbol in frame else pd.Series(dtype=float)
    factor = _realized_annualization_factor(values, frequency)
    if values.shape[0] > 1 and factor is not None:
        return _round_or_none(float(values.std() * factor))
    return None


def _heatmap_rows(symbols: list[str], pearson: dict[str, dict[str, float | None]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for y in symbols:
        row: dict[str, Any] = {"symbol": y, "market": _infer_market(y)}
        for x in symbols:
            row[x] = (pearson.get(y) or {}).get(x)
        rows.append(row)
    return rows


def _drop_nan_heavy_columns(
    frame: pd.DataFrame,
    threshold: float = NAN_DROP_THRESHOLD,
    gap_ratios: dict[str, float] | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Drop columns whose missing-data ratio exceeds ``threshold``.

    ``gap_ratios`` (from ``_calendar_gap_ratios``) is the share of each symbol's
    own expected trading sessions with no data. When it is given, that share is
    what is tested, so calendar gaps in the joined frame never count. Without
    it the raw NaN ratio of the frame is used.

    Returns the cleaned frame and the list of dropped symbols so callers can
    surface them in the response payload instead of silently propagating NaN
    correlations downstream.
    """
    if frame.empty:
        return frame, []
    if gap_ratios is None:
        nan_ratio = frame.isna().mean(axis=0)
    else:
        nan_ratio = pd.Series(
            {col: float(gap_ratios.get(str(col), 1.0)) for col in frame.columns},
            dtype=float,
        )
    keep = nan_ratio[nan_ratio <= threshold].index.tolist()
    drop = [str(col) for col in frame.columns if col not in keep]
    if drop:
        LOG.warning(
            "CORR dropped %d null-heavy column(s) above %.0f%% threshold: %s",
            len(drop),
            threshold * 100,
            drop,
        )
    return frame.loc[:, keep], drop


def _price_frame(
    price_series: list[dict[str, Any]],
    frequency: str,
) -> pd.DataFrame:
    """Union price frame on the selected frequency; NaN where a symbol has no close."""
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
    return prices


def _series_returns(values: pd.Series, return_method: str) -> pd.Series:
    # B6: guard the log transform against zero prices by clipping non-positive
    # values to NaN BEFORE the log so we don't emit -inf into the frame.
    safe = values.where(values > 0)
    if return_method == "log":
        returns = np.log(safe / safe.shift(1))
    else:
        # Explicit ratio rather than pct_change(): pct_change pads NaN gaps by default.
        returns = safe / safe.shift(1) - 1.0
    return returns.replace([np.inf, -np.inf], np.nan)


def _returns_from_prices(
    prices: pd.DataFrame,
    return_method: str,
    missing_policy: str,
    frequency: str = "daily",
) -> pd.DataFrame:
    """Returns for every symbol on one shared calendar.

    CORR-R2: the old per-symbol returns spanned each symbol's own consecutive
    closes, so a Monday equity return covered three days while a 24/7 crypto
    return covered one. Correlations then compared unequal horizons. Returns are
    now taken between consecutive dates on which every anchor symbol has a close.
    Anchor symbols are those within the null-heavy threshold; a heavier symbol
    stays in the frame (so it is still reported as dropped) but does not shrink
    the shared calendar. Weekend dates drop out automatically when a weekday-only
    symbol is in the universe, and holidays drop out for everyone.

    ``forward_fill`` keeps the explicit union-calendar fill the user asked for.
    """
    if prices.empty:
        return pd.DataFrame()
    if missing_policy == "forward_fill":
        filled = prices.ffill()
        returns = pd.DataFrame(
            {col: _series_returns(filled[col], return_method) for col in filled.columns},
            index=filled.index,
        )
    else:
        gap_ratios = _calendar_gap_ratios(prices, frequency)
        anchors = [col for col in prices.columns if gap_ratios.get(str(col), 1.0) <= NAN_DROP_THRESHOLD]
        if not anchors:
            anchors = list(prices.columns)
        shared_index = prices[anchors].dropna(how="any").index
        columns = {
            col: _series_returns(prices.loc[shared_index, col], return_method)
            for col in prices.columns
            if prices[col].notna().any()
        }
        returns = pd.DataFrame(columns, index=shared_index)
    returns = returns.replace([np.inf, -np.inf], np.nan)
    if missing_policy == "intersection":
        returns = returns.dropna(how="any")
    else:
        returns = returns.dropna(how="all")
    return returns


def _calendar_gap_ratios(prices: pd.DataFrame, frequency: str) -> dict[str, float]:
    """Share of each symbol's expected trading sessions with no observed close.

    A symbol that trades on weekends (24/7 crypto) is expected every calendar
    day in its span. Any other daily symbol is expected on weekdays only, so a
    weekend is never a gap for it. Holidays still count, and that is intended:
    they are sessions the symbol did not print. Weekly and monthly frames use
    every period in the span.
    """
    ratios: dict[str, float] = {}
    if prices.empty:
        return ratios
    for col in prices.columns:
        observed = prices[col].dropna().index
        if len(observed) == 0:
            ratios[str(col)] = 1.0
            continue
        span = prices.index[(prices.index >= observed.min()) & (prices.index <= observed.max())]
        if frequency == "daily":
            weekend_share = float(np.mean(np.asarray(observed.dayofweek) >= 5))
            if weekend_share <= 0.10:
                span = span[span.dayofweek < 5]
        if len(span) == 0:
            ratios[str(col)] = 1.0
            continue
        missing = len(span.difference(observed))
        ratios[str(col)] = missing / len(span)
    return ratios


def _build_return_frame(
    price_series: list[dict[str, Any]],
    frequency: str,
    return_method: str,
    missing_policy: str,
) -> pd.DataFrame:
    prices = _price_frame(price_series, frequency)
    return _returns_from_prices(prices, return_method, missing_policy, frequency)


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


def _as_of_error(value: Any) -> str | None:
    """CORR#7: an as_of anchor is honoured only when it is today.

    CORR always measures the window ending at the latest close. A past anchor
    would otherwise be silently replaced by that window, and a future anchor
    cannot be measured, so both are refused.
    """
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        return "as_of must be a single date (YYYY-MM-DD); CORR cannot anchor a list or a range."
    text = value.strip()
    try:
        anchor = date.fromisoformat(text[:10])
    except ValueError:
        return f"Unparsable as_of {value!r}; use a date such as 2026-11-07."
    today = datetime.now(timezone.utc).date()
    if anchor > today:
        return (
            f"as_of {anchor.isoformat()} is in the future; CORR cannot measure a window "
            "that has not closed yet."
        )
    if anchor < today:
        return (
            f"as_of {anchor.isoformat()} is before today; CORR measures the window ending at the "
            "latest close and does not anchor historical windows yet."
        )
    return None


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
    if text in {"weekly", "week", "w", "1wk"}:
        return "weekly"
    if text in {"monthly", "month", "m", "1mo"}:
        return "monthly"
    return "daily"


_WINDOW_DAYS_RE = re.compile(r"^(\d+)\s*(d|y)$")


def _resolve_days(params: dict[str, Any]) -> int | None:
    """Lookback in days: the pane's ``days`` wins, else the seed ``window``.

    Returns None when ``window`` is present but unparsable, so the caller can
    return an explicit input error instead of silently using the default.
    """
    if params.get("days") not in (None, ""):
        return _bounded_int(params.get("days"), 30, 2520, 365)
    window = params.get("window")
    if window in (None, ""):
        return 365
    match = _WINDOW_DAYS_RE.match(str(window).strip().lower())
    if not match:
        return None
    count = int(match.group(1)) * (365 if match.group(2) == "y" else 1)
    return max(30, min(2520, count))


def _input_error_result(message: str, instrument: Instrument | None, symbols: list[str]) -> FunctionResult:
    return FunctionResult(
        code="CORR",
        instrument=instrument,
        data={
            "status": "input_error",
            "reason": message,
            "symbols": list(symbols),
            "next_actions": ["Correct the input and run CORR again."],
        },
        sources=[],
        metadata={"live": False, "impactor_integrated": True},
        warnings=[message],
    )


def _thin_pairs(
    frame: pd.DataFrame,
    symbols: list[str],
    min_overlap: int,
) -> list[tuple[str, str, int]]:
    """CORR#7: unordered pairs whose overlapping observation count is below min_overlap."""
    cols = [symbol for symbol in symbols if symbol in frame.columns]
    valid = frame[cols].notna() if cols else pd.DataFrame()
    out: list[tuple[str, str, int]] = []
    for index, left in enumerate(cols):
        for right in cols[index + 1 :]:
            observations = int((valid[left] & valid[right]).sum())
            if observations < min_overlap:
                out.append((left, right, observations))
    return out


def _null_pairs(matrix: dict[str, dict[str, float | None]], pairs: list[tuple[str, str, int]]) -> None:
    for left, right, _ in pairs:
        if left in matrix and right in matrix[left]:
            matrix[left][right] = None
        if right in matrix and left in matrix[right]:
            matrix[right][left] = None


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
                    # CORR#5: a missing Spearman/downside cell is null, never the Pearson value.
                    "spearman": (spearman.get(left) or {}).get(right),
                    "downside": (downside.get(left) or {}).get(right),
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
