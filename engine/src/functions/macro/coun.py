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
        if not live:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=_country_profile_model(country),
                sources=["country_profile_model"],
                metadata={"live": False},
            )
        btmm = await BTMMFunction(self.deps).execute(country=country)
        # FRED series mapping per country (US default)
        series_per_country = {
            "US": ["GDPC1", "CPIAUCSL", "UNRATE", "DGS10"],
            "EU": ["LRHUTTTTEZQ156S"],
            "GB": ["GBRCPIALLMINMEI"],
            "TR": ["TURGDPRQDSMEI"],
        }
        series = series_per_country.get(country, [])
        ecst_results = []
        for sid in series:
            try:
                r = await ECSTFunction(self.deps).execute(series_id=sid)
                ecst_results.append({"id": sid, "result": r.data})
            except Exception:
                continue
        return FunctionResult(
            code=self.code, instrument=None,
            data={"country": country, "rates": btmm.data, "indicators": ecst_results},
            sources=["seed", "fred"],
        )


def _country_profile_model(country: str) -> dict[str, Any]:
    profiles = {
        "US": {"policy_rate": 0.0525, "inflation": 0.031, "unemployment": 0.039, "currency": "USD"},
        "EU": {"policy_rate": 0.04, "inflation": 0.026, "unemployment": 0.064, "currency": "EUR"},
        "GB": {"policy_rate": 0.0525, "inflation": 0.032, "unemployment": 0.043, "currency": "GBP"},
        "TR": {"policy_rate": 0.50, "inflation": 0.55, "unemployment": 0.09, "currency": "TRY"},
    }
    profile = profiles.get(country, {"policy_rate": 0.04, "inflation": 0.03, "unemployment": 0.06, "currency": None})
    return {
        "country": country,
        "rates": {
            "policy_rate": profile["policy_rate"],
            "currency": profile["currency"],
            "curve_bias": "template_neutral",
        },
        "indicators": [
            {"id": "GDP", "result": {"latest": 0.02, "trend": "stable"}},
            {"id": "CPI", "result": {"latest": profile["inflation"], "trend": "moderating"}},
            {"id": "UNEMPLOYMENT", "result": {"latest": profile["unemployment"], "trend": "stable"}},
        ],
    }


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
