"""CRVF — Yield Curve."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.functions._fred_csv import fred_with_keyless_fallback

LOG = logging.getLogger("showme.engine.functions.crvf")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _curve_model() -> dict[str, float]:
    return {
        "1M": 5.32,
        "3M": 5.28,
        "6M": 5.15,
        "1Y": 4.92,
        "2Y": 4.62,
        "5Y": 4.38,
        "10Y": 4.45,
        "30Y": 4.67,
    }


_TENOR_YEARS = {
    "1M": 1 / 12,
    "3M": 0.25,
    "6M": 0.5,
    "1Y": 1.0,
    "2Y": 2.0,
    "3Y": 3.0,
    "5Y": 5.0,
    "7Y": 7.0,
    "10Y": 10.0,
    "20Y": 20.0,
    "30Y": 30.0,
}

# FredAdapter.yield_curve() (and the keyless CSV shim) return raw FRED
# series ids; _curve_payload filters on tenor labels. Without this mapping
# every live curve row was silently dropped (rows=[]) — caught while
# wiring the keyless CSV fallback (2026-09-08).
_SERIES_TO_TENOR = {
    "DGS3MO": "3M",
    "DGS6MO": "6M",
    "DGS1": "1Y",
    "DGS2": "2Y",
    "DGS3": "3Y",
    "DGS5": "5Y",
    "DGS7": "7Y",
    "DGS10": "10Y",
    "DGS20": "20Y",
    "DGS30": "30Y",
}


def _curve_payload(country: str, curve: dict[str, float], source_mode: str) -> dict[str, Any]:
    rows = [
        {
            "country": country,
            "tenor": tenor,
            "tenor_years": _TENOR_YEARS.get(tenor, 0),
            "yield": float(value),
            "as_of": datetime.now(timezone.utc).date().isoformat(),
        }
        for tenor, value in curve.items()
        if tenor in _TENOR_YEARS
    ]
    rows.sort(key=lambda row: float(row["tenor_years"]))
    return {
        "rows": rows,
        "curve": rows,
        "summary": {
            "country": country,
            "tenors": len(rows),
            "source_mode": source_mode,
            "latest_10y": next((row["yield"] for row in rows if row["tenor"] == "10Y"), None),
        },
        "methodology": "CRVF returns a sovereign yield curve ordered by maturity. The chart uses tenor_years on the x-axis and yield on the y-axis, so it is a true maturity curve rather than a row-index line.",
        "field_dictionary": {
            "tenor": "Curve maturity label.",
            "tenor_years": "Numeric maturity used for the curve x-axis.",
            "yield": "Annualized yield percentage for that tenor.",
            "as_of": "Date of the curve snapshot shown by this function.",
        },
    }


@FunctionRegistry.register
class CRVFFunction(BaseFunction):
    code = "CRVF"
    name = "Yield Curve"
    category = "bond"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        country = (params.get("country") or "US").upper()
        warnings: list[str] = []
        curve: dict[str, float] = {}
        # Default-polarity flip (survey S2 c#3): the live curve (keyed
        # adapter, else keyless fredgraph.csv) is the default; the canned
        # model curve serves only on ``reference=true`` or labelled failure.
        live = not _truthy(params.get("reference"))
        if not live:
            curve = _curve_model()
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=_curve_payload(country, curve, "computed_model"),
                sources=["curve_model"],
                warnings=[],
                metadata={"country": country, "mode": "computed_model",
                          "live": False, "data_mode": "modeled"},
            )
        # Live branch: FRED currently only ships the US Treasury curve. Be
        # honest when the requested country is not US, or when the FRED
        # fetch fails. Keyless fallback (survey S2 c#3): without a keyed
        # adapter the curve still comes live from fredgraph.csv.
        fred = fred_with_keyless_fallback(
            self.deps.fred, client=getattr(self, "_http_client", None)
        )
        if country == "US":
            try:
                curve = await fred.yield_curve()
                curve = {
                    _SERIES_TO_TENOR.get(k, k): v
                    for k, v in curve.items()
                    if v is not None and v == v
                }
            except Exception as e:
                # QA-fix: log + propagate reason so the warning is never an
                # empty "fred: " label.
                reason = str(e) or e.__class__.__name__
                LOG.warning("CRVF live curve fetch failed: %s", reason)
                warnings.append(f"fred: {reason}")
        elif country != "US":
            warnings.append(
                f"live curve for {country} is not wired; using computed_model fallback"
            )
            LOG.info("CRVF non-US country %s: provider_unavailable", country)
        if not curve and not warnings:
            warnings.append("fred curve came back empty; using computed_model fallback")
            LOG.warning("CRVF: live FRED curve returned no usable tenors")
        source_mode = "fred" if curve and not warnings else "computed_model"
        if not curve:
            curve = _curve_model()
        return FunctionResult(
            code=self.code,
            instrument=None,
            data=_curve_payload(country, curve, source_mode),
            sources=[source_mode],
            warnings=warnings,
            metadata={"country": country, "mode": source_mode,
                      "live": bool(curve) and not warnings,
                      "data_mode": "live_official" if source_mode == "fred" else "modeled"},
        )
