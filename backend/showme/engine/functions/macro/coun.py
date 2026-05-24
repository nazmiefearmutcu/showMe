"""COUN — Country Guide (ekonomi + siyaset + mali, tek sayfada)."""

from __future__ import annotations

from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.functions.macro.btmm import BTMMFunction
from showme.engine.functions.macro.ecst import ECSTFunction


@FunctionRegistry.register
class COUNFunction(BaseFunction):
    code = "COUN"
    name = "Country Guide"
    category = "macro"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        country = (params.get("country") or "US").upper()
        live = _truthy(params.get("live_macro") or params.get("live"))
        profile = _country_profile_model(country)
        country_is_known = country in _KNOWN_PROFILE_COUNTRIES
        baseline_warnings: list[str] = []
        if not country_is_known:
            baseline_warnings.append(
                f"country '{country}' has no curated profile; using generic reference fallback"
            )
        if not live:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=profile,
                sources=["country_reference_profile"],
                warnings=baseline_warnings,
                metadata={"live": False, "country_known": country_is_known},
            )
        provider_errors: list[str] = []
        try:
            btmm = await BTMMFunction(self.deps).execute(country=country, timeout=params.get("timeout", 4))
            policy_row = (btmm.data.get("rows") or [None])[0] if isinstance(btmm.data, dict) else None
        except Exception as exc:
            provider_errors.append(f"btmm: {exc}")
            policy_row = None
        # FRED series mapping per country (US default)
        series_per_country = {
            "US": ["GDPC1", "CPIAUCSL", "UNRATE", "DGS10"],
            "EU": ["LRHUTTTTEZQ156S"],
            "GB": ["GBRCPIALLMINMEI"],
            "TR": ["TURGDPRQDSMEI"],
        }
        series = series_per_country.get(country, [])
        indicator_rows: list[dict[str, Any]] = []
        history: list[dict[str, Any]] = []
        for sid in series:
            try:
                r = await ECSTFunction(self.deps).execute(series_id=sid, timeout=params.get("timeout", 4))
                row, points = _indicator_from_ecst(country, sid, r.data, r.sources)
                indicator_rows.append(row)
                history.extend(points)
            except Exception as exc:
                provider_errors.append(f"ecst.{sid}: {exc}")
        rows = _country_rows(country, profile, policy_row, indicator_rows)
        # Honest source attribution: only include "fred" if we actually invoked
        # any ECST series, and only include "btmm" if the policy row resolved.
        live_sources: list[str] = []
        if policy_row:
            live_sources.append("btmm")
        if indicator_rows and series:
            live_sources.append("fred")
        live_sources.append("country_reference_profile")
        all_warnings = baseline_warnings + provider_errors
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "country": country,
                "rows": rows,
                "history": history[-80:],
                "cards": _country_cards(country, profile, policy_row, indicator_rows),
                "methodology": (
                    "COUN combines a country reference profile with the latest policy-rate "
                    "row from BTMM and normalized macro series from ECST. Values are shown "
                    "with explicit metric labels, units, dates, and source modes."
                ),
                "field_dictionary": {
                    "metric": "Human-readable country metric.",
                    "value": "Latest normalized value in the displayed unit.",
                    "as_of": "Latest provider date when available.",
                    "source_mode": "Provider or reference layer used for the row.",
                },
                "source_mode": "live_macro" if indicator_rows or policy_row else "reference_country_profile",
                "country_known": country_is_known,
            },
            sources=_unique(live_sources),
            warnings=all_warnings,
            metadata={
                "country": country,
                "series": series,
                "provider_errors": provider_errors,
                "country_known": country_is_known,
            },
        )


_KNOWN_PROFILE_COUNTRIES = frozenset({"US", "EU", "GB", "TR"})


def _country_profile_model(country: str) -> dict[str, Any]:
    profiles = {
        "US": {"policy_rate": 0.0525, "inflation": 0.031, "unemployment": 0.039, "currency": "USD", "gdp_growth": 0.02, "debt_to_gdp": 1.21, "fiscal_balance": -0.058, "ten_year_yield": 0.043},
        "EU": {"policy_rate": 0.04, "inflation": 0.026, "unemployment": 0.064, "currency": "EUR", "gdp_growth": 0.012, "debt_to_gdp": 0.88, "fiscal_balance": -0.031, "ten_year_yield": 0.026},
        "GB": {"policy_rate": 0.0525, "inflation": 0.032, "unemployment": 0.043, "currency": "GBP", "gdp_growth": 0.011, "debt_to_gdp": 0.97, "fiscal_balance": -0.044, "ten_year_yield": 0.041},
        "TR": {"policy_rate": 0.50, "inflation": 0.55, "unemployment": 0.09, "currency": "TRY", "gdp_growth": 0.032, "debt_to_gdp": 0.30, "fiscal_balance": -0.045, "ten_year_yield": 0.275},
    }
    profile = profiles.get(country, {"policy_rate": 0.04, "inflation": 0.03, "unemployment": 0.06, "currency": None, "gdp_growth": 0.015, "debt_to_gdp": None, "fiscal_balance": None, "ten_year_yield": None})
    rows = [
        {"section": "rates", "metric": "Policy rate", "value": profile["policy_rate"] * 100, "unit": "%", "source_mode": "country_reference_profile"},
        {"section": "prices", "metric": "Inflation", "value": profile["inflation"] * 100, "unit": "% y/y", "source_mode": "country_reference_profile"},
        {"section": "labor", "metric": "Unemployment", "value": profile["unemployment"] * 100, "unit": "%", "source_mode": "country_reference_profile"},
        {"section": "growth", "metric": "Real GDP growth", "value": profile["gdp_growth"] * 100, "unit": "% y/y", "source_mode": "country_reference_profile"},
        {"section": "fiscal", "metric": "Fiscal balance", "value": _pct(profile.get("fiscal_balance")), "unit": "% GDP", "source_mode": "country_reference_profile"},
        {"section": "fiscal", "metric": "Debt to GDP", "value": _pct(profile.get("debt_to_gdp")), "unit": "% GDP", "source_mode": "country_reference_profile"},
    ]
    return {
        "country": country,
        "rows": rows,
        "cards": [
            {"label": "Currency", "value": profile["currency"] or "-"},
            {"label": "Policy rate", "value": round(profile["policy_rate"] * 100, 3)},
            {"label": "Inflation", "value": round(profile["inflation"] * 100, 3)},
            {"label": "Unemployment", "value": round(profile["unemployment"] * 100, 3)},
        ],
        "methodology": "Reference country profile used when live macro adapters are unavailable.",
        "field_dictionary": {"value": "Displayed percent or level.", "unit": "Unit shown next to value."},
        "source_mode": "country_reference_profile",
    }


def _indicator_from_ecst(country: str, series_id: str, payload: Any, sources: list[str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = payload.get("rows") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        rows = []
    latest = rows[-1] if rows else {}
    label, unit = _series_label(series_id)
    source_mode = ",".join(sources or ["unknown"])
    points = [
        {
            "date": row.get("date"),
            "metric": label,
            "value": row.get("value"),
            "unit": unit,
            "country": country,
            "source_mode": row.get("source_mode") or source_mode,
        }
        for row in rows
        if isinstance(row, dict) and row.get("date") and row.get("value") is not None
    ]
    return {
        "section": _series_section(series_id),
        "metric": label,
        "value": latest.get("value"),
        "unit": unit,
        "as_of": latest.get("date"),
        "series_id": series_id,
        "source_mode": latest.get("source_mode") or source_mode,
    }, points


def _country_rows(country: str, profile: dict[str, Any], policy_row: dict[str, Any] | None, indicators: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Bug #23 fix: previously this concatenated the reference-profile rows
    # (which always include a static "Policy rate") with a BTMM-sourced
    # "Policy rate" row inserted at position 0 AND with ECST indicator
    # rows. The UI then rendered three "Policy rate" entries with three
    # different values (3.625% live, 5.25% reference, 4.3% 10Y proxy mis-
    # parsed as policy). Solution: deduplicate by ``(section, metric)``,
    # keeping the row with the most recent ``as_of`` timestamp and
    # preferring rows that carry an ``as_of`` at all over reference rows
    # that don't.
    candidates: list[dict[str, Any]] = []
    if policy_row:
        candidates.append({
            "section": "rates",
            "metric": "Policy rate",
            "value": policy_row.get("policy_rate"),
            "unit": "%",
            "as_of": policy_row.get("as_of"),
            "country": country,
            "source_mode": policy_row.get("source") or "BTMM",
        })
    candidates.extend(profile.get("rows") or [])
    candidates.extend(indicators)
    return _deduplicate_country_rows(candidates)


def _deduplicate_country_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop duplicate (section, metric) pairs, keeping the freshest row.

    "Freshest" = the row with the latest ``as_of`` ISO date; rows without
    an ``as_of`` are treated as oldest (reference fallback only wins when
    no live row exists). First seen wins on ties so the BTMM-inserted row
    keeps its leading slot.
    """
    best: dict[tuple[str, str], int] = {}
    out: list[dict[str, Any]] = []
    out_index = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = (str(row.get("section") or ""), str(row.get("metric") or ""))
        if not key[1]:
            # Rows with no metric label can't collide — let them pass through.
            out.append(row)
            out_index += 1
            continue
        if key not in best:
            best[key] = out_index
            out.append(row)
            out_index += 1
            continue
        existing_idx = best[key]
        if _row_freshness(row) > _row_freshness(out[existing_idx]):
            out[existing_idx] = row
    return out


def _row_freshness(row: dict[str, Any]) -> str:
    """Sortable freshness key — empty string for rows with no ``as_of``."""
    as_of = row.get("as_of")
    if not as_of:
        return ""
    return str(as_of)


def _country_cards(country: str, profile: dict[str, Any], policy_row: dict[str, Any] | None, indicators: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards = list(profile.get("cards") or [])
    if policy_row:
        cards = [{"label": "Country", "value": country}, {"label": "Policy rate", "value": policy_row.get("policy_rate")}] + cards
    for row in indicators[:3]:
        cards.append({"label": row.get("metric"), "value": row.get("value")})
    return cards[:8]


def _series_label(series_id: str) -> tuple[str, str]:
    labels = {
        "GDPC1": ("Real GDP", "index"),
        "CPIAUCSL": ("Inflation proxy / CPI", "index"),
        "UNRATE": ("Unemployment rate", "%"),
        "DGS10": ("10Y government yield", "%"),
        "LRHUTTTTEZQ156S": ("Unemployment rate", "%"),
        "GBRCPIALLMINMEI": ("Consumer prices", "index"),
        "TURGDPRQDSMEI": ("Real GDP", "index"),
    }
    return labels.get(series_id, (series_id, "value"))


def _series_section(series_id: str) -> str:
    if series_id in {"GDPC1", "TURGDPRQDSMEI"}:
        return "growth"
    if series_id in {"CPIAUCSL", "GBRCPIALLMINMEI"}:
        return "prices"
    if "UNRATE" in series_id or "LRHUT" in series_id:
        return "labor"
    if series_id.startswith("DGS"):
        return "rates"
    return "macro"


def _pct(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value) * 100, 3)


def _unique(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
