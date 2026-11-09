"""ECST — Economic Statistics (FRED-backed series viewer)."""

from __future__ import annotations

import asyncio
import calendar
import datetime
import re
from typing import Any

import pandas as pd

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions._fred_csv import (
    _KeylessFredCSV,
    fred_with_keyless_fallback,
    keyless_ignored_request_params,
)


_SERIES_CATALOG: dict[str, dict[str, str]] = {
    "CPIAUCSL": {"label": "US CPI all urban consumers", "unit": "index", "frequency": "monthly"},
    "GDPC1": {"label": "US real GDP", "unit": "billions chained USD", "frequency": "quarterly"},
    "UNRATE": {"label": "US unemployment rate", "unit": "%", "frequency": "monthly"},
    "DGS10": {"label": "US 10Y Treasury yield", "unit": "%", "frequency": "daily"},
    "DGS2": {"label": "US 2Y Treasury yield", "unit": "%", "frequency": "daily"},
}

_WINDOW_RE = re.compile(r"^\s*(\d+)\s*([DMY])\s*$", re.IGNORECASE)

# The keyed FRED API takes aggregation codes, not labels. "native" means no
# aggregation, so no frequency parameter is sent at all.
_FRED_FREQUENCY_CODES: dict[str, str] = {
    "daily": "d",
    "weekly": "w",
    "monthly": "m",
    "quarterly": "q",
    "annual": "a",
}


def _frequency_request(value: Any) -> tuple[str | None, str | None]:
    """Return ``(requested_name, fred_code)``; ``(None, None)`` for native/empty.

    Anything outside the seed's frequency options raises ``ValueError`` so the
    caller reports an explicit input_error instead of sending it to a provider.
    """
    text = str(value or "").strip().lower()
    if text in ("", "native"):
        return None, None
    if text in _FRED_FREQUENCY_CODES:
        return text, _FRED_FREQUENCY_CODES[text]
    raise ValueError(
        f"unsupported frequency {value!r}: use native, daily, weekly, monthly, "
        "quarterly or annual"
    )


def _window_start(date_range: str, today: datetime.date) -> str:
    """Start date (YYYY-MM-DD) for a ``<n>D|M|Y`` window ending today.

    The unit is part of the request: ``6M`` is six months, not six years.
    Anything that is not a positive count with unit D, M or Y raises
    ``ValueError`` so the caller can report an input error.
    """
    match = _WINDOW_RE.match(str(date_range))
    if not match or int(match.group(1)) < 1:
        raise ValueError(
            f"unsupported date_range {date_range!r}: use a positive count with unit "
            "D, M or Y (e.g. 30D, 6M, 10Y) or MAX"
        )
    count = int(match.group(1))
    unit = match.group(2).upper()
    if unit == "D":
        try:
            start = today - datetime.timedelta(days=count)
        except OverflowError as exc:  # timedelta or date arithmetic left the calendar
            raise ValueError(
                f"date_range {date_range!r} starts before year 1"
            ) from exc
    elif unit == "M":
        total = today.year * 12 + (today.month - 1) - count
        year, month0 = divmod(total, 12)
        month = month0 + 1
        if year < 1:
            raise ValueError(f"date_range {date_range!r} starts before year 1")
        day = min(today.day, calendar.monthrange(year, month)[1])
        start = datetime.date(year, month, day)
    else:
        if today.year - count < 1:
            raise ValueError(f"date_range {date_range!r} starts before year 1")
        try:
            start = today.replace(year=today.year - count)
        except ValueError:  # 29 Feb in a non-leap target year
            start = today.replace(year=today.year - count, day=28)
    return start.strftime("%Y-%m-%d")


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
        if str(date_range).strip().upper() != "MAX":
            # F4 fix: the window must track the real system date. A pinned
            # "today" silently skews the 10Y start and drifts further every
            # session.
            try:
                start_date = _window_start(str(date_range), datetime.date.today())
            except ValueError as exc:
                return _window_input_error(self.code, instrument, sid, str(exc))
        try:
            requested_frequency, fred_frequency = _frequency_request(params.get("frequency"))
        except ValueError as exc:
            return _window_input_error(
                self.code,
                instrument,
                sid,
                str(exc),
                next_action="Use a frequency of native, daily, weekly, monthly, quarterly or annual.",
            )

        # ECST#5: level (as published) or y/y % change. A y/y value needs the observation
        # one year earlier, so the fetch starts ~400 days before the window; the window
        # itself is applied after the transform.
        transform_raw = str(params.get("transform") or "level").strip().lower()
        transform = transform_raw if transform_raw in _TRANSFORMS else "level"
        transform_warnings: list[str] = (
            [] if transform_raw in _TRANSFORMS
            else [f"ECST: unknown transform {transform_raw!r}; level served"]
        )
        fetch_start = start_date
        if transform == "yoy" and start_date:
            fetch_start = (pd.Timestamp(start_date) - pd.Timedelta(days=_YOY_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

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
        
        # ECST#5: frequency and vintage are FRED controls. Labels go to FRED as its codes
        # ("monthly" -> "m"); "native" and "latest" send nothing. Whether FRED applied them is
        # reported after the fetch, never assumed.
        raw_vintage = str(params.get("vintage") or "latest").strip()
        fred_vintage = None if raw_vintage.lower() == "latest" else raw_vintage

        # 1. Try fetching from FRED
        series_info = {}
        compare_info = {}
        # Keyless FRED CSV (survey S2 c#3): without a keyed adapter the
        # series still comes live from fredgraph.csv (info() is keyed-only
        # and is skipped by the existing except guard).
        fred = fred_with_keyless_fallback(
            self.deps.fred, client=getattr(self, "_http_client", None)
        )
        # HNT-20: the keyless CSV serves native frequency and latest vintage
        # only. Record any other request so the response says it was not applied.
        unhonoured = keyless_ignored_request_params(
            fred,
            frequency=params.get("frequency"),
            vintage=params.get("vintage"),
        )
        if fred:
            try:
                df = await asyncio.wait_for(
                    fred.series(
                        sid,
                        start=fetch_start,
                        frequency=fred_frequency,
                        vintage=fred_vintage
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
                provider_errors.append(f"fred: {str(e) or type(e).__name__}")
                
            if compare_sid:
                try:
                    compare_df = await asyncio.wait_for(
                        fred.series(
                            compare_sid,
                            start=fetch_start,
                            frequency=fred_frequency,
                            vintage=fred_vintage
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
                    provider_errors.append(f"fred (compare): {str(e) or type(e).__name__}")

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
                    provider_errors.append(f"worldbank: {str(e) or type(e).__name__}")
                    
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
                        provider_errors.append(f"worldbank (compare): {str(e) or type(e).__name__}")

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
            if transform == "yoy":
                df = _yoy_frame(df)
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
            if transform == "yoy":
                compare_df = _yoy_frame(compare_df)
            if start_date:
                compare_df = compare_df[compare_df.index >= start_date]

            # Rename value to compare_value
            compare_df = compare_df.rename(columns={"value": "compare_value"})
            merged = pd.merge(df, compare_df[["compare_value"]], left_index=True, right_index=True, how="outer")
            # Data policy: no value is carried onto a date it was not observed.
            # The overlay keeps only dates the main series observed; compare_value
            # is present only where the compare series itself was observed.
            df = merged.sort_index()
            df = df[df["value"].notna()]

        # Normalize and construct response metadata
        keyless_fred = isinstance(fred, _KeylessFredCSV)
        applied_by_fred = main_available and source_mode == "fred" and not keyless_fred
        # The keyed API aggregated the series to the requested frequency, so the response
        # and every row report that frequency, not the native catalog one.
        # ECST#3: the World Bank indicators this adapter serves are annual, whatever the
        # catalog frequency of the FRED series says, so the rows must not claim monthly.
        served_native_frequency = _WORLDBANK_NATIVE_FREQUENCY if source_mode == "worldbank" else None
        rows = _normalize_rows(
            df,
            sid,
            source_mode,
            compare_sid,
            frequency=requested_frequency if applied_by_fred else served_native_frequency,
        )
        if transform == "yoy":
            for row in rows:
                row["unit"] = YOY_UNIT
                row["transform"] = "yoy"
        latest = rows[-1] if rows else {}

        catalog = _series_meta(sid)
        label = series_info.get("title") or catalog["label"]
        unit = series_info.get("units") or catalog["unit"]
        frequency = series_info.get("frequency") or catalog["frequency"]
        if source_mode == "worldbank":
            frequency = _WORLDBANK_NATIVE_FREQUENCY
        if transform == "yoy":
            label = f"{label} (y/y % change)"
            unit = YOY_UNIT

        # ECST#5: only the keyed FRED adapter applies a frequency or pinned vintage; the keyless
        # CSV shim serves native-frequency latest-vintage data. Say so rather than imply it.
        # A request is applied only when the keyed FRED adapter served the series, or when
        # it asked for nothing (native / latest). With no observations nothing was applied.
        worldbank_native_request = source_mode == "worldbank" and requested_frequency == _WORLDBANK_NATIVE_FREQUENCY
        frequency_applied = fred_frequency is None or applied_by_fred or worldbank_native_request
        vintage_applied = fred_vintage is None or applied_by_fred
        if requested_frequency and applied_by_fred:
            # The keyed API aggregated the series to the requested frequency, so the
            # response reports that frequency, not the native one.
            frequency = requested_frequency
        request_warnings: list[str] = []
        if not frequency_applied:
            request_warnings.append(
                f"ECST: frequency {requested_frequency} not applied: {_not_applied_reason(keyless_fred, source_mode)}"
            )
        if not vintage_applied:
            request_warnings.append(
                f"ECST: vintage {raw_vintage} not applied: {_not_applied_reason(keyless_fred, source_mode)}"
            )
        warnings: list[str] = [*provider_errors, *transform_warnings, *request_warnings]
        reason: str | None = None
        if not main_available:
            reason = (
                "; ".join(provider_errors)
                if provider_errors
                else f"no live provider returned observations for {sid!r}"
            )
            if not provider_errors:
                warnings.append(f"ECST: {reason}")
        # Observations existed but none fall inside the requested window: an
        # explicit empty state, not an ok live series with zero rows.
        main_in_window = main_available and bool(rows)
        if main_available and not rows:
            reason = (
                f"provider returned observations for {sid!r}, but none fall on or "
                f"after the requested window start {start_date or 'MAX'}"
            )
        if compare_sid and compare_source_mode == "provider_unavailable":
            warnings.append(
                f"{compare_sid} compare series was unavailable from the providers — "
                "the overlay is omitted (no synthetic series is served)."
            )
        if unhonoured:
            requested = ", ".join(
                f"{name}={params.get(name)!r}" for name in unhonoured
            )
            warnings.append(
                f"ECST: {requested} not applied — the keyless FRED CSV source serves "
                f"native frequency and latest vintage only; the series is returned at "
                f"its native frequency ({frequency})."
            )

        data_res = {
            "series_id": sid,
            "series_name": label,
            "unit": unit,
            "frequency": frequency,
            "transform": transform,
            "status": (
                "ok" if main_in_window
                else "empty" if main_available
                else "provider_unavailable"
            ),
            "data_state": (
                "live" if main_in_window
                else "empty" if main_available
                else "provider_unavailable"
            ),
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
            "frequency_requested": str(params.get("frequency") or "native").strip().lower(),
            "frequency_applied": frequency_applied,
            "vintage_requested": raw_vintage,
            "vintage_applied": vintage_applied,
        }
        if reason is not None:
            data_res["reason"] = reason
            data_res["next_actions"] = [
                "Retry ECST — FRED and World Bank may be momentarily unreachable.",
                f"Confirm '{sid}' is a valid FRED series id.",
            ]
        if unhonoured:
            data_res["unhonoured_params"] = unhonoured

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


_TRANSFORMS = frozenset({"level", "yoy"})


_WORLDBANK_NATIVE_FREQUENCY = "annual"


def _not_applied_reason(keyless: bool, source_mode: str | None) -> str:
    if source_mode == "worldbank":
        return "the series was served by worldbank, which publishes annual data and does not apply a frequency or vintage"
    if source_mode in (None, "provider_unavailable"):
        return "no live provider returned observations, so nothing was served with the request"
    if keyless:
        return "the keyless FRED CSV serves native-frequency, latest-vintage data only (a FRED API key applies it)"
    return f"the series was served by {source_mode or 'no provider'}, which does not apply it"
YOY_UNIT = "% y/y"
# Calendar slack so the observation a year before the window start is fetched.
_YOY_LOOKBACK_DAYS = 400
# A prior-year observation must sit within this many days of the same date a year earlier.
_YOY_MATCH_TOLERANCE_DAYS = 10


def _yoy_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Percent change against the observation one calendar year earlier.

    Input and output are indexed by ISO date strings with a ``value`` column. The prior
    observation is the nearest one within ``_YOY_MATCH_TOLERANCE_DAYS`` of the same date
    a year earlier. A date with no such observation is dropped: a y/y value is never
    estimated or carried forward.
    """
    empty = frame.iloc[0:0]
    if frame.empty or "value" not in frame.columns:
        return empty
    base = pd.DataFrame({
        "date": pd.to_datetime(frame.index),
        "value": pd.to_numeric(frame["value"], errors="coerce").to_numpy(),
    }).dropna(subset=["value"]).sort_values("date").reset_index(drop=True)
    if base.empty:
        return empty
    prior = base.rename(columns={"date": "prior_date", "value": "prior_value"})
    base["target"] = base["date"] - pd.DateOffset(years=1)
    merged = pd.merge_asof(
        base.sort_values("target"),
        prior.sort_values("prior_date"),
        left_on="target",
        right_on="prior_date",
        direction="nearest",
        tolerance=pd.Timedelta(days=_YOY_MATCH_TOLERANCE_DAYS),
    )
    merged = merged.dropna(subset=["prior_value"])
    merged = merged[merged["prior_value"] != 0]
    if merged.empty:
        return empty
    out = pd.DataFrame(
        {"value": ((merged["value"] / merged["prior_value"] - 1.0) * 100.0).to_numpy()},
        index=merged["date"].dt.strftime("%Y-%m-%d").to_numpy(),
    )
    out.index.name = "date"
    return out.sort_index()


def _series_meta(series_id: str) -> dict[str, str]:
    return _SERIES_CATALOG.get(series_id, {"label": series_id, "unit": "value", "frequency": "unknown"})


def _window_input_error(
    code: str,
    instrument: Instrument | None,
    sid: str,
    reason: str,
    next_action: str = "Use a date range such as 1Y, 3Y, 5Y, 10Y, 20Y or MAX.",
) -> FunctionResult:
    """Explicit input_error envelope: no provider call, no rows, no guessed window."""
    return FunctionResult(
        code=code,
        instrument=instrument,
        data={
            "series_id": sid,
            "series_name": _series_meta(sid)["label"],
            "status": "input_error",
            "data_state": "input_error",
            "rows": [],
            "history": [],
            "cards": [{"label": "Series", "value": sid}],
            "reason": reason,
            "next_actions": [next_action],
            "source_mode": "input_error",
        },
        sources=[],
        warnings=[f"ECST: {reason}"],
    )


def _normalize_rows(
    df: pd.DataFrame, 
    series_id: str, 
    source_mode: str, 
    compare_sid: str | None = None,
    limit: int = 1500,
    frequency: str | None = None,
) -> list[dict[str, Any]]:
    """Build the row list. ``frequency`` is the applied aggregation (keyed FRED
    only); when absent each row keeps the series' native catalog frequency."""
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
        if value is None or pd.isna(value):
            continue
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
            "frequency": frequency or meta["frequency"],
            "source_mode": source_mode,
        }
        
        if "compare_value" in item and item.get("compare_value") is not None and not pd.isna(item.get("compare_value")):
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
