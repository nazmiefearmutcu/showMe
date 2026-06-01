"""ECFC — Economic Forecasts.

Real, keyless economic forecasts sourced from the IMF World Economic
Outlook (WEO) via the public IMF DataMapper API
(``https://www.imf.org/external/datamapper/api/v1/{indicator}/{country}``).
The DataMapper returns the WEO vintage's full historical + forward
projection series keyed by the same indicator codes the manifest seed
exposes (NGDP_RPCH, PCPIPCH, LUR, GGXCNL_NGDP, GGXWDG_NGDP, BCA_NGDPD,
NGDPD), so every (indicator, year) cell is a genuine per-country IMF
forecast — not a hardcoded constant. No API key is required.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument

_DATAMAPPER_BASE = "https://www.imf.org/external/datamapper/api/v1"

# IMF WEO indicator code -> (human label, display unit)
_INDICATORS: dict[str, tuple[str, str]] = {
    "NGDP_RPCH": ("Real GDP growth", "% y/y"),
    "PCPIPCH": ("Inflation", "% y/y"),
    "LUR": ("Unemployment rate", "%"),
    "GGXCNL_NGDP": ("Fiscal balance", "% GDP"),
    "GGXWDG_NGDP": ("Government debt", "% GDP"),
    "BCA_NGDPD": ("Current account", "% GDP"),
    "NGDPD": ("GDP", "USD bn"),
}

_DEFAULT_INDICATORS = ["NGDP_RPCH", "PCPIPCH", "LUR", "GGXCNL_NGDP", "GGXWDG_NGDP"]

# IMF DataMapper keys every series by ISO 3166-1 *alpha-3* (USA, GBR, JPN, ...)
# plus its own group codes (EURO, WEOWORLD, ...). The manifest/UI often pass
# the alpha-2 form (US, GB, JP), and ``/{indicator}/US`` 200s with the WHOLE
# all-country dataset — so a naive ``.get("US")`` silently misses ("USA" is
# the real key) and the function looked dead. Normalise alpha-2 -> alpha-3 for
# the major economies; anything already alpha-3 / an IMF group code passes
# through untouched.
_ISO2_TO_ISO3: dict[str, str] = {
    "US": "USA", "GB": "GBR", "UK": "GBR", "JP": "JPN", "DE": "DEU", "FR": "FRA",
    "IT": "ITA", "ES": "ESP", "CA": "CAN", "AU": "AUS", "CN": "CHN", "IN": "IND",
    "BR": "BRA", "RU": "RUS", "KR": "KOR", "MX": "MEX", "TR": "TUR", "ID": "IDN",
    "SA": "SAU", "CH": "CHE", "NL": "NLD", "SE": "SWE", "PL": "POL", "BE": "BEL",
    "AT": "AUT", "NO": "NOR", "IE": "IRL", "DK": "DNK", "FI": "FIN", "PT": "PRT",
    "GR": "GRC", "CZ": "CZE", "HU": "HUN", "NZ": "NZL", "ZA": "ZAF", "AR": "ARG",
    "CL": "CHL", "CO": "COL", "PE": "PER", "TH": "THA", "MY": "MYS", "PH": "PHL",
    "VN": "VNM", "SG": "SGP", "HK": "HKG", "TW": "TWN", "IL": "ISR", "AE": "ARE",
    "EG": "EGY", "NG": "NGA", "PK": "PAK", "BD": "BGD", "UA": "UKR", "RO": "ROU",
}


def _normalize_country(code: str) -> str:
    """Alpha-2 -> alpha-3 where known; pass IMF group / alpha-3 codes through."""
    c = (code or "").strip().upper()
    return _ISO2_TO_ISO3.get(c, c)


def _provider_unavailable(country: str, indicators: list[str], reason: str) -> dict[str, Any]:
    """Honest empty envelope for a genuine network/upstream failure."""
    return {
        "country": country,
        "rows": [],
        "series": [],
        "cards": [],
        "status": "provider_unavailable",
        "data_state": "provider_unavailable",
        "vintage": "imf_weo",
        "source_mode": "provider_unavailable",
        "methodology": (
            "ECFC pulls live IMF World Economic Outlook forecasts from the keyless "
            "IMF DataMapper API. The upstream request failed for this run "
            f"({reason}), so the function returns an explicit provider_unavailable "
            "envelope rather than fabricating forecast values."
        ),
        "next_actions": [
            "Retry ECFC — the IMF DataMapper endpoint may be momentarily unreachable.",
            "Confirm the country code is a valid ISO 3166-1 alpha-3 / IMF group code.",
        ],
        "requested_indicators": indicators,
        "field_dictionary": _FIELD_DICT,
    }


_FIELD_DICT: dict[str, str] = {
    "country": "ISO 3166-1 alpha-3 (or IMF group) code echoed back.",
    "indicator": "IMF WEO indicator code.",
    "metric": "Human-readable macro variable.",
    "year": "Forecast calendar year (integer).",
    "forecast_value": "IMF WEO forecast value in the displayed unit.",
    "unit": "Display unit (% YoY, % of GDP, USD bn, ...).",
    "vintage": "Forecast vintage label (imf_weo).",
    "source_mode": "Provider layer used for the row (imf_weo).",
}


def _indicator_label(indicator: str) -> tuple[str, str]:
    return _INDICATORS.get(indicator, (indicator, "value"))


@FunctionRegistry.register
class ECFCFunction(BaseFunction):
    code = "ECFC"
    name = "Economic Forecasts"
    category = "macro"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        country = _normalize_country(str(params.get("country") or "USA"))
        indicators = params.get("indicators") or list(_DEFAULT_INDICATORS)
        if isinstance(indicators, str):
            indicators = [s.strip() for s in indicators.split(",") if s.strip()]
        indicators = [str(i).strip() for i in indicators if str(i).strip()]
        if not indicators:
            indicators = list(_DEFAULT_INDICATORS)
        try:
            years = int(params.get("years") or 5)
        except (TypeError, ValueError):
            years = 5
        years = max(1, min(years, 6))
        # IMF's Akamai edge is slow to first-byte for the full WEO series
        # (~120 KB/indicator) and the shared client's own read timeout is 20s,
        # so a 12s cap was firing as a ReadTimeout before the payload landed.
        # Give it a realistic ceiling (default 25s, hard-capped at 40s).
        timeout = max(5.0, min(float(params.get("timeout", 25)), 40.0))

        client = await self._client()

        async def _fetch(ind: str) -> tuple[str, dict[str, Any] | None, str | None]:
            url = f"{_DATAMAPPER_BASE}/{ind}/{country}"
            try:
                # IMF DataMapper sits behind an Akamai WAF that 403s *browser-
                # like* User-Agents (anything matching Mozilla/5.0..., and even
                # the shared client's spoofed "...showMe" UA), while it serves a
                # plain ``curl/...`` UA with a 200 + full JSON. Empirically
                # verified 2026-06-01: chrome/mozilla/showMe-research all 403,
                # ``curl/8.4.0`` 200s. Override the UA per-request (httpx request
                # headers win over client defaults). A minimal mock client may
                # expose ``get(url)`` without a ``headers`` kwarg — fall back to
                # the bare call in that case.
                # Pass ``timeout`` through to httpx too — the shared client's
                # own 20s read timeout would otherwise fire before our outer
                # ``wait_for`` ceiling on IMF's slow edge. A minimal mock client
                # may accept neither kwarg; degrade gracefully.
                try:
                    coro = client.get(
                        url, headers={"User-Agent": "curl/8.4.0"}, timeout=timeout
                    )
                except TypeError:
                    try:
                        coro = client.get(url, headers={"User-Agent": "curl/8.4.0"})
                    except TypeError:
                        coro = client.get(url)
                resp = await asyncio.wait_for(coro, timeout=timeout + 2)
                resp.raise_for_status()
                payload = resp.json()
            except Exception as exc:  # network / decode / HTTP error
                return ind, None, f"{ind}: {type(exc).__name__}: {exc}"
            series = (
                (payload.get("values") or {})
                .get(ind, {})
                .get(country)
            )
            if not isinstance(series, dict) or not series:
                return ind, None, f"{ind}: no series for {country}"
            return ind, series, None

        results = await asyncio.gather(*(_fetch(i) for i in indicators))

        warnings: list[str] = []
        current_year = datetime.now(timezone.utc).year
        # Forecast horizon: from current year forward (the future-estimate table).
        forecast_years = list(range(current_year, current_year + years))

        rows: list[dict[str, Any]] = []
        any_series = False
        for ind, series, err in results:
            if err:
                warnings.append(err)
                continue
            any_series = True
            label, unit = _indicator_label(ind)
            for yr in forecast_years:
                raw = series.get(str(yr))
                if raw is None:
                    continue
                try:
                    value = round(float(raw), 6)
                except (TypeError, ValueError):
                    continue
                rows.append({
                    "country": country,
                    "indicator": ind,
                    "metric": label,
                    "year": yr,
                    "forecast_value": value,
                    "unit": unit,
                    "vintage": "imf_weo",
                    "source_mode": "imf_weo",
                })

        if not rows:
            # No live rows at all -> genuine outage or unknown country.
            reason = "; ".join(warnings) if warnings else "no forecast rows available"
            data = _provider_unavailable(country, indicators, reason)
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=data,
                sources=["no_live_source"] if not any_series else ["imf"],
                warnings=warnings or [f"ECFC: {reason}"],
                metadata={
                    "country": country,
                    "indicators": indicators,
                    "data_state": "provider_unavailable",
                },
            )

        rows.sort(key=lambda r: (str(r["metric"]), int(r["year"])))
        cards = _forecast_cards(rows)
        data = {
            "country": country,
            "rows": rows,
            "series": rows,
            "cards": cards,
            "status": "ok",
            "data_state": "live",
            "vintage": "imf_weo",
            "source_mode": "imf_weo",
            "as_of": datetime.now(timezone.utc).isoformat(),
            "methodology": (
                "ECFC builds the forecast table from the IMF World Economic Outlook "
                "via the keyless IMF DataMapper API. For each requested WEO indicator "
                "code the full per-country projection series is fetched, then the "
                f"forward horizon ({forecast_years[0]}-{forecast_years[-1]}) is sliced "
                "out as the forecast rows. Every value is a genuine IMF projection for "
                "that (country, indicator, year) — no constants are fabricated. Cards "
                "summarise the nearest-year forecast per indicator."
            ),
            "field_dictionary": _FIELD_DICT,
        }
        return FunctionResult(
            code=self.code,
            instrument=None,
            data=data,
            sources=["imf"],
            warnings=warnings,
            metadata={
                "country": country,
                "indicators": indicators,
                "vintage": "imf_weo",
                "data_state": "live",
                "provider_errors": warnings,
            } if warnings else {
                "country": country,
                "indicators": indicators,
                "vintage": "imf_weo",
                "data_state": "live",
            },
        )

    async def _client(self) -> Any:
        """Resolve an httpx-like async client (shared keyless pool).

        Resolution order: an explicitly injected ``self._http_client`` (used
        by tests), then ``self.deps.http`` if a host wired one, then the
        shared keyless httpx pool.
        """
        injected = getattr(self, "_http_client", None)
        if injected is not None:
            return injected
        deps = getattr(self, "deps", None)
        http = getattr(deps, "http", None) if deps is not None else None
        if http is not None:
            return http
        from showme.providers._http import get_client

        return await get_client()


def _forecast_cards(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Nearest-year forecast value per metric, one card each (max 6)."""
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in sorted(rows, key=lambda r: (str(r.get("metric")), int(r.get("year") or 0))):
        metric = str(row.get("metric"))
        if metric in seen:
            continue
        seen.add(metric)
        cards.append({"label": metric, "value": row.get("forecast_value")})
    return cards[:6]
