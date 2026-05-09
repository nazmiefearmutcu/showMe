"""ECST — Economic Statistics (FRED-backed series viewer)."""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


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
        df = pd.DataFrame()
        sources: list[str] = []
        provider_errors: list[str] = []
        timeout = float(params.get("timeout", 8))
        if self.deps.fred:
            try:
                df = await asyncio.wait_for(
                    self.deps.fred.series(sid, frequency=params.get("frequency")),
                    timeout=timeout,
                )
                sources.append("fred")
            except Exception as e:
                provider_errors.append(f"fred: {e}")
        if df.empty and self.deps.worldbank:
            try:
                df = await asyncio.wait_for(
                    self.deps.worldbank.indicator("USA", sid),
                    timeout=timeout,
                )
                sources.append("worldbank")
            except Exception as e:
                provider_errors.append(f"worldbank: {e}")
        source_mode = sources[-1] if sources else "macro_series_baseline"
        if df.empty:
            df = pd.DataFrame(_baseline_rows_for_series(sid))
            sources.append("macro_series_baseline")
            source_mode = "macro_series_baseline"
        rows = _normalize_rows(df, sid, source_mode)
        latest = rows[-1] if rows else {}
        catalog = _series_meta(sid)
        warnings = provider_errors if source_mode == "macro_series_baseline" else []
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "series_id": sid,
                "series_name": catalog["label"],
                "unit": catalog["unit"],
                "frequency": catalog["frequency"],
                "rows": rows,
                "history": rows,
                "cards": [
                    {"label": "Series", "value": sid},
                    {"label": "Latest", "value": latest.get("value")},
                    {"label": "Unit", "value": catalog["unit"]},
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
                    "source_mode": "Provider or fallback used for the row.",
                },
                "source_mode": source_mode,
            },
            sources=sources,
            warnings=warnings,
            metadata={"series_id": sid, "provider_errors": provider_errors, "source_mode": source_mode}
            if provider_errors else {"series_id": sid, "source_mode": source_mode},
        )


def _series_meta(series_id: str) -> dict[str, str]:
    return _SERIES_CATALOG.get(series_id, {"label": series_id, "unit": "value", "frequency": "unknown"})


def _baseline_rows_for_series(series_id: str) -> list[dict[str, float | str]]:
    baselines: dict[str, list[float]] = {
        "CPIAUCSL": [3.1, 3.0, 2.9],
        "GDPC1": [23_714.2, 23_861.4, 24_018.8],
        "UNRATE": [4.0, 4.1, 4.1],
        "DGS10": [4.18, 4.28, 4.31],
        "DGS2": [3.84, 3.91, 3.93],
    }
    frequency = _series_meta(series_id)["frequency"]
    dates = ["2026-01-01", "2026-02-01", "2026-03-01"]
    if frequency == "quarterly":
        dates = ["2025-07-01", "2025-10-01", "2026-01-01"]
    values = baselines.get(series_id, [1.0, 1.0, 1.0])
    return [{"date": date, "value": value} for date, value in zip(dates, values, strict=False)]


def _normalize_rows(df: pd.DataFrame, series_id: str, source_mode: str) -> list[dict[str, Any]]:
    meta = _series_meta(series_id)
    rows: list[dict[str, Any]] = []
    if df.empty:
        return rows
    data = df.reset_index() if "date" not in df.columns else df.copy()
    for _, item in data.tail(240).iterrows():
        date_value = item.get("date")
        if date_value is None:
            date_value = item.get("index")
        value = item.get("value")
        try:
            numeric_value = round(float(value), 6)
        except (TypeError, ValueError):
            continue
        rows.append({
            "date": str(date_value)[:10],
            "series_id": series_id,
            "series_name": meta["label"],
            "value": numeric_value,
            "unit": meta["unit"],
            "frequency": meta["frequency"],
            "source_mode": source_mode,
        })
    return rows
