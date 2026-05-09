"""COUN — Country Guide (ekonomi + siyaset + mali, tek sayfada)."""

from __future__ import annotations

from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument
from src.functions.macro.btmm import BTMMFunction
from src.functions.macro.ecst import ECSTFunction


@FunctionRegistry.register
class COUNFunction(BaseFunction):
    code = "COUN"
    name = "Country Guide"
    category = "macro"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        country = (params.get("country") or "US").upper()
        live = _truthy(params.get("live_macro") or params.get("live"))
        profile = _country_profile_model(country)
        if not live:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=profile,
                sources=["country_reference_profile"],
                metadata={"live": False},
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
            },
            sources=_unique(["btmm", "fred", "country_reference_profile"]),
            warnings=provider_errors,
            metadata={"country": country, "series": series, "provider_errors": provider_errors},
        )


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
    rows = list(profile.get("rows") or [])
    if policy_row:
        rows.insert(0, {
            "section": "rates",
            "metric": "Policy rate",
            "value": policy_row.get("policy_rate"),
            "unit": "%",
            "as_of": policy_row.get("as_of"),
            "country": country,
            "source_mode": policy_row.get("source") or "BTMM",
        })
    return rows + indicators


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
