"""CRVF — Yield Curve."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.functions._fred_csv import (
    _KeylessFredCSV,
    fetch_fred_csv_series,
    fred_with_keyless_fallback,
)

LOG = logging.getLogger("showme.engine.functions.crvf")

_NON_US_REASON = (
    "No curve is wired for {country}: CRVF's only source is FRED's US Treasury "
    "(DGS*) curve, so no live or reference {country} curve is returned."
)
_NON_US_NEXT_ACTIONS = [
    "Use country=US for the FRED Treasury curve.",
    "Use Yield & Spread Analytics (YAS) to price a specific bond.",
]


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _live_requested(params: dict[str, Any]) -> bool:
    """Live FRED is the default; ``reference`` and ``live_curve=false`` opt out.

    ``live_curve`` is the manifest switch. ``reference`` stays as a legacy
    alias so existing callers keep the canned curve.
    """
    if _truthy(params.get("reference")):
        return False
    raw = params.get("live_curve")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return True
    return _truthy(raw)


def _requested_tenors(raw: Any) -> list[str] | None:
    """Normalise the ``tenors`` input (list or comma string); None = all."""
    if raw is None:
        return None
    if isinstance(raw, str):
        items: list[Any] = raw.split(",")
    elif isinstance(raw, (list, tuple, set)):
        items = list(raw)
    else:
        items = [raw]
    tenors = [str(item).strip().upper() for item in items if str(item).strip()]
    return tenors or None


def _filter_curve(curve: dict[str, float], tenors: list[str] | None) -> dict[str, float]:
    if tenors is None:
        return curve
    wanted = set(tenors)
    return {tenor: value for tenor, value in curve.items() if tenor in wanted}


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
    "2M": 2 / 12,
    "4M": 4 / 12,
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
# wiring the keyless CSV fallback (2026-09-08). R2 L-2: the monthly bill
# ids (DGS1MO/DGS2MO/DGS4MO, served by the keyed adapter path) used to
# fall through the _TENOR_YEARS filter and silently drop as well; they now
# map to fractional years end-to-end.
_SERIES_TO_TENOR = {
    "DGS1MO": "1M",
    "DGS2MO": "2M",
    "DGS4MO": "4M",
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


def _curve_payload(
    country: str,
    curve: dict[str, float],
    source_mode: str,
    as_of_by_tenor: dict[str, str] | None = None,
    tenor_filter: list[str] | None = None,
) -> dict[str, Any]:
    as_of_by_tenor = as_of_by_tenor or {}
    rows = [
        {
            "country": country,
            "tenor": tenor,
            "tenor_years": _TENOR_YEARS.get(tenor, 0),
            "yield": float(value),
            # The FRED observation date for this tenor; None when the
            # provider does not report it (never the fetch date).
            "as_of": as_of_by_tenor.get(tenor),
        }
        for tenor, value in curve.items()
        if tenor in _TENOR_YEARS
    ]
    rows.sort(key=lambda row: float(row["tenor_years"]))
    as_of_values = [row["as_of"] for row in rows if row["as_of"]]
    return {
        "rows": rows,
        "curve": rows,
        "summary": {
            "country": country,
            "tenors": len(rows),
            "source_mode": source_mode,
            "as_of": max(as_of_values) if as_of_values else None,
            "tenor_filter": list(tenor_filter) if tenor_filter else None,
            "latest_10y": next((row["yield"] for row in rows if row["tenor"] == "10Y"), None),
        },
        "methodology": "CRVF returns a sovereign yield curve ordered by maturity. The chart uses tenor_years on the x-axis and yield on the y-axis, so it is a true maturity curve rather than a row-index line.",
        "field_dictionary": {
            "tenor": "Curve maturity label.",
            "tenor_years": "Numeric maturity used for the curve x-axis.",
            "yield": "Annualized yield percentage for that tenor.",
            "as_of": "FRED observation date of that tenor's yield (null when the provider does not report it).",
        },
    }


_LIVE_UNAVAILABLE_REASON = (
    "FRED live US curve unavailable ({detail}). The static computed model is not "
    "served in place of a live request; the API caller can set live_curve=false to view it, labelled as a model."
)
_LIVE_UNAVAILABLE_NEXT = [
    "Retry later: FRED did not return the DGS* Treasury yields.",
    "Set live_curve=false to view the labelled computed_model curve (not live).",
    "Use Yield & Spread Analytics (YAS) to price a specific bond.",
]


def _no_match_warnings(tenor_filter: list[str] | None, curve: dict[str, float]) -> list[str]:
    if tenor_filter and not curve:
        return [f"no curve point matches tenors={','.join(tenor_filter)}"]
    return []


async def _keyless_curve_with_dates(client: Any) -> tuple[dict[str, float], dict[str, str]]:
    """Latest value and FRED observation date per series, one fetch per series.

    Value and date come from the same frame. A failed fetch is not cached,
    so a second pass over the series would refetch it.
    """
    curve: dict[str, float] = {}
    dates: dict[str, str] = {}
    for series_id in _KeylessFredCSV._CURVE_IDS:
        try:
            frame = await fetch_fred_csv_series(series_id, client=client)
        except Exception:  # noqa: BLE001 - a missing series is reported by absence
            frame = None
        if frame is None or frame.empty:
            continue
        value = float(frame["value"].iloc[-1])
        if value != value:
            continue
        tenor = _SERIES_TO_TENOR.get(series_id, series_id)
        curve[tenor] = value
        dates[tenor] = frame.index[-1].date().isoformat()
    return curve, dates


async def _keyed_curve_with_dates(fred: Any) -> tuple[dict[str, float], dict[str, str]]:
    """Keyed FRED: value and observation date from one adapter call.

    An adapter that reports only values (no ``yield_curve_observations``)
    yields no dates, so as_of stays null rather than a fetch date.
    """
    observe = getattr(fred, "yield_curve_observations", None)
    if observe is not None:
        observations = await observe()
    else:
        observations = {sid: (value, None) for sid, value in (await fred.yield_curve()).items()}
    curve: dict[str, float] = {}
    dates: dict[str, str] = {}
    for sid, (value, when) in observations.items():
        if value is None or value != value:
            continue
        tenor = _SERIES_TO_TENOR.get(sid, sid)
        curve[tenor] = float(value)
        if when is not None:
            dates[tenor] = when.date().isoformat()
    return curve, dates


async def _fetch_live_curve(fred: Any, client: Any) -> tuple[dict[str, float], dict[str, str], str]:
    """Return (curve, as_of_by_tenor, failure_detail); detail is empty on success."""
    if isinstance(fred, _KeylessFredCSV):
        curve, dates = await _keyless_curve_with_dates(client)
        return curve, dates, "" if curve else "fredgraph.csv returned no usable DGS* yields"
    try:
        curve, dates = await _keyed_curve_with_dates(fred)
    except Exception as e:  # noqa: BLE001 - the reason is reported, never hidden
        reason = str(e) or e.__class__.__name__
        LOG.warning("CRVF live curve fetch failed: %s", reason)
        return {}, {}, reason
    return curve, dates, "" if curve else "FRED returned no usable DGS* yields"


@FunctionRegistry.register
class CRVFFunction(BaseFunction):
    code = "CRVF"
    name = "Yield Curve"
    category = "bond"

    def _unavailable(
        self,
        country: str,
        tenor_filter: list[str] | None,
        reason: str,
        next_actions: list[str] | None = None,
    ) -> FunctionResult:
        data: dict[str, Any] = {
            "status": "provider_unavailable",
            "reason": reason,
            "next_actions": list(next_actions or _NON_US_NEXT_ACTIONS),
        }
        data.update(_curve_payload(country, {}, "provider_unavailable", tenor_filter=tenor_filter))
        return FunctionResult(
            code=self.code,
            instrument=None,
            data=data,
            sources=[],
            warnings=[reason],
            metadata={"country": country, "mode": "provider_unavailable",
                      "live": False, "data_mode": "unavailable"},
        )

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        country = (params.get("country") or "US").upper()
        tenor_filter = _requested_tenors(params.get("tenors"))
        # Only the US Treasury curve is wired. A non-US request gets an
        # explicit unavailable state, never the US levels under its label.
        if country != "US":
            return self._unavailable(country, tenor_filter, _NON_US_REASON.format(country=country))

        if not _live_requested(params):
            # Explicit opt-out (live_curve=false or reference=true): the
            # static model, labelled computed_model and never called live.
            curve = _filter_curve(_curve_model(), tenor_filter)
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=_curve_payload(country, curve, "computed_model", tenor_filter=tenor_filter),
                sources=["curve_model"],
                warnings=_no_match_warnings(tenor_filter, curve),
                metadata={"country": country, "mode": "computed_model",
                          "live": False, "data_mode": "modeled"},
            )
        # Live branch: the keyed FRED adapter when keyed, else the keyless
        # fredgraph.csv endpoint. A failed or empty fetch is an honest
        # provider_unavailable state; the model is never substituted.
        client = getattr(self, "_http_client", None)
        fred = fred_with_keyless_fallback(self.deps.fred, client=client)
        curve, as_of_by_tenor, detail = await _fetch_live_curve(fred, client)
        if not curve:
            reason = _LIVE_UNAVAILABLE_REASON.format(detail=detail or "no usable yields")
            return self._unavailable(country, tenor_filter, reason, next_actions=_LIVE_UNAVAILABLE_NEXT)
        curve = _filter_curve(curve, tenor_filter)
        warnings = _no_match_warnings(tenor_filter, curve)
        return FunctionResult(
            code=self.code,
            instrument=None,
            data=_curve_payload(
                country,
                curve,
                "fred",
                as_of_by_tenor=as_of_by_tenor,
                tenor_filter=tenor_filter,
            ),
            sources=["fred"],
            warnings=warnings,
            metadata={"country": country, "mode": "fred",
                      "live": not warnings, "data_mode": "live_official"},
        )
