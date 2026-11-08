"""ECST — Economic Statistics (FRED-backed series viewer)."""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions._fred_csv import fred_with_keyless_fallback


_SERIES_CATALOG: dict[str, dict[str, str]] = {
    "CPIAUCSL": {"label": "US CPI all urban consumers", "unit": "index", "frequency": "monthly"},
    "GDPC1": {"label": "US real GDP", "unit": "billions chained USD", "frequency": "quarterly"},
    "UNRATE": {"label": "US unemployment rate", "unit": "%", "frequency": "monthly"},
    "DGS10": {"label": "US 10Y Treasury yield", "unit": "%", "frequency": "daily"},
    "DGS2": {"label": "US 2Y Treasury yield", "unit": "%", "frequency": "daily"},
}


@FunctionRegistry.register
class ECSTFunction(BaseFunction):
    code = "ECST"
    name = "Economic Statistics"
    asset_classes = (AssetClass.MACRO,)
    category = "macro"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        sid = params.get("series_id") or (instrument.symbol if instrument else "CPIAUCSL")
        compare_sid = params.get("compare_with")
        
        # Parse date range to calculate start date
        start_date = None
        date_range = params.get("date_range") or "10Y"
        if date_range != "MAX":
            import datetime
            # F4 fix: the window must track the real system date. A pinned
            # "today" silently skews the 10Y start and drifts further every
            # session.
            today = datetime.date.today()
            try:
                years = int(date_range[:-1])
                start_date = today.replace(year=today.year - years).strftime("%Y-%m-%d")
            except Exception:
                start_date = (today - datetime.timedelta(days=3650)).strftime("%Y-%m-%d")
                
        df = pd.DataFrame()
        compare_df = pd.DataFrame()
        sources: list[str] = []
        provider_errors: list[str] = []
        timeout = float(params.get("timeout", 8))
        # Track the MAIN series' mode separately from any compare series —
        # `sources[-1]` used to flip the main `source_mode` when the compare
        # fetch succeeded (e.g. main from worldbank, compare from fred).
        source_mode: str | None = None
        compare_source_mode: str | None = None

        def _note_source(provider: str) -> None:
            if provider not in sources:
                sources.append(provider)
        
        # 1. Try fetching from FRED
        series_info = {}
        compare_info = {}
        # Keyless FRED CSV (survey S2 c#3): without a keyed adapter the
        # series still comes live from fredgraph.csv (info() is keyed-only
        # and is skipped by the existing except guard).
        fred = fred_with_keyless_fallback(
            self.deps.fred, client=getattr(self, "_http_client", None)
        )
        if fred:
            try:
                df = await asyncio.wait_for(
                    fred.series(
                        sid, 
                        start=start_date, 
                        frequency=params.get("frequency"),
                        vintage=params.get("vintage")
                    ),
                    timeout=timeout,
                )
                sources.append("fred")
                source_mode = "fred"
                try:
                    series_info = await fred.info(sid)
                except Exception:
                    pass
            except Exception as e:
                provider_errors.append(f"fred: {e}")
                
            if compare_sid:
                try:
                    compare_df = await asyncio.wait_for(
                        fred.series(
                            compare_sid, 
                            start=start_date, 
                            frequency=params.get("frequency"),
                            vintage=params.get("vintage")
                        ),
                        timeout=timeout,
                    )
                    if not compare_df.empty:
                        _note_source("fred")
                        compare_source_mode = "fred"
                        try:
                            compare_info = await fred.info(compare_sid)
                        except Exception:
                            pass
                except Exception as e:
                    provider_errors.append(f"fred (compare): {e}")

        # World Bank mapping dictionary
        wb_map = {
            "CPIAUCSL": "FP.CPI.TOTL",
            "GDPC1": "NY.GDP.MKTP.KD",
            "UNRATE": "SL.UEM.TOTL.ZS",
        }

        # 2. Try fetching from World Bank if FRED is empty
        if df.empty and self.deps.worldbank:
            wb_indicator = wb_map.get(sid)
            if wb_indicator:
                try:
                    df = await asyncio.wait_for(
                        self.deps.worldbank.indicator("USA", wb_indicator),
                        timeout=timeout,
                    )
                    if sid == "GDPC1" and not df.empty:
                        df["value"] = df["value"] / 1_000_000_000
                    sources.append("worldbank")
                    source_mode = "worldbank"
                except Exception as e:
                    provider_errors.append(f"worldbank: {e}")
                    
            if compare_sid and compare_df.empty:
                wb_compare_indicator = wb_map.get(compare_sid)
                if wb_compare_indicator:
                    try:
                        compare_df = await asyncio.wait_for(
                            self.deps.worldbank.indicator("USA", wb_compare_indicator),
                            timeout=timeout,
                        )
                        if compare_sid == "GDPC1" and not compare_df.empty:
                            compare_df["value"] = compare_df["value"] / 1_000_000_000
                        if not compare_df.empty:
                            _note_source("worldbank")
                            compare_source_mode = "worldbank"
                    except Exception as e:
                        provider_errors.append(f"worldbank (compare): {e}")

        # Data policy: no synthetic series is ever served as data. When no
        # provider returned observations the series is unavailable (no rows,
        # explicit status + reason); it is never replaced by a constructed curve.
        main_available = not df.empty
        if main_available:
            if source_mode is None:
                source_mode = sources[-1] if sources else "provider_unavailable"
        else:
            source_mode = "provider_unavailable"
            sources = ["no_live_source"]

        if compare_sid and compare_df.empty:
            # The overlay is omitted, not filled with a constructed curve.
            compare_source_mode = "provider_unavailable"

        # Standardize and merge dataframes
        if not df.empty:
            df = df.copy()
            if "date" not in df.columns:
                df = df.reset_index()
            if df["date"].dtype in ('int64', 'int32', 'float64'):
                df["date"] = df["date"].astype(int).apply(lambda y: f"{y}-12-31")
            else:
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            df = df.set_index("date")
            if start_date:
                df = df[df.index >= start_date]

        # The overlay only exists alongside a live main series (no compare-only rows).
        if not compare_df.empty and main_available:
            compare_df = compare_df.copy()
            if "date" not in compare_df.columns:
                compare_df = compare_df.reset_index()
            if compare_df["date"].dtype in ('int64', 'int32', 'float64'):
                compare_df["date"] = compare_df["date"].astype(int).apply(lambda y: f"{y}-12-31")
            else:
                compare_df["date"] = pd.to_datetime(compare_df["date"]).dt.strftime("%Y-%m-%d")
            compare_df = compare_df.set_index("date")
            if start_date:
                compare_df = compare_df[compare_df.index >= start_date]

            # Rename value to compare_value
            compare_df = compare_df.rename(columns={"value": "compare_value"})
            merged = pd.merge(df, compare_df[["compare_value"]], left_index=True, right_index=True, how="outer")
            merged = merged.sort_index().ffill().bfill()
            df = merged

        # Normalize and construct response metadata
        rows = _normalize_rows(df, sid, source_mode, compare_sid)
        latest = rows[-1] if rows else {}
        
        catalog = _series_meta(sid)
        label = series_info.get("title") or catalog["label"]
        unit = series_info.get("units") or catalog["unit"]
        frequency = series_info.get("frequency") or catalog["frequency"]
        
        warnings: list[str] = list(provider_errors)
        reason: str | None = None
        if not main_available:
            reason = (
                "; ".join(provider_errors)
                if provider_errors
                else f"no live provider returned observations for {sid!r}"
            )
            if not provider_errors:
                warnings.append(f"ECST: {reason}")
        if compare_sid and compare_source_mode == "provider_unavailable":
            warnings.append(
                f"{compare_sid} compare series was unavailable from the providers — "
                "the overlay is omitted (no synthetic series is served)."
            )

        data_res = {
            "series_id": sid,
            "series_name": label,
            "unit": unit,
            "frequency": frequency,
            "status": "ok" if main_available else "provider_unavailable",
            "data_state": "live" if main_available else "provider_unavailable",
            "rows": rows,
            "history": rows,
            "cards": [
                {"label": "Series", "value": sid},
                {"label": "Latest", "value": latest.get("value")},
                {"label": "Unit", "value": unit},
                {"label": "As of", "value": latest.get("date")},
            ],
            "methodology": (
                "ECST shows one named macro series at a time. FRED is queried first, "
                "World Bank is used as a secondary adapter. When neither provider "
                "returns observations the response is status provider_unavailable with "
                "no rows: no synthetic or baseline series is ever served as data."
            ),
            "field_dictionary": {
                "date": "Observation date.",
                "series_id": "Provider series code.",
                "series_name": "Human-readable series label.",
                "value": "Observation value in the displayed unit.",
                "compare_value": "Compare series' value on the same observation date (present only when compare_with is set).",
                "source_mode": "Provider or fallback used for the row.",
            },
            "source_mode": source_mode,
        }
        if reason is not None:
            data_res["reason"] = reason
            data_res["next_actions"] = [
                "Retry ECST — FRED and World Bank may be momentarily unreachable.",
                f"Confirm '{sid}' is a valid FRED series id.",
            ]

        if compare_sid:
            compare_catalog = _series_meta(compare_sid)
            compare_label = compare_info.get("title") or compare_catalog["label"]
            data_res["cards"].append({"label": f"vs {compare_sid}", "value": latest.get("compare_value")})
            data_res["compare_series_id"] = compare_sid
            data_res["compare_series_name"] = compare_label
            data_res["compare_source_mode"] = compare_source_mode or "provider_unavailable"

        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data=data_res,
            sources=sources,
            warnings=warnings,
            metadata={"series_id": sid, "provider_errors": provider_errors, "source_mode": source_mode}
            if provider_errors else {"series_id": sid, "source_mode": source_mode},
        )


def _series_meta(series_id: str) -> dict[str, str]:
    return _SERIES_CATALOG.get(series_id, {"label": series_id, "unit": "value", "frequency": "unknown"})


def _normalize_rows(
    df: pd.DataFrame, 
    series_id: str, 
    source_mode: str, 
    compare_sid: str | None = None,
    limit: int = 1500
) -> list[dict[str, Any]]:
    meta = _series_meta(series_id)
    compare_meta = _series_meta(compare_sid) if compare_sid else None
    rows: list[dict[str, Any]] = []
    if df.empty:
        return rows
        
    data = df.reset_index() if "date" not in df.columns else df.copy()
    data = data.sort_values("date")
    
    for _, item in data.tail(limit).iterrows():
        date_value = item.get("date")
        if date_value is None:
            date_value = item.get("index")
        value = item.get("value")
        try:
            numeric_value = round(float(value), 6)
        except (TypeError, ValueError):
            continue
            
        row = {
            "date": str(date_value)[:10],
            "series_id": series_id,
            "series_name": meta["label"],
            "value": numeric_value,
            "unit": meta["unit"],
            "frequency": meta["frequency"],
            "source_mode": source_mode,
        }
        
        if "compare_value" in item and item.get("compare_value") is not None:
            try:
                compare_value = round(float(item["compare_value"]), 6)
                row["compare_value"] = compare_value
                if compare_meta:
                    row["compare_series_id"] = compare_sid
                    row["compare_series_name"] = compare_meta["label"]
            except (TypeError, ValueError):
                pass
                
        rows.append(row)
    return rows
