"""WB — World Bonds (sovereign yields heatmap)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.functions._fred_csv import fred_with_keyless_fallback


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


_SOVEREIGN_FRED_IDS = {
    # Developed markets.
    "US": "DGS10",
    "DE": "IRLTLT01DEM156N",
    "JP": "IRLTLT01JPM156N",
    "GB": "IRLTLT01GBM156N",
    "CA": "IRLTLT01CAM156N",
    "FR": "IRLTLT01FRM156N",
    "IT": "IRLTLT01ITM156N",
    "ES": "IRLTLT01ESM156N",
    "AU": "IRLTLT01AUM156N",
    # Emerging markets — the exact roster the WB pane's EM tab filters on
    # (OECD long-term 10Y benchmark series on FRED).
    "TR": "IRLTLT01TRM156N",
    "BR": "IRLTLT01BRM156N",
    "MX": "IRLTLT01MXM156N",
    "ZA": "IRLTLT01ZAM156N",
    "IN": "IRLTLT01INM156N",
    "CN": "IRLTLT01CNM156N",
    "RU": "IRLTLT01RUM156N",
    "ID": "IRLTLT01IDM156N",
}

# F4 fix: the labelled template is a static reference snapshot, so its rows
# must carry the model vintage — not "today", which would claim the levels
# were observed on the request date.
_MODEL_TEMPLATE_VINTAGE = "2025-12-31"


def _world_bond_template() -> dict[str, float]:
    # Static reference levels (labelled sovereign_yield_model, NOT live).
    return {
        "US": 4.45, "DE": 2.58, "JP": 0.92, "GB": 4.18, "CA": 3.35,
        "FR": 3.02, "IT": 3.86, "ES": 3.24, "AU": 4.12,
        "TR": 28.50, "BR": 12.80, "MX": 9.10, "ZA": 10.20,
        "IN": 6.85, "CN": 2.05, "RU": 13.40, "ID": 6.65,
    }


def _rows_from_yields(values: dict[str, float], source_mode: str, tenor: str = "10Y") -> dict[str, Any]:
    is_template = source_mode == "sovereign_yield_model"
    as_of = (
        _MODEL_TEMPLATE_VINTAGE
        if is_template
        else datetime.now(timezone.utc).date().isoformat()
    )
    rows = [
        {
            "country": country,
            "tenor": tenor,
            "yield": float(yield_pct),
            "as_of": as_of,
            "source_mode": source_mode,
            **({"reference_vintage": _MODEL_TEMPLATE_VINTAGE} if is_template else {}),
        }
        for country, yield_pct in values.items()
    ]
    rows.sort(key=lambda row: str(row["country"]))
    summary: dict[str, Any] = {"countries": len(rows), "tenor": tenor, "source_mode": source_mode}
    if is_template:
        summary["reference_vintage"] = _MODEL_TEMPLATE_VINTAGE
    return {
        "rows": rows,
        "summary": summary,
        "methodology": "WB shows sovereign benchmark yields by country. The bundled default is a 10Y comparison; each row labels country, tenor, yield, source mode, and snapshot date.",
        "field_dictionary": {
            "country": "ISO-style country code.",
            "tenor": "Benchmark maturity used for comparison.",
            "yield": "Annualized sovereign yield percentage.",
            "source_mode": "fred when live data is available, otherwise sovereign_yield_model.",
            "as_of": "Observation date for live rows; the model vintage for template rows.",
        },
    }


@FunctionRegistry.register
class WBFunction(BaseFunction):
    code = "WB"
    name = "World Bonds"
    category = "bond"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        raw_countries = params.get("countries")
        country_filter = {
            str(item).strip().upper()
            for item in (raw_countries if isinstance(raw_countries, (list, tuple, set)) else str(raw_countries or "").split(","))
            if str(item).strip()
        }
        fred_ids = {
            country: fred_id
            for country, fred_id in _SOVEREIGN_FRED_IDS.items()
            if not country_filter or country in country_filter
        }
        # Default-polarity flip + keyless FRED CSV (survey S2 c#3, item 4):
        # WB pulls live sovereign yields by default — keyed adapter when
        # wired, otherwise the keyless fredgraph.csv endpoint — and serves
        # the labelled template only behind ``reference=true``.
        if _truthy(params.get("reference")):
            data = {country: value for country, value in _world_bond_template().items() if not country_filter or country in country_filter}
            return FunctionResult(code=self.code, instrument=None, data=_rows_from_yields(data, "sovereign_yield_model"),
                                  sources=["sovereign_yield_model"],
                                  warnings=["reference=true; serving the labelled sovereign yield template."])
        fred = fred_with_keyless_fallback(
            self.deps.fred, client=getattr(self, "_http_client", None)
        )
        out: dict[str, float] = {}
        timeout = float(params.get("fred_timeout", 8))
        async def _one(country, fred_id):
            try:
                df = await asyncio.wait_for(fred.series(fred_id), timeout=timeout)
                return country, float(df["value"].iloc[-1])
            except Exception:
                return country, float("nan")
        results = await asyncio.gather(*(
            _one(c, fid) for c, fid in fred_ids.items()
        ))
        for c, y in results:
            out[c] = y
        out = {c: y for c, y in out.items() if y == y}
        if not out:
            out = _world_bond_template()
            return FunctionResult(code=self.code, instrument=None, data=_rows_from_yields(out, "sovereign_yield_model"), sources=["sovereign_yield_model"],
                                  warnings=["Live sovereign yields unavailable (keyed FRED adapter or keyless CSV); showing the labelled reference template."])
        return FunctionResult(code=self.code, instrument=None, data=_rows_from_yields(out, "fred"), sources=["fred"],
                              metadata={"live": True, "data_mode": "live_official"})
