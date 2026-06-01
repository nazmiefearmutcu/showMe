"""GMM — Global Macro Movers / Global Macro Matrix.

Cross-country macro snapshot built from the World Bank's keyless open-data
API (api.worldbank.org/v2). For each major economy we pull the latest
available value of four canonical indicators — real GDP growth, headline
CPI inflation, unemployment, and general-government debt-to-GDP — and rank
the rows so an analyst can see at a glance which economy is running hot or
cold across the board.

The earlier implementation depended on the key-gated ``tradingeconomics``
adapter and silently degraded to a hardcoded 3-row reference table whenever
the key was absent (the common case), so the UI showed lifeless placeholder
text. This module fetches real, live data from a keyless source instead.
"""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument

# World Bank v2 open-data API — keyless. Each indicator code maps to a
# canonical macro series. We request the most-recent-non-empty value per
# country, because World Bank publishes lagged annual data and the very
# latest year is frequently still null for many economies.
_WB_BASE = "https://api.worldbank.org/v2"

# ISO 3166-1 alpha-2 -> human label for the major economies we cover by default.
_DEFAULT_COUNTRIES: dict[str, str] = {
    "US": "United States",
    "CN": "China",
    "JP": "Japan",
    "DE": "Germany",
    "GB": "United Kingdom",
    "FR": "France",
    "IN": "India",
    "BR": "Brazil",
    "CA": "Canada",
    "IT": "Italy",
    "KR": "South Korea",
    "AU": "Australia",
    "MX": "Mexico",
    "TR": "Turkey",
}

# Indicator code -> (output key, human label, unit). World Bank codes:
#   NY.GDP.MKTP.KD.ZG  GDP growth (annual %)
#   FP.CPI.TOTL.ZG     Inflation, consumer prices (annual %)
#   SL.UEM.TOTL.ZS     Unemployment, total (% of labor force) [modeled ILO]
#   GC.DOD.TOTL.GD.ZS  Central government debt, total (% of GDP)
_INDICATORS: dict[str, tuple[str, str, str]] = {
    "NY.GDP.MKTP.KD.ZG": ("gdp_growth", "GDP growth", "% y/y"),
    "FP.CPI.TOTL.ZG": ("inflation", "CPI inflation", "% y/y"),
    "SL.UEM.TOTL.ZS": ("unemployment", "Unemployment", "% labor force"),
    "GC.DOD.TOTL.GD.ZS": ("debt_gdp", "Debt / GDP", "% of GDP"),
}


@FunctionRegistry.register
class GMMFunction(BaseFunction):
    code = "GMM"
    name = "Global Macro Movers"
    category = "macro"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        # Resolve the requested country universe. Accept "countries" (manifest)
        # or legacy "country"; empty / unknown falls back to the major-economy set.
        requested = params.get("countries") or params.get("country")
        countries = _resolve_countries(requested)
        timeout = float(params.get("timeout", 12))

        rows: list[dict[str, Any]] = []
        try:
            rows = await asyncio.wait_for(
                _fetch_worldbank_matrix(countries), timeout=timeout
            )
        except Exception as exc:  # noqa: BLE001 - honest outage path
            return _provider_unavailable(f"worldbank: {exc}")

        if not rows:
            return _provider_unavailable(
                "worldbank returned no observations for the requested countries."
            )

        # Score = composite macro-stress proxy: high inflation + high
        # unemployment + high debt minus growth. Higher = more stressed /
        # bigger mover. Sort descending so the most extreme economies lead.
        for row in rows:
            row["score"] = _composite_score(row)
        rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0.0)))

        limit = _coerce_int(params.get("top_n") or params.get("limit"), default=len(rows))
        rows = rows[:limit]

        hottest = max(
            (r for r in rows if r.get("inflation") is not None),
            key=lambda r: r["inflation"],
            default=None,
        )
        fastest = max(
            (r for r in rows if r.get("gdp_growth") is not None),
            key=lambda r: r["gdp_growth"],
            default=None,
        )

        cards = [
            {"key": "economies", "label": "Economies", "value": len(rows)},
            {
                "key": "hottest_inflation",
                "label": "Hottest CPI",
                "value": f"{hottest['country']} {hottest['inflation']:.1f}%" if hottest else None,
            },
            {
                "key": "fastest_growth",
                "label": "Fastest GDP",
                "value": f"{fastest['country']} {fastest['gdp_growth']:.1f}%" if fastest else None,
            },
            {"key": "source", "label": "Source", "value": "World Bank"},
        ]

        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": "ok",
                "rows": rows,
                "cards": cards,
                "surface": [
                    {"country": r["country"], "code": r["country_code"], "score": r["score"]}
                    for r in rows
                ],
                "summary": {
                    "economies": len(rows),
                    "indicators": [label for (_k, label, _u) in _INDICATORS.values()],
                },
                "methodology": (
                    "GMM builds a cross-country macro matrix from the World Bank open-data API "
                    "(api.worldbank.org/v2), a keyless source. For each economy it pulls the most "
                    "recent non-null annual observation of four indicators — real GDP growth "
                    "(NY.GDP.MKTP.KD.ZG), headline CPI inflation (FP.CPI.TOTL.ZG), unemployment "
                    "(SL.UEM.TOTL.ZS), and central-government debt-to-GDP (GC.DOD.TOTL.GD.ZS). "
                    "Rows are ranked by a composite macro-stress score = inflation + unemployment "
                    "+ 0.05·debt/GDP − GDP growth, so the economies running hottest/most stretched "
                    "surface first. World Bank annual series are lagged, so each cell carries its "
                    "own observation year. No value is fabricated: a missing cell stays null."
                ),
                "field_dictionary": {
                    "country": "Country name.",
                    "country_code": "ISO 3166-1 alpha-2 code.",
                    "gdp_growth": "Real GDP growth, annual % (World Bank NY.GDP.MKTP.KD.ZG).",
                    "gdp_growth_year": "Year of the GDP growth observation.",
                    "inflation": "Headline CPI inflation, annual % (FP.CPI.TOTL.ZG).",
                    "inflation_year": "Year of the inflation observation.",
                    "unemployment": "Unemployment, % of labor force (SL.UEM.TOTL.ZS).",
                    "unemployment_year": "Year of the unemployment observation.",
                    "debt_gdp": "Central government debt, % of GDP (GC.DOD.TOTL.GD.ZS).",
                    "debt_gdp_year": "Year of the debt/GDP observation.",
                    "score": "Composite macro-stress score (higher = hotter/more stretched).",
                },
                "source_mode": "worldbank",
            },
            sources=["worldbank"],
            warnings=[],
            metadata={"provider": "worldbank", "indicators": list(_INDICATORS.keys())},
        )


def _resolve_countries(requested: Any) -> dict[str, str]:
    """Map a requested country list/string to {code: label}, defaulting to majors."""
    if not requested:
        return dict(_DEFAULT_COUNTRIES)
    if isinstance(requested, str):
        codes = [requested]
    else:
        try:
            codes = list(requested)
        except TypeError:
            return dict(_DEFAULT_COUNTRIES)
    out: dict[str, str] = {}
    for raw in codes:
        code = str(raw).strip().upper()
        # Accept "EZ"/"EU" as euro-area proxy -> Germany is the largest member
        # series available; otherwise keep known majors and pass through unknowns
        # using the code as its own label so World Bank can still resolve it.
        if code in _DEFAULT_COUNTRIES:
            out[code] = _DEFAULT_COUNTRIES[code]
        elif code in ("EZ", "EU"):
            out["DE"] = _DEFAULT_COUNTRIES["DE"]
        elif code:
            out[code] = code
    return out or dict(_DEFAULT_COUNTRIES)


async def _fetch_worldbank_matrix(countries: dict[str, str]) -> list[dict[str, Any]]:
    """Fetch the four indicators for each country and assemble matrix rows.

    Uses the shared keyless HTTP client. World Bank lets us batch all
    countries in one call per indicator using a semicolon-joined country list,
    so we issue exactly len(_INDICATORS) requests regardless of country count.
    """
    from showme.providers._http import get_client

    client = await get_client()
    country_param = ";".join(countries.keys())

    async def _one_indicator(ind_code: str) -> dict[str, tuple[float, int]]:
        url = f"{_WB_BASE}/country/{country_param}/indicator/{ind_code}"
        resp = await client.get(
            url,
            params={"format": "json", "per_page": "2000", "mrnev": "1"},
        )
        resp.raise_for_status()
        payload = resp.json()
        return _parse_wb_series(payload)

    results = await asyncio.gather(*[_one_indicator(c) for c in _INDICATORS])

    # results[i] is {country_code: (value, year)} for indicator i.
    by_country: dict[str, dict[str, Any]] = {}
    for code, label in countries.items():
        by_country[code] = {"country": label, "country_code": code}

    for (ind_code, (out_key, _label, _unit)), series in zip(_INDICATORS.items(), results):
        for ccode, (value, year) in series.items():
            row = by_country.get(ccode)
            if row is None:
                continue
            row[out_key] = value
            row[f"{out_key}_year"] = year

    # Ensure every output key exists (null) so the UI table is rectangular.
    rows: list[dict[str, Any]] = []
    for code in countries:
        row = by_country[code]
        for _ind, (out_key, _label, _unit) in _INDICATORS.items():
            row.setdefault(out_key, None)
            row.setdefault(f"{out_key}_year", None)
        rows.append(row)
    return rows


def _parse_wb_series(payload: Any) -> dict[str, tuple[float, int]]:
    """Parse a World Bank v2 indicator response into {country_code: (value, year)}.

    Response shape is ``[metadata, [observations...]]``. With ``mrnev=1`` each
    country yields its single most-recent non-empty value, but we still guard
    for nulls and keep the latest year if multiple slip through.
    """
    out: dict[str, tuple[float, int]] = {}
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
        return out
    for obs in payload[1]:
        if not isinstance(obs, dict):
            continue
        value = obs.get("value")
        if value is None:
            continue
        country = obs.get("countryiso3code") or ""
        # World Bank returns iso3 in countryiso3code; the "country" sub-object's
        # "id" is iso2, which is what we requested. Prefer that, fall back to a
        # small iso3->iso2 map for the majors.
        country_obj = obs.get("country") or {}
        iso2 = country_obj.get("id") or _iso3_to_iso2(country)
        if not iso2:
            continue
        try:
            year = int(obs.get("date"))
        except (TypeError, ValueError):
            year = 0
        try:
            fval = round(float(value), 4)
        except (TypeError, ValueError):
            continue
        prev = out.get(iso2)
        if prev is None or year > prev[1]:
            out[iso2] = (fval, year)
    return out


# Minimal iso3->iso2 fallback for the majors we cover (World Bank "country.id"
# is normally iso2 already, so this is just a safety net).
_ISO3_ISO2 = {
    "USA": "US", "CHN": "CN", "JPN": "JP", "DEU": "DE", "GBR": "GB",
    "FRA": "FR", "IND": "IN", "BRA": "BR", "CAN": "CA", "ITA": "IT",
    "KOR": "KR", "AUS": "AU", "MEX": "MX", "TUR": "TR",
}


def _iso3_to_iso2(iso3: str) -> str | None:
    return _ISO3_ISO2.get((iso3 or "").upper())


def _composite_score(row: dict[str, Any]) -> float | None:
    """Macro-stress proxy: inflation + unemployment + 0.05·debt/GDP − growth."""
    inflation = row.get("inflation")
    unemployment = row.get("unemployment")
    debt = row.get("debt_gdp")
    growth = row.get("gdp_growth")
    if inflation is None and unemployment is None and debt is None and growth is None:
        return None
    parts: list[float] = []
    if inflation is not None:
        parts.append(float(inflation))
    if unemployment is not None:
        parts.append(float(unemployment))
    if debt is not None:
        parts.append(0.05 * float(debt))
    if growth is not None:
        parts.append(-float(growth))
    return round(sum(parts), 4) if parts else None


def _coerce_int(value: Any, default: int) -> int:
    try:
        out = int(value)
        return out if out > 0 else default
    except (TypeError, ValueError):
        return default


def _provider_unavailable(reason: str) -> FunctionResult:
    """Honest outage envelope — never fabricates numbers."""
    return FunctionResult(
        code="GMM",
        instrument=None,
        data={
            "status": "provider_unavailable",
            "rows": [],
            "cards": [{"key": "source", "label": "Source", "value": "World Bank"}],
            "methodology": (
                "GMM builds a cross-country macro matrix from the keyless World Bank open-data "
                "API (api.worldbank.org/v2): GDP growth, CPI inflation, unemployment, and "
                "debt-to-GDP per major economy. The live fetch failed on this run."
            ),
            "field_dictionary": {
                "gdp_growth": "Real GDP growth, annual % (World Bank NY.GDP.MKTP.KD.ZG).",
                "inflation": "Headline CPI inflation, annual % (FP.CPI.TOTL.ZG).",
                "unemployment": "Unemployment, % of labor force (SL.UEM.TOTL.ZS).",
                "debt_gdp": "Central government debt, % of GDP (GC.DOD.TOTL.GD.ZS).",
            },
            "source_mode": "worldbank",
            "next_actions": [
                "Retry — the World Bank API is keyless but occasionally rate-limits.",
                "Check network connectivity to api.worldbank.org.",
            ],
        },
        sources=["worldbank"],
        warnings=[f"World Bank fetch failed: {reason}"],
        metadata={"provider": "worldbank"},
    )
