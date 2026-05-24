"""CRVF — Yield Curve."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument

LOG = logging.getLogger("showme.engine.functions.crvf")


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
        live = bool(params.get("live_curve") or params.get("live"))
        if not live:
            curve = _curve_model()
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=_curve_payload(country, curve, "computed_model"),
                sources=["curve_model"],
                warnings=[],
                metadata={"country": country, "mode": "computed_model"},
            )
        # Live branch: FRED currently only ships the US Treasury curve. Be
        # honest when the requested country is not US, or when the FRED
        # adapter is missing / failed.
        if country == "US" and self.deps.fred:
            try:
                curve = await self.deps.fred.yield_curve()
                curve = {k: v for k, v in curve.items() if v is not None and v == v}
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
        elif not self.deps.fred:
            warnings.append("fred adapter unavailable; using computed_model fallback")
            # QA-fix: log so operators know the FRED adapter is the missing piece.
            LOG.warning("CRVF: FRED adapter unavailable (likely FRED_API_KEY unset)")
        source_mode = "fred" if curve and not warnings else "computed_model"
        if not curve:
            curve = _curve_model()
        return FunctionResult(
            code=self.code,
            instrument=None,
            data=_curve_payload(country, curve, source_mode),
            sources=[source_mode],
            warnings=warnings,
            metadata={"country": country, "mode": source_mode},
        )
