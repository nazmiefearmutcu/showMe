"""GC3D — Yield Curve Surface (curve × time → date-by-tenor yield grid)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.functions._fred_csv import fred_with_keyless_fallback


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


_FRED_TENORS = [
    ("3M", "DGS3MO"), ("6M", "DGS6MO"), ("1Y", "DGS1"), ("2Y", "DGS2"),
    ("3Y", "DGS3"), ("5Y", "DGS5"), ("7Y", "DGS7"),
    ("10Y", "DGS10"), ("20Y", "DGS20"), ("30Y", "DGS30"),
]

# Must match the seed default for ``tenors`` (manifest/seeds/gc3d_seed.py).
_DEFAULT_TENORS = ["3M", "6M", "1Y", "2Y", "5Y", "10Y", "30Y"]

# The only sovereign curve this function can serve (FRED DGS* = US Treasuries).
_SUPPORTED_COUNTRY = "US"

_TENOR_YEARS = {
    "3M": 0.25, "6M": 0.5, "1Y": 1.0, "2Y": 2.0, "3Y": 3.0,
    "5Y": 5.0, "7Y": 7.0, "10Y": 10.0, "20Y": 20.0, "30Y": 30.0,
}

# Template snapshot look-backs in days before today. The template does not
# follow the requested window, so its real span is reported as summary.days.
_TEMPLATE_OFFSETS = (45, 30, 15)


def _parse_tenors(raw: Any) -> tuple[list[str], list[str]]:
    """Return (known tenors in curve order, unrecognised labels)."""
    if raw is None or raw == "" or raw == []:
        items: list[str] = list(_DEFAULT_TENORS)
    elif isinstance(raw, str):
        items = [t.strip() for t in raw.split(",") if t.strip()]
    else:
        items = [str(t).strip() for t in raw if str(t).strip()]
    known = {t for t, _ in _FRED_TENORS}
    wanted = {t.upper() for t in items}
    unknown = [t for t in items if t.upper() not in known]
    chosen = [t for t, _ in _FRED_TENORS if t in wanted]
    return chosen, unknown


def _surface_template(tenors: list[str]) -> dict[str, Any]:
    # Rolling dates anchored to "today" so the fallback never advertises stale
    # timestamps. The yield levels remain a labelled reference template.
    today = datetime.now(timezone.utc).date()
    offsets = _TEMPLATE_OFFSETS
    dates = [(today - timedelta(days=d)).strftime("%Y-%m-%d") for d in offsets]
    base = {"3M": 5.28, "6M": 5.15, "1Y": 4.92, "2Y": 4.62,
            "3Y": 4.47, "5Y": 4.38, "7Y": 4.42, "10Y": 4.45,
            "20Y": 4.61, "30Y": 4.67}
    surface: list[dict[str, Any]] = []
    for i, date in enumerate(dates):
        for tenor in tenors:
            surface.append({"date": date, "tenor": tenor, "tenor_years": _TENOR_YEARS.get(tenor, 0),
                            "yield": round(base.get(tenor, 4.5) + i * 0.015, 4)})
    return _surface_payload(surface, tenors, dates, "yield_curve_model", max(offsets))


def _surface_payload(
    surface: list[dict[str, Any]],
    tenors: list[str],
    dates: list[str],
    source_mode: str,
    days: int,
) -> dict[str, Any]:
    return {
        "surface": surface,
        "rows": surface,
        "tenors": tenors,
        "dates": dates,
        "summary": {
            "source_mode": source_mode,
            "dates": len(dates),
            "tenors": len(tenors),
            "points": len(surface),
            "days": days,
        },
        "methodology": "GC3D builds a date-by-tenor yield grid (tenor rows, date columns). The native renderer shows it as a heat-tinted table with date, tenor, tenor_years, and yield; it is a 2D grid, not a 3D plot.",
        "field_dictionary": {
            "date": "Observation date (FRED observation date, passed through unchanged).",
            "tenor": "Treasury maturity label.",
            "tenor_years": "Numeric maturity for ordering.",
            "yield": "FRED Treasury yield percentage.",
        },
    }


@FunctionRegistry.register
class GC3DFunctionLive(BaseFunction):
    code = "GC3D"
    name = "Yield Curve Surface (live FRED)"
    category = "bond"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        country = str(params.get("country") or _SUPPORTED_COUNTRY).strip().upper()
        if country != _SUPPORTED_COUNTRY:
            return FunctionResult(
                code=self.code, instrument=None,
                data={
                    "status": "input_error",
                    "reason": f"GC3D serves the US Treasury curve (FRED DGS*) only; country={country} is not supported.",
                    "country": country,
                    "next_actions": ["Set country to US."],
                },
                sources=[],
                warnings=[f"Unsupported country {country}: no curve was fetched."],
            )
        tenors, unknown_tenors = _parse_tenors(params.get("tenors"))
        tenor_notes = (
            [f"Ignored unsupported tenors: {', '.join(unknown_tenors)}."] if unknown_tenors else []
        )
        if not tenors:
            return FunctionResult(
                code=self.code, instrument=None,
                data={
                    "status": "input_error",
                    "reason": "None of the requested tenors are available; choose from 3M, 6M, 1Y, 2Y, 3Y, 5Y, 7Y, 10Y, 20Y, 30Y.",
                    "requested_tenors": unknown_tenors,
                    "next_actions": ["Select at least one supported tenor."],
                },
                sources=[],
                warnings=tenor_notes,
            )
        # Clamp to a sane look-back window: a request for `days=999999` used
        # to balloon the FRED query without bound.
        try:
            requested_days = int(params.get("days", 365))
        except (TypeError, ValueError):
            requested_days = 365
        days = max(7, min(requested_days, 3650))
        # Live by default via the keyed FRED adapter when wired, otherwise the
        # keyless fredgraph.csv endpoint. ``reference=true`` serves the labelled
        # template without any fetch.
        if _truthy(params.get("reference")):
            return FunctionResult(
                code=self.code, instrument=None,
                data=_surface_template(tenors),
                sources=["yield_curve_model"],
                warnings=[
                    f"Labelled reference template (fixed reference levels over the last {max(_TEMPLATE_OFFSETS)} days); "
                    f"the requested {days}-day look-back is not applied."
                ] + tenor_notes,
            )
        fred = fred_with_keyless_fallback(
            self.deps.fred, client=getattr(self, "_http_client", None)
        )
        series_by_tenor = {t: sid for t, sid in _FRED_TENORS if t in tenors}

        async def _one(tenor, sid):
            try:
                df = await asyncio.wait_for(
                    fred.series(
                        sid,
                        start=(datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d"),
                    ),
                    timeout=float(params.get("fred_timeout", 8)),
                )
                return tenor, df
            except Exception:
                return tenor, None
        results = await asyncio.gather(*(_one(t, s) for t, s in series_by_tenor.items()))
        # Build surface: rows = dates, cols = tenors
        import pandas as pd
        frame = pd.DataFrame()
        for tenor, df in results:
            if df is None or df.empty:
                continue
            frame[tenor] = df["value"]
        frame = frame.dropna(how="all").sort_index()
        surface = []
        if not frame.empty:
            for date, row in frame.iterrows():
                for tenor in row.index:
                    if row[tenor] != row[tenor]:
                        continue
                    surface.append({"date": date.strftime("%Y-%m-%d"),
                                    "tenor": tenor, "tenor_years": _TENOR_YEARS.get(tenor, 0),
                                    "yield": float(row[tenor])})
        if not surface:
            return FunctionResult(
                code=self.code, instrument=None,
                data=_surface_template(tenors),
                sources=["yield_curve_model"],
                warnings=[
                    "Live FRED curve unavailable (keyed adapter or keyless CSV); showing the labelled reference template "
                    f"with a {max(_TEMPLATE_OFFSETS)}-day span instead of the requested {days}-day look-back."
                ] + tenor_notes,
            )
        live_tenors = [t for t in tenors if any(p["tenor"] == t for p in surface)]
        return FunctionResult(
            code=self.code, instrument=None,
            data=_surface_payload(
                surface,
                live_tenors,
                [d.strftime("%Y-%m-%d") for d in frame.index],
                "fred",
                days,
            ),
            sources=["fred"],
            warnings=tenor_notes,
            metadata={"live": True, "data_mode": "live_official"},
        )
