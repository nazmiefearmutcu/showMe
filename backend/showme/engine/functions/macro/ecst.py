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

        if source_mode is None:
            source_mode = sources[-1] if sources else "macro_series_baseline"
        
        # 3. Fall back to robust baseline if still empty
        if df.empty:
            df = pd.DataFrame(_baseline_rows_for_series(sid))
            _note_source("macro_series_baseline")
            source_mode = "macro_series_baseline"
            
        if compare_sid and compare_df.empty:
            # The compare overlay must stay honest: the baseline is labelled
            # via compare_source_mode (+ a warning), never passed off as the
            # provider the main series used.
            compare_df = pd.DataFrame(_baseline_rows_for_series(compare_sid))
            _note_source("macro_series_baseline")
            compare_source_mode = "macro_series_baseline"

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

        if not compare_df.empty:
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
        
        warnings: list[str] = []
        if source_mode == "macro_series_baseline":
            warnings.extend(provider_errors)
        if compare_sid and compare_source_mode == "macro_series_baseline":
            warnings.append(
                f"{compare_sid} compare series was unavailable from the providers — "
                "the labelled macro_series_baseline is shown for the overlay."
            )
        
        data_res = {
            "series_id": sid,
            "series_name": label,
            "unit": unit,
            "frequency": frequency,
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
                "World Bank is used as a secondary adapter, and a labelled baseline "
                "is only used when neither provider returns data."
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
        
        if compare_sid:
            compare_catalog = _series_meta(compare_sid)
            compare_label = compare_info.get("title") or compare_catalog["label"]
            data_res["cards"].append({"label": f"vs {compare_sid}", "value": latest.get("compare_value")})
            data_res["compare_series_id"] = compare_sid
            data_res["compare_series_name"] = compare_label
            data_res["compare_source_mode"] = compare_source_mode or "macro_series_baseline"

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


def _baseline_rows_for_series(series_id: str) -> list[dict[str, float | str]]:
    import datetime
    meta = _series_meta(series_id)
    freq = meta["frequency"]
    
    start_date = datetime.date(2016, 1, 1)
    end_date = datetime.date(2026, 6, 1)
    rows = []
    
    if series_id == "CPIAUCSL":
        curr_date = start_date
        val = 236.9
        while curr_date <= end_date:
            growth = 0.005 if curr_date.year >= 2021 else 0.0015
            val = val * (1 + growth)
            rows.append({"date": curr_date.strftime("%Y-%m-%d"), "value": round(val, 3)})
            if curr_date.month == 12:
                curr_date = datetime.date(curr_date.year + 1, 1, 1)
            else:
                curr_date = datetime.date(curr_date.year, curr_date.month + 1, 1)
                
    elif series_id == "GDPC1":
        curr_date = start_date
        val = 17500.0
        while curr_date <= end_date:
            val = val * (1 + 0.005)
            if curr_date.year == 2020 and curr_date.month == 4:
                val = val * 0.90
            elif curr_date.year == 2020 and curr_date.month == 7:
                val = val * 1.08
            rows.append({"date": curr_date.strftime("%Y-%m-%d"), "value": round(val, 1)})
            if curr_date.month == 10:
                curr_date = datetime.date(curr_date.year + 1, 1, 1)
            else:
                curr_date = datetime.date(curr_date.year, curr_date.month + 3, 1)
                
    elif series_id == "UNRATE":
        curr_date = start_date
        while curr_date <= end_date:
            if curr_date.year == 2020 and curr_date.month == 4:
                val = 14.7
            elif curr_date.year == 2020 and curr_date.month == 5:
                val = 13.2
            elif curr_date.year == 2020 and curr_date.month in (6, 7, 8):
                val = 10.0
            elif curr_date.year < 2020:
                val = 5.0 - (curr_date.year - 2016) * 0.3 - (curr_date.month / 12.0) * 0.3
                val = max(3.5, val)
            else:
                val = 6.0 - (curr_date.year - 2021) * 0.8
                val = max(3.7, val)
            val += (curr_date.month % 3) * 0.1
            rows.append({"date": curr_date.strftime("%Y-%m-%d"), "value": round(val, 2)})
            if curr_date.month == 12:
                curr_date = datetime.date(curr_date.year + 1, 1, 1)
            else:
                curr_date = datetime.date(curr_date.year, curr_date.month + 1, 1)
                
    elif series_id in ("DGS10", "DGS2"):
        curr_date = start_date
        val = 2.0 if series_id == "DGS10" else 1.0
        while curr_date <= end_date:
            if curr_date.weekday() < 5:
                if curr_date.year <= 2018:
                    val = 2.0 if series_id == "DGS10" else 1.5
                elif curr_date.year == 2020:
                    val = 0.8 if series_id == "DGS10" else 0.2
                elif curr_date.year >= 2023:
                    val = 4.2 if series_id == "DGS10" else 4.5
                else:
                    val = 2.5 if series_id == "DGS10" else 2.0
                day_offset = (curr_date.day % 7) * 0.05 - 0.15
                rows.append({"date": curr_date.strftime("%Y-%m-%d"), "value": round(val + day_offset, 2)})
            curr_date += datetime.timedelta(days=1)
    else:
        curr_date = start_date
        while curr_date <= end_date:
            rows.append({"date": curr_date.strftime("%Y-%m-%d"), "value": 1.0})
            if curr_date.month == 12:
                curr_date = datetime.date(curr_date.year + 1, 1, 1)
            else:
                curr_date = datetime.date(curr_date.year, curr_date.month + 1, 1)
                
    return rows


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
