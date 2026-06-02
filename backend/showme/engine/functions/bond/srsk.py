"""SRSK — Sovereign Risk (keyless macro composite + yield-proxy PD).

Historically SRSK depended on FRED (key-gated) long-rate series and
returned ``provider_unavailable`` whenever the key was absent, so the
panel showed a lifeless gated state.  This implementation makes the
DEFAULT path return real, live data from **keyless** sources:

* World Bank Open Data (no key) supplies the macro fundamentals that
  actually drive sovereign credit risk — central-government debt/GDP
  (``GC.DOD.TOTL.GD.ZS``), total reserves in months of imports
  (``FI.RES.TOTL.MO``), current-account balance %GDP
  (``BN.CAB.XOKA.GD.ZS``) and consumer inflation
  (``FP.CPI.TOTL.ZG``).
* A composite 0–100 ``risk_score`` is built from those z-scored macro
  legs, and a yield-style CDS-proxy spread is derived from the score so
  the legacy ``PD ≈ spread / (1 − R)`` Hull identity still produces a
  ranked, per-country probability of default.

FRED, when a key is configured, is still consulted to refine the proxy
spread with a real ``country 10Y − UST 10Y`` reading; otherwise the
macro composite carries the row.  A genuine network outage (World Bank
unreachable AND no FRED) is the only path that yields
``provider_unavailable``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument

# ---------------------------------------------------------------------------
# ISO-2 → ISO-3 for the curated sovereign universe (World Bank uses ISO-3
# alpha codes in its REST path).  Falls back to the raw token when unknown.
# ---------------------------------------------------------------------------
_ISO2_TO_ISO3: dict[str, str] = {
    "US": "USA", "DE": "DEU", "JP": "JPN", "GB": "GBR", "FR": "FRA",
    "IT": "ITA", "ES": "ESP", "AU": "AUS", "CA": "CAN", "TR": "TUR",
    "BR": "BRA", "MX": "MEX", "ZA": "ZAF", "IN": "IND", "CN": "CHN",
    "RU": "RUS", "ID": "IDN", "GR": "GRC", "PT": "PRT", "AR": "ARG",
    "KR": "KOR", "CH": "CHE", "NL": "NLD", "SE": "SWE", "PL": "POL",
}

# World Bank indicator codes for the macro legs that drive sovereign risk.
_WB_INDICATORS: dict[str, str] = {
    "debt_to_gdp": "GC.DOD.TOTL.GD.ZS",     # central govt debt, % of GDP
    "reserves_months": "FI.RES.TOTL.MO",    # reserves, months of imports
    "current_account_gdp": "BN.CAB.XOKA.GD.ZS",  # current account, % of GDP
    "inflation_pct": "FP.CPI.TOTL.ZG",      # CPI inflation, annual %
}

_WB_BASE = "https://api.worldbank.org/v2"


def _latest_wb_value(payload: Any) -> tuple[float | None, str | None]:
    """Pull the most recent non-null observation from a World Bank reply.

    The v2 REST shape is ``[meta, [obs, obs, ...]]`` where each obs has
    ``value`` and ``date`` keys, newest first.
    """
    try:
        rows = payload[1]
    except (TypeError, IndexError, KeyError):
        return None, None
    if not isinstance(rows, list):
        return None, None
    for obs in rows:
        if not isinstance(obs, dict):
            continue
        val = obs.get("value")
        if val is not None:
            try:
                return float(val), str(obs.get("date") or "")
            except (TypeError, ValueError):
                continue
    return None, None


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _leg_score(value: float | None, *, low: float, high: float, invert: bool) -> float | None:
    """Map a raw macro value onto a 0–100 risk leg.

    ``low``/``high`` bound the "best" → "worst" raw range.  When
    ``invert`` is False a higher raw value means more risk (e.g.
    debt/GDP, inflation); when True a higher raw value means LESS risk
    (e.g. reserves, current-account surplus), so the leg is flipped.
    """
    if value is None:
        return None
    span = high - low
    if span == 0:
        return 50.0
    frac = (value - low) / span
    if invert:
        frac = 1.0 - frac
    return round(_clamp(frac, 0.0, 1.0) * 100.0, 2)


class _WBUnavailable(Exception):
    """Raised when the keyless World Bank fetch fails for a country."""


@FunctionRegistry.register
class SRSKFunction(BaseFunction):
    code = "SRSK"
    name = "Sovereign Risk"
    category = "bond"

    # -- keyless World Bank fetch -------------------------------------------
    async def _wb_fetch_indicator(self, iso3: str, indicator: str) -> tuple[float | None, str | None]:
        """Fetch the latest value for one indicator via the shared keyless client.

        Tries an injected adapter first (``self.deps.worldbank``) and
        falls back to a direct HTTP call.  Raises ``_WBUnavailable`` only
        on a hard network failure so the caller can decide per-country.
        """
        url = f"{_WB_BASE}/country/{iso3}/indicator/{indicator}"
        params = {"format": "json", "per_page": "20"}

        adapter = getattr(self.deps, "worldbank", None)
        if adapter is not None:
            for meth in ("indicator", "series", "get", "fetch"):
                fn = getattr(adapter, meth, None)
                if fn is None:
                    continue
                try:
                    res = fn(iso3, indicator)
                    if asyncio.iscoroutine(res):
                        res = await res
                    val, date = _latest_wb_value(res)
                    if val is not None:
                        return val, date
                except Exception:  # pragma: no cover - adapter shape varies
                    break

        # Direct keyless HTTP fetch.  ``get_client`` is an async factory in
        # production (returns a shared httpx.AsyncClient) but unit tests inject
        # a synchronous stub — handle both shapes, and likewise await the
        # response/``.json()`` only when they are awaitable.
        try:
            from showme.providers._http import get_client  # local import keeps cold-start cheap

            client = get_client()
            if asyncio.iscoroutine(client):
                client = await client
            resp = client.get(url, params=params, timeout=10.0)
            if asyncio.iscoroutine(resp):
                resp = await resp
            getter = getattr(resp, "json", None)
            payload = getter() if getter is not None else resp
            if asyncio.iscoroutine(payload):
                payload = await payload
            return _latest_wb_value(payload)
        except Exception as exc:  # network / parse failure
            raise _WBUnavailable(str(exc)) from exc

    async def _country_macro(self, iso3: str) -> tuple[dict[str, Any], list[str]]:
        """Fetch every macro leg for a country with per-leg tolerance.

        A single failed/empty indicator must NOT take down the whole
        country: a per-leg network/parse failure is caught, the leg is
        recorded as ``None`` with a note, and the remaining legs are still
        fetched.  ``execute()`` only treats a country as unavailable when
        *every* leg failed (no real value at all).
        """
        out: dict[str, Any] = {}
        notes: list[str] = []
        keys_and_indicators = list(_WB_INDICATORS.items())

        async def _fetch_one(key: str, indicator: str):
            try:
                val, date = await self._wb_fetch_indicator(iso3, indicator)
                return key, indicator, val, date, None
            except _WBUnavailable as exc:
                return key, indicator, None, None, str(exc)

        results = await asyncio.gather(*(
            _fetch_one(k, ind) for k, ind in keys_and_indicators
        ))

        for key, indicator, val, date, err in results:
            if err:
                notes.append(f"{indicator} fetch failed for {iso3}: {err}")
            out[key] = val
            if date and "as_of" not in out:
                out["as_of"] = date
            if val is None and not any(
                n.startswith(indicator) for n in notes
            ):
                notes.append(f"{indicator} unavailable for {iso3}")
        return out, notes

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        raw_countries = params.get("countries") or params.get("country") or ["TR", "US", "DE", "JP"]
        if isinstance(raw_countries, str):
            countries = [item.strip().upper() for item in raw_countries.split(",") if item.strip()]
        else:
            countries = [str(item).strip().upper() for item in raw_countries if str(item).strip()]
        countries = countries[:12] or ["TR"]
        recovery = float(params.get("recovery", 0.4))
        fallback_spread = float(params.get("proxy_spread_pct", 3.25))

        warnings: list[str] = []
        rows: list[dict[str, Any]] = []

        # Optional FRED refinement of the proxy spread (only if a key is set).
        ust_y: float | None = None
        sovereign_fred_ids: dict[str, str] = {}
        if self.deps.fred:
            try:
                ust = await self.deps.fred.series("DGS10")
                ust_y = float(ust["value"].iloc[-1])
            except Exception as exc:  # pragma: no cover - key-gated
                warnings.append(f"fred DGS10: {exc}")
            try:
                from showme.engine.functions.bond.wb import _SOVEREIGN_FRED_IDS  # type: ignore

                sovereign_fred_ids = dict(_SOVEREIGN_FRED_IDS)
            except Exception:  # pragma: no cover - sibling import optional
                sovereign_fred_ids = {}

        wb_network_failures = 0
        wb_success = 0
        sources: list[str] = []

        async def _fetch_one_country(country: str):
            iso3 = _ISO2_TO_ISO3.get(country, country)
            macro: dict[str, Any] = {}
            macro_notes: list[str] = []
            wb_ok = False
            wb_err = None
            try:
                macro, macro_notes = await self._country_macro(iso3)
                wb_ok = any(
                    macro.get(k) is not None for k in _WB_INDICATORS
                )
            except _WBUnavailable as exc:
                wb_err = exc

            target_y = None
            fred_err = None
            fid = sovereign_fred_ids.get(country)
            if self.deps.fred and ust_y is not None and fid and country != "US":
                try:
                    target = await self.deps.fred.series(fid)
                    target_y = float(target["value"].iloc[-1])
                except Exception as exc:
                    fred_err = exc
            return country, macro, macro_notes, wb_ok, wb_err, target_y, fred_err

        results = await asyncio.gather(*(_fetch_one_country(c) for c in countries))

        for country, macro, macro_notes, wb_ok, wb_err, target_y, fred_err in results:
            if wb_err:
                wb_network_failures += 1
                warnings.append(f"worldbank {country}: {wb_err}")
            elif wb_ok:
                wb_success += 1

            if fred_err:
                warnings.append(f"{country}: {fred_err}")

            # Build the 0-100 composite risk score from available legs.
            legs: dict[str, float | None] = {
                "debt_leg": _leg_score(macro.get("debt_to_gdp"), low=20.0, high=160.0, invert=False),
                "reserves_leg": _leg_score(macro.get("reserves_months"), low=1.0, high=12.0, invert=True),
                "cab_leg": _leg_score(macro.get("current_account_gdp"), low=-10.0, high=8.0, invert=True),
                "inflation_leg": _leg_score(macro.get("inflation_pct"), low=1.0, high=30.0, invert=False),
            }
            present = [v for v in legs.values() if v is not None]
            risk_score: float | None = round(sum(present) / len(present), 2) if present else None

            # Derive a CDS-style proxy spread (percentage points) from the
            # composite score: 0 score → ~0.1%, 100 score → ~12%.
            if risk_score is not None:
                proxy_spread = round(0.1 + (risk_score / 100.0) * 11.9, 4)
                source_mode = "worldbank"
                row_note: str | None = "; ".join(macro_notes) if macro_notes else None
            else:
                proxy_spread = fallback_spread
                source_mode = "sovereign_risk_model"
                row_note = f"no live World Bank macro for {country}; using fallback proxy_spread_pct={fallback_spread}"

            # Refine with a real yield differential when FRED is available.
            fid = sovereign_fred_ids.get(country)
            if self.deps.fred and ust_y is not None and fid:
                if country == "US":
                    proxy_spread = 0.0
                    source_mode = "fred"
                    row_note = (
                        "US sovereign self-spread is zero; PD shown for completeness only "
                        "and is not a credit-risk reading"
                    )
                elif target_y is not None:
                    proxy_spread = round(target_y - ust_y, 4)
                    source_mode = "fred+worldbank" if risk_score is not None else "fred"

            pd_1y = proxy_spread / 100 / max(0.01, (1 - recovery))
            rows.append(
                {
                    "country": country,
                    "debt_to_gdp": macro.get("debt_to_gdp"),
                    "reserves_months": macro.get("reserves_months"),
                    "current_account_gdp": macro.get("current_account_gdp"),
                    "inflation_pct": macro.get("inflation_pct"),
                    "risk_score": risk_score,
                    "proxy_spread_pct": proxy_spread,
                    "pd_1y_proxy": pd_1y,
                    "pd_1y_pct": pd_1y * 100,
                    "recovery": recovery,
                    "source_mode": source_mode,
                    "as_of": macro.get("as_of"),
                    "note": row_note,
                }
            )

        if wb_success:
            sources.append("worldbank")
        if ust_y is not None and any(r["source_mode"].startswith("fred") for r in rows):
            sources.append("fred")
        if not sources:
            sources.append("sovereign_risk_model")

        # Honest outage only when NOTHING real came back.
        if wb_success == 0 and ust_y is None:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": (
                        "World Bank Open Data unreachable and no FRED key configured; "
                        "SRSK cannot compute live sovereign macro risk."
                    ),
                    "rows": [],
                    "summary": {
                        "countries": 0,
                        "recovery": recovery,
                        "formula": "PD ~= spread / (1 - recovery)",
                    },
                    "methodology": (
                        "SRSK ranks sovereigns by a 0-100 composite macro risk score built from "
                        "keyless World Bank fundamentals (debt/GDP, reserves in months of imports, "
                        "current-account %GDP, CPI inflation), then converts that score into a "
                        "CDS-style proxy spread and a Hull PD ~= spread / (1 - recovery)."
                    ),
                    "field_dictionary": self._field_dictionary(),
                    "next_actions": [
                        "Retry once World Bank api.worldbank.org is reachable.",
                        "Optionally configure a FRED API key to add real 10Y yield differentials.",
                    ],
                },
                sources=["worldbank"],
                warnings=warnings or ["worldbank: no live observations returned"],
                metadata={
                    "live": False,
                    "fallback": False,
                    "wb_network_failures": wb_network_failures,
                },
            )

        # Rank: highest risk first for the bar ladder / cards.
        scored = [r for r in rows if r.get("risk_score") is not None]
        highest = max(scored, key=lambda r: r["risk_score"]) if scored else (
            max(rows, key=lambda r: r["pd_1y_pct"]) if rows else None
        )

        as_of = next((r.get("as_of") for r in rows if r.get("as_of")), None)
        cards = {
            "highest_pd_country": highest["country"] if highest else None,
            "highest_pd": round(highest["pd_1y_pct"], 4) if highest else None,
            "recovery": recovery,
            "data_mode": "live_official" if wb_success else "modeled",
            "as_of": as_of,
        }

        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": "ok",
                "rows": rows,
                "cards": cards,
                "data_mode": "live_official" if wb_success else "modeled",
                "summary": {
                    "countries": len(rows),
                    "recovery": recovery,
                    "formula": "PD ~= spread / (1 - recovery)",
                    "worldbank_countries": wb_success,
                    "fallback_countries": sum(1 for r in rows if r["source_mode"] == "sovereign_risk_model"),
                    "highest_risk_country": highest["country"] if highest else None,
                },
                "methodology": (
                    "SRSK ranks sovereigns by a 0-100 composite macro risk score built from keyless "
                    "World Bank Open Data fundamentals: central-government debt/GDP "
                    "(GC.DOD.TOTL.GD.ZS), reserves in months of imports (FI.RES.TOTL.MO), "
                    "current-account balance %GDP (BN.CAB.XOKA.GD.ZS) and CPI inflation "
                    "(FP.CPI.TOTL.ZG). Each leg is mapped onto a 0-100 sub-score (debt and inflation "
                    "are risk-positive; reserves and current-account surplus are risk-negative) and "
                    "averaged over the legs that returned data. The composite is converted into a "
                    "CDS-style proxy spread (0 score -> ~0.1%, 100 -> ~12%); when a FRED key is "
                    "present the spread is refined to a real country-10Y minus UST-10Y differential "
                    "(US pinned to zero). The Hull approximation PD_1Y ~= spread / (1 - recovery) then "
                    "yields a one-year default-probability proxy. Only a full World Bank outage with no "
                    "FRED key returns provider_unavailable."
                ),
                "field_dictionary": self._field_dictionary(),
            },
            sources=sources,
            warnings=warnings,
            metadata={
                "live": bool(wb_success),
                "ust_10y_pct": ust_y,
                "worldbank_countries": wb_success,
                "wb_network_failures": wb_network_failures,
            },
        )

    @staticmethod
    def _field_dictionary() -> dict[str, str]:
        return {
            "country": "ISO-2 sovereign issuer code.",
            "debt_to_gdp": "Central government debt as a percent of GDP (World Bank GC.DOD.TOTL.GD.ZS).",
            "reserves_months": "Total reserves expressed in months of imports (World Bank FI.RES.TOTL.MO).",
            "current_account_gdp": "Current-account balance as a percent of GDP (World Bank BN.CAB.XOKA.GD.ZS).",
            "inflation_pct": "Consumer price inflation, annual percent (World Bank FP.CPI.TOTL.ZG).",
            "risk_score": "Composite 0-100 sovereign macro risk score (higher = riskier).",
            "proxy_spread_pct": "CDS-style proxy spread in percentage points derived from the risk score (or a real FRED yield differential when available).",
            "pd_1y_proxy": "One-year default-probability proxy as a decimal.",
            "pd_1y_pct": "One-year default-probability proxy in percent.",
            "recovery": "Assumed recovery rate in the Hull reduced-form approximation.",
            "source_mode": "'worldbank' for the macro composite, 'fred'/'fred+worldbank' when a real yield differential refines it, 'sovereign_risk_model' for the fallback spread.",
            "as_of": "Observation year of the latest World Bank data point used.",
            "note": "Per-row caveat: missing macro legs, US self-spread, or fallback applied.",
        }
