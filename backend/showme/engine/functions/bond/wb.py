"""WB — World Bonds (sovereign yields heatmap)."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
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

# WB#3: the region buckets the seed exposes (all | dm | em). The pane buckets
# the same countries client-side; the backend must filter on the same sets.
_DEVELOPED_CODES = frozenset({"US", "DE", "JP", "GB", "CA", "FR", "IT", "ES", "AU"})
_EMERGING_CODES = frozenset({"TR", "BR", "MX", "ZA", "IN", "CN", "RU", "ID"})
_REGION_BUCKETS: dict[str, frozenset[str] | None] = {
    "all": None,
    "dm": _DEVELOPED_CODES,
    "em": _EMERGING_CODES,
}

# WB#1: a live row whose last FRED observation is older than this is flagged
# ``stale`` so it is never presented as a current reading.
_STALE_AFTER_DAYS = 120


def _observation_date(df: Any) -> str | None:
    """ISO date of the last FRED observation, or None when it is unreadable."""
    try:
        last = df.index[-1]
        return datetime.fromisoformat(str(last)[:10]).date().isoformat()
    except Exception:
        return None


def _days_since(observed_on: str, today: date) -> int:
    return (today - date.fromisoformat(observed_on)).days


def _world_bond_template() -> dict[str, float]:
    # Static reference levels (labelled sovereign_yield_model, NOT live).
    return {
        "US": 4.45, "DE": 2.58, "JP": 0.92, "GB": 4.18, "CA": 3.35,
        "FR": 3.02, "IT": 3.86, "ES": 3.24, "AU": 4.12,
        "TR": 28.50, "BR": 12.80, "MX": 9.10, "ZA": 10.20,
        "IN": 6.85, "CN": 2.05, "RU": 13.40, "ID": 6.65,
    }


def _rows_from_yields(
    values: dict[str, float],
    source_mode: str,
    tenor: str = "10Y",
    observed_on: dict[str, str] | None = None,
) -> dict[str, Any]:
    is_template = source_mode == "sovereign_yield_model"
    today = datetime.now(timezone.utc).date()
    observed_on = observed_on or {}
    rows: list[dict[str, Any]] = []
    for country, yield_pct in values.items():
        row: dict[str, Any] = {
            "country": country,
            "tenor": tenor,
            "yield": float(yield_pct),
            "source_mode": source_mode,
        }
        if is_template:
            row["as_of"] = _MODEL_TEMPLATE_VINTAGE
            row["reference_vintage"] = _MODEL_TEMPLATE_VINTAGE
        else:
            # WB#1: the FRED observation date, never the request date.
            obs = observed_on[country]
            row["as_of"] = obs
            row["days_since_observation"] = _days_since(obs, today)
            row["stale"] = row["days_since_observation"] > _STALE_AFTER_DAYS
        rows.append(row)
    rows.sort(key=lambda row: str(row["country"]))
    summary: dict[str, Any] = {"countries": len(rows), "tenor": tenor, "source_mode": source_mode}
    if is_template:
        summary["reference_vintage"] = _MODEL_TEMPLATE_VINTAGE
    else:
        obs_dates = sorted(observed_on[c] for c in values)
        if obs_dates:
            summary["latest_observation"] = obs_dates[-1]
            summary["oldest_observation"] = obs_dates[0]
        summary["stale_countries"] = sum(1 for row in rows if row.get("stale"))
        summary["stale_after_days"] = _STALE_AFTER_DAYS
    return {
        "rows": rows,
        "summary": summary,
        "methodology": "WB shows sovereign benchmark yields by country. The bundled default is a 10Y comparison; each row labels country, tenor, yield, source mode, and the FRED observation date (or model vintage for the template).",
        "field_dictionary": {
            "country": "ISO-style country code.",
            "tenor": "Benchmark maturity used for comparison.",
            "yield": "Annualized sovereign yield percentage.",
            "source_mode": "fred when live data is available, otherwise sovereign_yield_model.",
            "as_of": "Last FRED observation date for live rows (not the request date); the model vintage for template rows.",
            "stale": f"True when the last observation is more than {_STALE_AFTER_DAYS} days old.",
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
        region = str(params.get("region") or "all").strip().lower()
        if region not in _REGION_BUCKETS:
            # Data policy: an unknown input is an explicit input error, never a silent "all".
            return FunctionResult(
                code=self.code, instrument=None,
                data={"status": "input_error", "reason": f"Unknown region {region!r} (use all, dm or em).",
                      "next_actions": ["Pick region all, dm or em."], "rows": []},
                warnings=[f"unknown region {region!r}"],
            )
        bucket = _REGION_BUCKETS[region]
        selected = {
            country
            for country in _SOVEREIGN_FRED_IDS
            if (not country_filter or country in country_filter) and (bucket is None or country in bucket)
        }
        if not selected:
            return FunctionResult(
                code=self.code, instrument=None,
                data={"status": "empty", "reason": "No sovereign series match the requested region and countries.",
                      "next_actions": ["Widen the region or the country list."], "rows": []},
                warnings=["no sovereign series match region/countries"],
            )
        fred_ids = {country: _SOVEREIGN_FRED_IDS[country] for country in selected}
        # Default-polarity flip + keyless FRED CSV (survey S2 c#3, item 4):
        # WB pulls live sovereign yields by default — keyed adapter when
        # wired, otherwise the keyless fredgraph.csv endpoint — and serves
        # the labelled template only behind ``reference=true``.
        if _truthy(params.get("reference")):
            data = {country: value for country, value in _world_bond_template().items() if country in selected}
            return FunctionResult(code=self.code, instrument=None, data=_rows_from_yields(data, "sovereign_yield_model"),
                                  sources=["sovereign_yield_model"],
                                  warnings=["reference=true; serving the labelled sovereign yield template."])
        fred = fred_with_keyless_fallback(
            self.deps.fred, client=getattr(self, "_http_client", None)
        )
        out: dict[str, float] = {}
        provider_errors: list[str] = []
        timeout = float(params.get("fred_timeout", 8))
        observed_on: dict[str, str] = {}

        async def _one(country, fred_id):
            try:
                df = await asyncio.wait_for(fred.series(fred_id), timeout=timeout)
                obs = _observation_date(df)
                if obs is None:
                    return country, float("nan"), f"fred {country} ({fred_id}): observation date unavailable", None
                return country, float(df["value"].iloc[-1]), None, obs
            except Exception as exc:
                return country, float("nan"), f"fred {country} ({fred_id}): {exc}", None
        results = await asyncio.gather(*(
            _one(c, fid) for c, fid in fred_ids.items()
        ))
        for c, y, err, obs in results:
            out[c] = y
            if obs is not None:
                observed_on[c] = obs
            if y != y:
                # HNT-12 fix: failed/NaN countries are surfaced via
                # provider_errors + missing_countries instead of being
                # silently dropped from the heatmap.
                provider_errors.append(err or f"fred {c}: series returned no usable observation")
        missing_countries = sorted(c for c, y in out.items() if y != y)
        out = {c: y for c, y in out.items() if y == y}
        if not out:
            out = {country: value for country, value in _world_bond_template().items() if country in selected}
            return FunctionResult(code=self.code, instrument=None, data=_rows_from_yields(out, "sovereign_yield_model"), sources=["sovereign_yield_model"],
                                  warnings=["Live sovereign yields unavailable (keyed FRED adapter or keyless CSV); showing the labelled reference template.",
                                            *provider_errors])
        data = _rows_from_yields(out, "fred", observed_on=observed_on)
        if missing_countries:
            # HNT-12 fix: partial coverage is visible in the payload, not
            # a silently shrunken heatmap.
            data["missing_countries"] = missing_countries
            data["summary"]["missing_countries"] = len(missing_countries)
            data["field_dictionary"]["missing_countries"] = (
                "Requested countries whose live FRED series failed or returned no usable observation."
            )
        metadata: dict[str, Any] = {"live": True, "data_mode": "live_official"}
        if provider_errors:
            metadata["provider_errors"] = provider_errors
        return FunctionResult(code=self.code, instrument=None, data=data, sources=["fred"],
                              metadata=metadata)
