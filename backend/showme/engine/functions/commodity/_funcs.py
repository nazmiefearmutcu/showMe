"""BOIL, BGAS, NGAS, CPF, GLCO, WETR — emtia fonksiyonları (kompakt)."""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


COMMODITY_CONTRACTS: dict[str, dict[str, Any]] = {
    "CL=F": {
        "name": "WTI Crude Oil",
        "sector": "energy",
        "contract": "NYMEX Light Sweet Crude Oil front month",
        "unit": "USD/bbl",
        "exchange": "NYMEX",
        "model_last": 78.0,
        "model_change_pct": 0.7,
    },
    "BZ=F": {
        "name": "Brent Crude Oil",
        "sector": "energy",
        "contract": "ICE Brent Crude front month",
        "unit": "USD/bbl",
        "exchange": "ICE",
        "model_last": 82.0,
        "model_change_pct": 0.5,
    },
    "NG=F": {
        "name": "Henry Hub Natural Gas",
        "sector": "energy",
        "contract": "NYMEX Henry Hub Natural Gas front month",
        "unit": "USD/MMBtu",
        "exchange": "NYMEX",
        "model_last": 3.25,
        "model_change_pct": -0.8,
    },
    "RB=F": {
        "name": "RBOB Gasoline",
        "sector": "energy",
        "contract": "NYMEX RBOB Gasoline front month",
        "unit": "USD/gal",
        "exchange": "NYMEX",
        "model_last": 2.35,
        "model_change_pct": 0.4,
    },
    "HO=F": {
        "name": "Heating Oil",
        "sector": "energy",
        "contract": "NYMEX Heating Oil front month",
        "unit": "USD/gal",
        "exchange": "NYMEX",
        "model_last": 2.48,
        "model_change_pct": -0.2,
    },
    "GC=F": {
        "name": "Gold",
        "sector": "metals",
        "contract": "COMEX Gold front month",
        "unit": "USD/oz",
        "exchange": "COMEX",
        "model_last": 2450.0,
        "model_change_pct": 0.3,
    },
    "SI=F": {
        "name": "Silver",
        "sector": "metals",
        "contract": "COMEX Silver front month",
        "unit": "USD/oz",
        "exchange": "COMEX",
        "model_last": 29.4,
        "model_change_pct": 0.8,
    },
    "HG=F": {
        "name": "Copper",
        "sector": "metals",
        "contract": "COMEX Copper front month",
        "unit": "USD/lb",
        "exchange": "COMEX",
        "model_last": 4.45,
        "model_change_pct": -0.1,
    },
    "ZC=F": {
        "name": "Corn",
        "sector": "agriculture",
        "contract": "CBOT Corn front month",
        "unit": "US cents/bu",
        "exchange": "CBOT",
        "model_last": 455.0,
        "model_change_pct": 0.2,
    },
    "ZW=F": {
        "name": "Wheat",
        "sector": "agriculture",
        "contract": "CBOT Wheat front month",
        "unit": "US cents/bu",
        "exchange": "CBOT",
        "model_last": 610.0,
        "model_change_pct": -0.4,
    },
    "ZS=F": {
        "name": "Soybeans",
        "sector": "agriculture",
        "contract": "CBOT Soybean front month",
        "unit": "US cents/bu",
        "exchange": "CBOT",
        "model_last": 1180.0,
        "model_change_pct": 0.1,
    },
    "KC=F": {
        "name": "Coffee",
        "sector": "softs",
        "contract": "ICE Coffee C front month",
        "unit": "US cents/lb",
        "exchange": "ICE",
        "model_last": 225.0,
        "model_change_pct": 1.2,
    },
    "SB=F": {
        "name": "Sugar No. 11",
        "sector": "softs",
        "contract": "ICE Sugar No. 11 front month",
        "unit": "US cents/lb",
        "exchange": "ICE",
        "model_last": 20.6,
        "model_change_pct": -0.5,
    },
    "CT=F": {
        "name": "Cotton",
        "sector": "softs",
        "contract": "ICE Cotton No. 2 front month",
        "unit": "US cents/lb",
        "exchange": "ICE",
        "model_last": 76.0,
        "model_change_pct": 0.6,
    },
}


LOCATION_PRESETS: dict[str, dict[str, Any]] = {
    "US_NORTHEAST": {
        "label": "US Northeast",
        "lat": 41.01,
        "lon": -74.0,
        "commodity_context": "natural gas and power demand",
    },
    "US_GULF": {
        "label": "US Gulf Coast",
        "lat": 29.76,
        "lon": -95.37,
        "commodity_context": "oil refining, LNG, and hurricane risk",
    },
    "US_MIDWEST": {
        "label": "US Midwest",
        "lat": 41.88,
        "lon": -87.63,
        "commodity_context": "corn, soybeans, and crop weather",
    },
    "EUROPE_GAS": {
        "label": "Northwest Europe",
        "lat": 52.52,
        "lon": 13.4,
        "commodity_context": "European gas and heating demand",
    },
}


FORECAST_REFERENCE_ROWS: list[dict[str, Any]] = [
    {"commodity": "WTI crude oil", "year": 2025, "forecast_value": 76.0, "unit": "USD/bbl"},
    {"commodity": "WTI crude oil", "year": 2026, "forecast_value": 82.0, "unit": "USD/bbl"},
    {"commodity": "WTI crude oil", "year": 2027, "forecast_value": 79.0, "unit": "USD/bbl"},
    {"commodity": "WTI crude oil", "year": 2028, "forecast_value": 77.0, "unit": "USD/bbl"},
    {"commodity": "Natural gas", "year": 2025, "forecast_value": 3.25, "unit": "USD/MMBtu"},
    {"commodity": "Natural gas", "year": 2026, "forecast_value": 3.60, "unit": "USD/MMBtu"},
    {"commodity": "Natural gas", "year": 2027, "forecast_value": 3.45, "unit": "USD/MMBtu"},
    {"commodity": "Natural gas", "year": 2028, "forecast_value": 3.35, "unit": "USD/MMBtu"},
    {"commodity": "Gold", "year": 2025, "forecast_value": 2350.0, "unit": "USD/oz"},
    {"commodity": "Gold", "year": 2026, "forecast_value": 2450.0, "unit": "USD/oz"},
    {"commodity": "Gold", "year": 2027, "forecast_value": 2380.0, "unit": "USD/oz"},
    {"commodity": "Gold", "year": 2028, "forecast_value": 2300.0, "unit": "USD/oz"},
    {"commodity": "Copper", "year": 2025, "forecast_value": 9300.0, "unit": "USD/mt"},
    {"commodity": "Copper", "year": 2026, "forecast_value": 9700.0, "unit": "USD/mt"},
    {"commodity": "Copper", "year": 2027, "forecast_value": 9900.0, "unit": "USD/mt"},
    {"commodity": "Copper", "year": 2028, "forecast_value": 10100.0, "unit": "USD/mt"},
]


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _int_param(params: dict[str, Any], key: str, default: int, low: int, high: int) -> int:
    try:
        value = int(float(params.get(key, default)))
    except Exception:
        value = default
    return max(low, min(value, high))


def _period_for_days(days: int) -> str:
    if days <= 31:
        return "1mo"
    if days <= 93:
        return "3mo"
    if days <= 186:
        return "6mo"
    if days <= 370:
        return "1y"
    return "3y"


def _date_label(value: Any) -> str:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        return value.date().isoformat()
    return str(value)[:10]


def _history_rows(df: Any, symbol: str, limit: int = 260) -> list[dict[str, Any]]:
    if df is None or getattr(df, "empty", True):
        return []
    rows: list[dict[str, Any]] = []
    for idx, row in df.tail(limit).iterrows():
        close = _finite(row.get("close"))
        if close is None:
            continue
        rows.append({
            "date": _date_label(idx),
            "symbol": symbol,
            "open": _finite(row.get("open")),
            "high": _finite(row.get("high")),
            "low": _finite(row.get("low")),
            "close": close,
            "volume": _finite(row.get("volume")),
        })
    return rows


def _model_row(symbol: str) -> dict[str, Any]:
    meta = COMMODITY_CONTRACTS[symbol]
    last = float(meta["model_last"])
    change_pct = float(meta["model_change_pct"])
    prev = last / (1 + change_pct / 100) if change_pct != -100 else None
    return {
        "symbol": symbol,
        "name": meta["name"],
        "sector": meta["sector"],
        "contract": meta["contract"],
        "unit": meta["unit"],
        "exchange": meta["exchange"],
        "last": round(last, 6),
        "prev": round(prev, 6) if prev is not None else None,
        "change": round(last - prev, 6) if prev is not None else None,
        "change_pct": round(change_pct, 4),
        "high": None,
        "low": None,
        "volume": None,
        "source": "commodity_reference_model",
        "source_mode": "model",
        "as_of": datetime.now(timezone.utc).date().isoformat(),
    }


async def _contract_snapshot(
    yfinance: Any,
    symbol: str,
    *,
    days: int,
    timeout: float,
    include_history: bool,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[str]]:
    meta = COMMODITY_CONTRACTS[symbol]
    errors: list[str] = []
    quote: Any = None
    history: list[dict[str, Any]] = []
    if yfinance:
        inst = Instrument(symbol=symbol, asset_class=AssetClass.COMMODITY)
        try:
            quote = await asyncio.wait_for(
                yfinance.fetch(DataRequest(
                    kind=DataKind.QUOTE,
                    instrument=inst,
                    extra={"timeout": timeout},
                )),
                timeout=timeout + 0.5,
            )
        except Exception as exc:
            errors.append(f"{symbol} quote: {exc}")
        if include_history:
            try:
                df = await asyncio.wait_for(
                    yfinance.fetch(DataRequest(
                        kind=DataKind.OHLCV,
                        instrument=inst,
                        limit=min(max(days, 2), 500),
                        extra={"period": _period_for_days(days), "timeout": timeout},
                    )),
                    timeout=max(timeout + 1.0, 3.0),
                )
                history = _history_rows(df, symbol, limit=min(max(days, 2), 500))
            except Exception as exc:
                errors.append(f"{symbol} history: {exc}")

    last = _finite(getattr(quote, "last", None))
    prev = _finite(getattr(quote, "close_prev", None))
    high = _finite(getattr(quote, "high_24h", None))
    low = _finite(getattr(quote, "low_24h", None))
    open_ = _finite(getattr(quote, "open_24h", None))
    volume = _finite(getattr(quote, "volume_24h", None))
    source = getattr(quote, "source", None) or "yfinance"
    as_of = getattr(getattr(quote, "timestamp", None), "isoformat", lambda: None)()

    if last is None and history:
        last = _finite(history[-1].get("close"))
        prev = _finite(history[-2].get("close")) if len(history) >= 2 else None
        high = _finite(history[-1].get("high"))
        low = _finite(history[-1].get("low"))
        open_ = _finite(history[-1].get("open"))
        volume = _finite(history[-1].get("volume"))
        source = "yfinance_chart"
        as_of = history[-1].get("date")

    if last is None:
        return None, history, errors

    change = last - prev if prev not in (None, 0) else None
    change_pct = (last / prev - 1) * 100 if prev not in (None, 0) else None
    return {
        "symbol": symbol,
        "name": meta["name"],
        "sector": meta["sector"],
        "contract": meta["contract"],
        "unit": meta["unit"],
        "exchange": meta["exchange"],
        "last": last,
        "prev": prev,
        "change": change,
        "change_pct": change_pct,
        "open": open_,
        "high": high,
        "low": low,
        "volume": volume,
        "source": source,
        "source_mode": "live_yfinance",
        "as_of": as_of or datetime.now(timezone.utc).isoformat(),
    }, history, errors


def _filter_sector(rows: list[dict[str, Any]], sector: Any) -> list[dict[str, Any]]:
    key = str(sector or "all").strip().lower()
    if key in {"", "all"}:
        return rows
    if key == "ags":
        key = "ag"
    return [row for row in rows if key in str(row.get("sector", "")).lower()]


def _provider_unavailable_payload(reason: str, next_actions: list[str]) -> dict[str, Any]:
    return {
        "status": "provider_unavailable",
        "reason": reason,
        "rows": [],
        "next_actions": next_actions,
    }


@FunctionRegistry.register
class BOILFunction(BaseFunction):
    """BOIL — WTI / Brent / Dubai oil spot + spread."""
    code = "BOIL"
    name = "Oil Spot"
    asset_classes = (AssetClass.COMMODITY,)
    category = "commodity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        days = _int_param(params, "days", 365, 20, 1095)
        timeout = max(1.0, min(float(params.get("quote_timeout", params.get("yfinance_timeout", 4))), 8.0))
        live = _truthy(params.get("live", True))
        selector = str(params.get("benchmark") or params.get("contract") or "").strip().upper()
        requested = instrument.symbol.upper() if instrument and instrument.symbol in {"CL=F", "BZ=F"} else ""
        if requested:
            symbols = [requested]
        elif selector in {"WTI", "CL", "CL=F"}:
            symbols = ["CL=F"]
        elif selector in {"BRENT", "BZ", "BZ=F"}:
            symbols = ["BZ=F"]
        else:
            symbols = ["CL=F", "BZ=F"]

        rows: list[dict[str, Any]] = []
        chart_history: list[dict[str, Any]] = []
        provider_errors: list[str] = []
        if live and self.deps.yfinance:
            for sym in symbols:
                row, history, errors = await _contract_snapshot(
                    self.deps.yfinance,
                    sym,
                    days=days,
                    timeout=timeout,
                    include_history=True,
                )
                provider_errors.extend(errors)
                if row:
                    rows.append(row)
                if not chart_history and history:
                    chart_history = history

        source_mode = "live_yfinance" if rows else "model"
        if not rows and not live:
            rows = [_model_row(sym) for sym in symbols]
        if not rows:
            data = _provider_unavailable_payload(
                "WTI/Brent futures quote provider returned no usable live oil rows.",
                [
                    "Retry after the public futures quote provider recovers.",
                    "Choose WTI or Brent explicitly, or run with live=false for the labelled reference model.",
                ],
            )
            data.update({
                "contracts": [COMMODITY_CONTRACTS[s] for s in symbols],
                "methodology": "BOIL reads WTI CL=F and Brent BZ=F front-month futures. It only reports OK when a last price or chart-derived close is available.",
                "field_dictionary": _commodity_field_dictionary(),
            })
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=data,
                sources=["yfinance_futures"],
                warnings=provider_errors,
                metadata={"provider_errors": provider_errors or ["oil futures quotes unavailable"]},
            )

        spread = None
        if len(rows) >= 2 and rows[0].get("last") is not None and rows[1].get("last") is not None:
            by_symbol = {row["symbol"]: row for row in rows}
            if "BZ=F" in by_symbol and "CL=F" in by_symbol:
                spread = by_symbol["BZ=F"]["last"] - by_symbol["CL=F"]["last"]

        data = {
            "status": "ok" if source_mode == "live_yfinance" else "reference_model",
            "market": "oil",
            "benchmark": selector or "WTI/BRENT",
            "source_mode": source_mode,
            "rows": rows,
            "history": chart_history,
            "spread": spread,
            "methodology": "BOIL reports front-month WTI (CL=F) and Brent (BZ=F) futures. Change % is (last / previous close - 1) * 100; history is daily OHLCV from Yahoo chart data.",
            "field_dictionary": _commodity_field_dictionary(),
        }
        return FunctionResult(
            code=self.code,
            instrument=None,
            data=data,
            sources=["yfinance_futures" if source_mode == "live_yfinance" else "commodity_reference_model"],
            warnings=provider_errors,
            metadata={"degraded": source_mode != "live_yfinance"} if source_mode != "live_yfinance" else {},
        )


@FunctionRegistry.register
class BGASFunction(BaseFunction):
    """BGAS — Henry Hub natural gas."""
    code = "BGAS"
    name = "Natural Gas Spot"
    asset_classes = (AssetClass.COMMODITY,)
    category = "commodity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        live = _truthy(params.get("live", True) or params.get("live_screen"))
        days = _int_param(params, "days", 365, 20, 1095)
        quote_timeout = max(1.0, min(float(params.get("quote_timeout", params.get("yfinance_timeout", 4))), 8.0))
        contract = str(params.get("contract") or (instrument.symbol if instrument else "") or "NG=F").strip().upper()
        # BUG-HUNT S01: previously a non-NG=F contract was silently
        # reverted to NG=F. Track the override so the user knows.
        original_contract = contract
        symbol = contract if contract in COMMODITY_CONTRACTS else "NG=F"
        provider_errors: list[str] = []
        if original_contract != symbol:
            provider_errors.append(
                f"contract={original_contract!r} not in COMMODITY_CONTRACTS; using NG=F"
            )
        try:
            if self.deps.eia:
                df = await self.deps.eia.fetch(DataRequest(
                    kind=DataKind.ECON_SERIES, symbols=["HENRYHUB"]))
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data={
                        "status": "ok",
                        "symbol": "HENRYHUB",
                        "source_mode": "live_eia",
                        "rows": df.to_dict("records") if hasattr(df, "to_dict") else df,
                        "methodology": "BGAS reads Henry Hub natural gas spot data from EIA when configured.",
                        "field_dictionary": _commodity_field_dictionary(),
                    },
                    sources=["eia"],
                )
        except Exception as exc:  # noqa: BLE001
            # BUG-HUNT S01: previously `except Exception: pass` hid EIA
            # transport failures so the yfinance fallback ran silently
            # even when EIA was the configured primary. Capture into
            # provider_errors so the source/status panel can show why.
            provider_errors.append(f"eia: {exc}")
        row = None
        history: list[dict[str, Any]] = []
        if live and self.deps.yfinance:
            # BUG-HUNT S01: preserve the EIA + contract-override errors
            # we already accumulated; don't let _contract_snapshot's own
            # error list overwrite them.
            row, history, snapshot_errors = await _contract_snapshot(
                self.deps.yfinance,
                symbol,
                days=days,
                timeout=quote_timeout,
                include_history=True,
            )
            provider_errors.extend(snapshot_errors)
        if row:
            data = {
                "status": "ok",
                "symbol": symbol,
                "source_mode": "live_yfinance",
                "rows": [row],
                "history": history,
                "methodology": "BGAS/NGAS uses the selected natural-gas futures contract, default NG=F. Change % is (last / previous close - 1) * 100; history is daily OHLCV.",
                "field_dictionary": _commodity_field_dictionary(),
            }
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=data,
                sources=["yfinance_futures"],
                warnings=provider_errors,
            )
        if not live:
            model = _model_row("NG=F")
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "reference_model",
                    "symbol": "NG=F",
                    "source_mode": "model",
                    "rows": [model],
                    "methodology": "Deterministic reference row used only when live=false.",
                    "field_dictionary": _commodity_field_dictionary(),
                },
                sources=["commodity_reference_model"],
                metadata={"degraded": True},
            )
        if live:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": "Natural gas quote provider returned no usable live quote.",
                    "rows": [],
                    "next_actions": [
                        "Retry BGAS/NGAS after the public quote provider recovers.",
                        "Run without live=true for the deterministic local market model.",
                    ],
                    "methodology": "BGAS/NGAS only reports OK when NG=F or the selected gas contract returns a usable last price or chart close.",
                    "field_dictionary": _commodity_field_dictionary(),
                },
                sources=["yfinance_futures"],
                warnings=provider_errors,
                metadata={"provider_errors": provider_errors or ["natural gas futures quote unavailable"]},
            )
        return FunctionResult(code=self.code, instrument=None, data={}, sources=[])


@FunctionRegistry.register
class NGASFunction(BGASFunction):
    """NGAS — Natural gas (alias)."""
    code = "NGAS"
    name = "Natural Gas"


@FunctionRegistry.register
class CPFFunction(BaseFunction):
    """CPF — Commodity Price Forecasts (World Bank Pink Sheet)."""
    code = "CPF"
    name = "Commodity Price Forecasts"
    asset_classes = (AssetClass.COMMODITY,)
    category = "commodity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        scenario = str(params.get("scenario") or "baseline").strip().lower()
        horizon_years = _int_param(params, "horizon_years", 4, 1, 6)
        wanted = _csv_lower(params.get("commodities"))
        factor = {
            "bear": 0.90,
            "downside": 0.90,
            "low": 0.90,
            "baseline": 1.0,
            "base": 1.0,
            "bull": 1.10,
            "upside": 1.10,
            "high": 1.10,
        }.get(scenario, 1.0)
        min_year = datetime.now(timezone.utc).year - 1
        max_year = min_year + horizon_years
        rows: list[dict[str, Any]] = []
        previous: dict[str, float] = {}
        for row in FORECAST_REFERENCE_ROWS:
            commodity_key = str(row["commodity"]).lower()
            if wanted and not any(item in commodity_key for item in wanted):
                continue
            year = int(row["year"])
            if year < min_year or year > max_year:
                continue
            base_value = float(row["forecast_value"])
            value = base_value * factor
            prev = previous.get(commodity_key)
            previous[commodity_key] = value
            rows.append({
                **row,
                "bucket": f"{year} {row['commodity']}",
                "forecast_value": round(value, 6),
                "scenario": scenario,
                "vintage": "2026-04 reference baseline",
                "source_mode": "reference_model",
                "yoy_change_pct": round((value / prev - 1) * 100, 4) if prev else None,
                "note": "Labelled reference forecast; connect World Bank/Pink Sheet feed for live vintage updates.",
            })
        data = {
            "status": "reference_baseline",
            "reason": "No live commodity forecast feed is configured; using a labelled multi-year reference forecast model.",
            "scenario": scenario,
            "horizon_years": horizon_years,
            "rows": rows,
            "surface": rows,
            "methodology": "CPF compares multi-year commodity forecast levels by commodity and scenario. Upside/downside scenarios scale the baseline by +/-10%; values are not live unless a forecast feed is configured.",
            "field_dictionary": {
                "forecast_value": "Forecast level in the row unit.",
                "yoy_change_pct": "Scenario-adjusted change from the previous forecast year for the same commodity.",
                "vintage": "Forecast/reference vintage used for the row.",
                "source_mode": "live feed or labelled reference model.",
            },
            "next_actions": [
                "Connect a World Bank Pink Sheet or equivalent forecast feed for live vintage rows.",
                "Use Scenario and Horizon controls to compare baseline/upside/downside assumptions.",
            ],
        }
        return FunctionResult(
            code=self.code,
            instrument=None,
            data=data,
            sources=["commodity_forecast_reference_model"],
            metadata={"degraded": True},
        )


@FunctionRegistry.register
class GLCOFunction(BaseFunction):
    """GLCO — Global Commodity Movers (yfinance ETFs)."""
    code = "GLCO"
    name = "Global Commodity Movers"
    asset_classes = (AssetClass.COMMODITY,)
    category = "commodity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        symbols = ["CL=F", "BZ=F", "NG=F", "RB=F", "HO=F", "GC=F", "SI=F", "HG=F", "ZC=F", "ZW=F", "ZS=F", "KC=F", "SB=F", "CT=F"]
        rows: list[dict[str, Any]] = []
        provider_errors: list[str] = []
        live = _truthy(params.get("live", True))
        if self.deps.yfinance:
            quote_timeout = max(1.0, min(float(params.get("quote_timeout", 2.0)), 4.0))
            screen_timeout = max(2.0, min(float(params.get("screen_timeout", 5.0)), 7.0))

            async def _one(sym: str) -> dict[str, Any] | None:
                row, _history, errors = await _contract_snapshot(
                    self.deps.yfinance,
                    sym,
                    days=30,
                    timeout=quote_timeout,
                    include_history=False,
                )
                provider_errors.extend(errors)
                return row

            if live:
                tasks = [asyncio.create_task(_one(s)) for s in symbols]
                done, pending = await asyncio.wait(tasks, timeout=screen_timeout)
                for task in pending:
                    task.cancel()
                for task in done:
                    if task.cancelled():
                        continue
                    row = task.result()
                    if row:
                        rows.append(row)
        if not rows:
            rows = [_model_row(sym) for sym in symbols]
            rows = _filter_sector(rows, params.get("sector"))
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": "Commodity futures quote provider returned no usable live rows; table is a labelled reference model.",
                    "source_mode": "model",
                    "rows": rows,
                    "methodology": "GLCO ranks a commodity futures universe by percent change. Live mode uses Yahoo futures quotes; if no live rows return, model rows are labelled and not treated as live quotes.",
                    "field_dictionary": _commodity_field_dictionary(),
                    "next_actions": [
                        "Retry GLCO after the public quote provider recovers.",
                        "Use sector tabs to narrow the commodity universe while the provider recovers.",
                    ],
                },
                sources=["yfinance", "commodity_reference_model"],
                warnings=provider_errors,
                metadata={"provider_errors": provider_errors or ["yfinance commodity futures unavailable"]},
            )
        rows = _filter_sector(rows, params.get("sector"))
        rows.sort(key=lambda row: abs(float(row.get("change_pct") or 0)), reverse=True)
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": "ok",
                "source_mode": "live_yfinance",
                "rows": rows,
                "methodology": "GLCO ranks front-month commodity futures by absolute percent move. Change % is (last / previous close - 1) * 100.",
                "field_dictionary": _commodity_field_dictionary(),
            },
            sources=["yfinance"],
            warnings=provider_errors,
        )


@FunctionRegistry.register
class WETRFunction(BaseFunction):
    """WETR — Weather trends for commodity-relevant regions."""
    code = "WETR"
    name = "Weather Trends"
    asset_classes = (AssetClass.COMMODITY,)
    category = "commodity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        days = _int_param(params, "days", 7, 3, 16)
        location_key = str(params.get("location") or "US_NORTHEAST").strip().upper()
        preset = LOCATION_PRESETS.get(location_key, LOCATION_PRESETS["US_NORTHEAST"])
        lat = _finite(params.get("lat")) if params.get("lat") not in (None, "") else None
        lon = _finite(params.get("lon")) if params.get("lon") not in (None, "") else None
        lat = lat if lat is not None else float(preset["lat"])
        lon = lon if lon is not None else float(preset["lon"])
        commodity = str(params.get("commodity") or preset["commodity_context"]).strip()
        if not self.deps.openweather:
            rows = _weather_model_rows(days, lat, lon, location_key, commodity)
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": "OPENWEATHERMAP_API_KEY is not configured; rows are a labelled seasonal weather model, not live forecast data.",
                    "location": location_key,
                    "lat": lat,
                    "lon": lon,
                    "commodity_context": commodity,
                    "source_mode": "seasonal_model",
                    "rows": rows,
                    "history": rows,
                    "risk_flags": sorted({row["risk_flag"] for row in rows}),
                    "methodology": "WETR shows weather variables relevant to commodities. HDD=max(18C-temp,0), CDD=max(temp-18C,0); risk flags map dry/hot/cold/wet days to demand or crop-weather pressure.",
                    "field_dictionary": {
                        "temp_c": "Daily average temperature in Celsius.",
                        "precip_mm": "Daily precipitation in millimeters.",
                        "hdd": "Heating degree days versus 18C.",
                        "cdd": "Cooling degree days versus 18C.",
                        "commodity_impact": "Plain-language link between weather and the selected commodity context.",
                    },
                    "next_actions": [
                        "Set OPENWEATHERMAP_API_KEY for live forecast rows.",
                        "Use Location/Lat/Lon controls to switch commodity-relevant regions.",
                    ],
                },
                sources=["seasonal_weather_model"],
                metadata={"provider_errors": ["OPENWEATHERMAP_API_KEY not set"]},
            )
        try:
            data = await self.deps.openweather.onecall(lat, lon)
        except Exception as e:
            rows = _weather_model_rows(days, lat, lon, location_key, commodity)
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": f"OpenWeather request failed: {e}",
                    "location": location_key,
                    "lat": lat,
                    "lon": lon,
                    "commodity_context": commodity,
                    "source_mode": "seasonal_model",
                    "rows": rows,
                    "history": rows,
                    "methodology": "OpenWeather failed, so WETR returned labelled seasonal model rows.",
                    "field_dictionary": {
                        "temp_c": "Daily average temperature in Celsius.",
                        "precip_mm": "Daily precipitation in millimeters.",
                        "hdd": "Heating degree days versus 18C.",
                        "cdd": "Cooling degree days versus 18C.",
                    },
                    "next_actions": ["Check OpenWeather credentials/network and rerun."],
                },
                sources=["openweathermap", "seasonal_weather_model"],
                metadata={"provider_errors": [str(e)]},
            )
        rows = _normalise_weather_rows(data, days, lat, lon, location_key, commodity)
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": "ok",
                "location": location_key,
                "lat": lat,
                "lon": lon,
                "commodity_context": commodity,
                "source_mode": "live_openweathermap",
                "rows": rows,
                "history": rows,
                "methodology": "WETR normalizes OpenWeather daily forecast rows and adds commodity impact flags.",
                "field_dictionary": {
                    "temp_c": "Daily average temperature in Celsius.",
                    "precip_mm": "Daily precipitation in millimeters.",
                    "hdd": "Heating degree days versus 18C.",
                    "cdd": "Cooling degree days versus 18C.",
                },
            },
            sources=["openweathermap"],
        )


def _commodity_field_dictionary() -> dict[str, str]:
    return {
        "symbol": "Yahoo futures ticker for the front-month contract.",
        "name": "Plain-language commodity name.",
        "sector": "Energy, metals, agriculture, or softs grouping.",
        "contract": "Contract description used by the quote.",
        "unit": "Price unit such as USD/bbl or USD/MMBtu.",
        "last": "Latest live futures price or chart-derived close.",
        "prev": "Previous close used for change calculations.",
        "change_pct": "(last / prev - 1) * 100.",
        "source_mode": "live_yfinance, live_eia, or labelled model.",
        "as_of": "Provider timestamp or chart date for the row.",
    }


def _csv_lower(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    else:
        items = str(value).split(",")
    return [str(item).strip().lower() for item in items if str(item).strip()]


def _weather_model_rows(
    days: int,
    lat: float,
    lon: float,
    location: str,
    commodity: str,
) -> list[dict[str, Any]]:
    start = datetime.now(timezone.utc).date()
    warm_bias = 2.5 if lat < 35 else 0.0
    rows: list[dict[str, Any]] = []
    for i in range(days):
        date = start + timedelta(days=i)
        temp = 17.5 + warm_bias + math.sin(i / 2.2) * 3.0 + i * 0.15
        precip = max(0.0, 2.4 - i * 0.12 + (0.8 if i % 5 == 0 else 0.0))
        hdd = max(18.0 - temp, 0.0)
        cdd = max(temp - 18.0, 0.0)
        if precip < 1 and temp > 22:
            risk = "dry_heat_watch"
        elif hdd > 2:
            risk = "heating_demand"
        elif cdd > 4:
            risk = "cooling_demand"
        elif precip > 3:
            risk = "wet_weather"
        else:
            risk = "normal"
        rows.append({
            "date": date.isoformat(),
            "day": i + 1,
            "location": location,
            "lat": lat,
            "lon": lon,
            "temp_c": round(temp, 2),
            "precip_mm": round(precip, 2),
            "hdd": round(hdd, 2),
            "cdd": round(cdd, 2),
            "risk_flag": risk,
            "commodity_impact": _weather_impact(risk, commodity),
            "source_mode": "seasonal_model",
        })
    return rows


def _normalise_weather_rows(
    data: Any,
    days: int,
    lat: float,
    lon: float,
    location: str,
    commodity: str,
) -> list[dict[str, Any]]:
    daily = data.get("daily") if isinstance(data, dict) else None
    if not isinstance(daily, list):
        return _weather_model_rows(days, lat, lon, location, commodity)
    rows: list[dict[str, Any]] = []
    for i, item in enumerate(daily[:days]):
        if not isinstance(item, dict):
            continue
        temp_raw = item.get("temp")
        temp = None
        if isinstance(temp_raw, dict):
            vals = [_finite(temp_raw.get(key)) for key in ("day", "min", "max")]
            vals = [v for v in vals if v is not None]
            temp = sum(vals) / len(vals) if vals else None
        else:
            temp = _finite(temp_raw)
        if temp is None:
            continue
        precip = _finite(item.get("rain")) or _finite(item.get("precipitation")) or 0.0
        hdd = max(18.0 - temp, 0.0)
        cdd = max(temp - 18.0, 0.0)
        risk = "heating_demand" if hdd > 2 else "cooling_demand" if cdd > 4 else "wet_weather" if precip > 3 else "normal"
        ts = item.get("dt")
        if isinstance(ts, (int, float)):
            date = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        else:
            date = (datetime.now(timezone.utc).date() + timedelta(days=i)).isoformat()
        rows.append({
            "date": date,
            "day": i + 1,
            "location": location,
            "lat": lat,
            "lon": lon,
            "temp_c": round(temp, 2),
            "precip_mm": round(precip, 2),
            "hdd": round(hdd, 2),
            "cdd": round(cdd, 2),
            "risk_flag": risk,
            "commodity_impact": _weather_impact(risk, commodity),
            "source_mode": "live_openweathermap",
        })
    return rows or _weather_model_rows(days, lat, lon, location, commodity)


def _weather_impact(risk: str, commodity: str) -> str:
    context = commodity or "commodities"
    if risk == "heating_demand":
        return f"Colder weather can lift {context} demand, especially gas/power."
    if risk == "cooling_demand":
        return f"Hotter weather can lift {context} cooling load and power burn."
    if risk == "dry_heat_watch":
        return f"Dry heat can pressure {context} supply or crop conditions."
    if risk == "wet_weather":
        return f"Wet weather can affect {context} logistics, field work, or demand."
    return f"No unusual weather pressure flagged for {context}."
