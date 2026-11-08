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
macro composite carries the row.  When no requested sovereign can be
priced at all, no rows are returned: ``provider_unavailable`` on a
network outage, ``empty`` when the World Bank answered with no data.
"""

from __future__ import annotations

import asyncio
import math
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

# Wall-clock budget for the World Bank fan-out (Wide-12 = 48 requests). It sits
# under the 14 s function timeout so a slow country becomes an explicit
# unavailable row instead of failing the whole call.
_CALL_BUDGET_S = 9.0

# Upper bound for the recovery input (matches the seed's max); R near 1 blows up the Hull PD.
_MAX_RECOVERY = 0.95


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


def _is_partial(row: dict[str, Any]) -> bool:
    """True when a scored row used fewer macro legs than the full composite."""
    present = row.get("legs_present")
    total = row.get("legs_total")
    return isinstance(present, int) and isinstance(total, int) and present < total


def _year_sort_key(text: str) -> tuple[int, str]:
    """Sort World Bank date strings (usually a year) oldest first."""
    try:
        return (int(text[:4]), text)
    except (TypeError, ValueError):
        return (9999, text)


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

        leg_dates: dict[str, str] = {}
        for key, indicator, val, date, err in results:
            if err:
                notes.append(f"{indicator} fetch failed for {iso3}: {err}")
            out[key] = val
            if date:
                leg_dates[key] = date
            if val is None and not any(
                n.startswith(indicator) for n in notes
            ):
                notes.append(f"{indicator} unavailable for {iso3}")
        # The row's as_of is the OLDEST leg date: a mixed-age row must not be
        # labelled with whichever leg happened to answer first.
        out["as_of_by_leg"] = leg_dates
        if leg_dates:
            out["as_of"] = min(leg_dates.values(), key=_year_sort_key)
        return out, notes

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        raw_countries = params.get("countries") or params.get("country") or ["TR", "US", "DE", "JP"]
        if isinstance(raw_countries, str):
            countries = [item.strip().upper() for item in raw_countries.split(",") if item.strip()]
        else:
            countries = [str(item).strip().upper() for item in raw_countries if str(item).strip()]
        countries = countries[:12] or ["TR"]
        recovery_raw = params.get("recovery")
        if recovery_raw is None:
            recovery_raw = 0.4
        try:
            recovery = float(recovery_raw)
        except (TypeError, ValueError):
            recovery = float("nan")
        # Recovery is a probability bounded by the seed's max (0.95). Outside it the
        # Hull denominator max(0.01, 1 - R) produces PD above 100%, so reject it.
        if not math.isfinite(recovery) or not 0.0 <= recovery <= _MAX_RECOVERY:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "input_error",
                    "reason": (
                        f"recovery must be a number between 0 and {_MAX_RECOVERY}; "
                        f"got {recovery_raw!r}. No spread or PD was computed."
                    ),
                    "rows": [],
                    "summary": {
                        "countries": 0,
                        "recovery": None,
                        "formula": "PD ~= spread / (1 - recovery)",
                    },
                    "next_actions": [
                        f"Pass a recovery rate between 0 and {_MAX_RECOVERY} (Hull default 0.4).",
                    ],
                },
                sources=[],
                warnings=[f"recovery out of range: {recovery_raw!r}"],
                metadata={"live": False, "fallback": False},
            )

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

        tasks = {c: asyncio.ensure_future(_fetch_one_country(c)) for c in countries}
        await asyncio.wait(tasks.values(), timeout=_CALL_BUDGET_S)
        results = []
        timed_out: list[asyncio.Future] = []
        for c in countries:
            task = tasks[c]
            if task.done():
                results.append(task.result())
            else:
                task.cancel()
                timed_out.append(task)
                results.append((c, {}, [], False, _WBUnavailable(
                    f"timed out: no answer within the {_CALL_BUDGET_S:g}s call budget"
                ), None, None))
        if timed_out:
            await asyncio.gather(*timed_out, return_exceptions=True)

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
                # No live macro legs: there is no score to map onto a spread, so
                # none is invented. The row stays unranked with null spread/PD.
                proxy_spread = None
                source_mode = "unavailable"
                row_note = (
                    f"no live World Bank macro for {country}; no risk score, spread or PD "
                    "computed (unranked)"
                )

            # Refine with a real yield differential when FRED is available.
            fid = sovereign_fred_ids.get(country)
            if self.deps.fred and ust_y is not None and fid:
                if country == "US":
                    # The US is the UST benchmark: a UST-minus-UST differential is zero by
                    # construction, not a credit reading. Never pin a constant spread here;
                    # keep whatever the live macro composite produced (null when unscored).
                    if risk_score is not None:
                        row_note = "; ".join(
                            [
                                *macro_notes,
                                "US is the UST benchmark; no FRED self-spread applied",
                            ]
                        )
                elif target_y is not None:
                    proxy_spread = round(target_y - ust_y, 4)
                    source_mode = "fred+worldbank" if risk_score is not None else "fred"
                    if risk_score is None:
                        # The spread/PD now come from a real FRED differential, but
                        # there is still no macro score: say exactly that.
                        row_note = (
                            f"no live World Bank macro for {country}; no risk score computed "
                            "(unranked); spread and PD come from the FRED 10Y differential"
                        )

            if proxy_spread is not None:
                pd_1y: float | None = proxy_spread / 100 / max(0.01, (1 - recovery))
                pd_1y_pct: float | None = pd_1y * 100
            else:
                pd_1y = None
                pd_1y_pct = None
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
                    "pd_1y_pct": pd_1y_pct,
                    "recovery": recovery,
                    "source_mode": source_mode,
                    "as_of": macro.get("as_of"),
                    "as_of_by_leg": macro.get("as_of_by_leg", {}),
                    "legs_present": len(present),
                    "legs_total": len(legs),
                    "note": row_note,
                }
            )

        if wb_success:
            sources.append("worldbank")
        if ust_y is not None and any(r["source_mode"].startswith("fred") for r in rows):
            sources.append("fred")

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

        # No requested sovereign was priced at all (no live World Bank macro and
        # no FRED spread): there is no value to report, so return an explicit
        # empty or provider_unavailable state rather than an 'ok' result.
        if wb_success == 0 and not any(r["proxy_spread_pct"] is not None for r in rows):
            unpriced = ", ".join(r["country"] for r in rows)
            outage = wb_network_failures > 0
            if outage:
                reason = (
                    f"World Bank Open Data was unreachable for {unpriced} and no FRED 10Y spread "
                    "priced them; no risk score, spread or PD was computed."
                )
            else:
                reason = (
                    f"World Bank returned no live macro observations for {unpriced} and no FRED "
                    "10Y spread priced them; no risk score, spread or PD was computed."
                )
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable" if outage else "empty",
                    "reason": reason,
                    "rows": [],
                    "summary": {
                        "countries": 0,
                        "recovery": recovery,
                        "formula": "PD ~= spread / (1 - recovery)",
                    },
                    "methodology": (
                        "SRSK ranks sovereigns by a 0-100 composite macro risk score built from "
                        "keyless World Bank fundamentals. No requested sovereign had a live macro "
                        "score or a FRED spread, so no rank, spread or PD is reported."
                    ),
                    "field_dictionary": self._field_dictionary(),
                    "next_actions": [
                        (
                            "Retry once api.worldbank.org is reachable."
                            if outage
                            else "Check the requested country codes (ISO-2, for example TR or DE)."
                        ),
                        "Optionally configure a FRED API key to add real 10Y yield differentials.",
                    ],
                },
                sources=[],
                warnings=warnings or [f"worldbank: no live observations for {unpriced}"],
                metadata={
                    "live": False,
                    "fallback": False,
                    "wb_network_failures": wb_network_failures,
                },
            )

        # Rank: highest risk first for the bar ladder / cards.
        # Rows without a live risk score stay unranked and never lead the cards,
        # even when a FRED differential gives them a spread and PD.
        # The card is "Highest PD": pick the largest PD among scored rows, not the
        # largest composite score (FRED spreads can reorder the two).
        # Partial-coverage rows (fewer than all legs) are averaged over a different
        # set of factors, so they never lead the card over a full-coverage country.
        scored = [
            r for r in rows
            if r.get("risk_score") is not None
            and r.get("pd_1y_pct") is not None
            and not _is_partial(r)
        ]
        highest = max(scored, key=lambda r: r["pd_1y_pct"]) if scored else None

        # data_mode names what actually priced the rows: live World Bank macro,
        # or (with no macro score at all) live FRED 10Y differentials only.
        data_mode = "live_official" if wb_success else "live"
        # Card as-of is the stalest row date, so the KPI never overstates freshness.
        row_dates = [r["as_of"] for r in rows if r.get("as_of")]
        as_of = min(row_dates, key=_year_sort_key) if row_dates else None
        cards = {
            "highest_pd_country": highest["country"] if highest else None,
            "highest_pd": round(highest["pd_1y_pct"], 4) if highest else None,
            "recovery": recovery,
            "data_mode": data_mode,
            "as_of": as_of,
        }

        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": "ok",
                "rows": rows,
                "cards": cards,
                "data_mode": data_mode,
                "summary": {
                    "countries": len(rows),
                    "recovery": recovery,
                    "formula": "PD ~= spread / (1 - recovery)",
                    "worldbank_countries": wb_success,
                    "unscored_countries": sum(1 for r in rows if r["risk_score"] is None),
                    "partial_coverage_countries": sum(1 for r in rows if _is_partial(r)),
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
                    "(the US is the benchmark and gets no FRED spread). The Hull approximation PD_1Y ~= spread / (1 - recovery) then "
                    "yields a one-year default-probability proxy. A country with no live macro data is kept "
                    "unranked with null spread and PD (source_mode 'unavailable'); no value is substituted. "
                    "If no requested sovereign can be priced at all, no rows are returned and the status is "
                    "provider_unavailable (World Bank unreachable) or empty (no observations)."
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
            "pd_1y_pct": "One-year default-probability proxy in percent (linear Hull approximation spread/(1-R)). It is not capped at 100; above 100 it is not a probability and only shows how large the spread is relative to the loss given default.",
            "recovery": "Assumed recovery rate in the Hull reduced-form approximation.",
            "source_mode": "'worldbank' for the macro composite, 'fred'/'fred+worldbank' when a real yield differential refines it, 'unavailable' when no live macro data exists (score, spread and PD are null, row unranked).",
            "as_of": "Observation year of the OLDEST World Bank leg used for the row (a mixed-age row is labelled with its stalest leg).",
            "legs_present": "How many of the four macro legs (debt, reserves, current account, inflation) fed this row's composite.",
            "legs_total": "Number of macro legs in the composite (always 4).",
            "as_of_by_leg": "Observation year of the latest World Bank point for each macro leg (debt_to_gdp, reserves_months, current_account_gdp, inflation_pct).",
            "note": "Per-row caveat: missing macro legs, US benchmark note, or unscored (unavailable) row.",
        }
