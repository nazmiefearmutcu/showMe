"""GRAB, LANG, BIO, BMC, FLY, DINE — yardımcı fonksiyonlar."""

from __future__ import annotations

import asyncio
import json
import math
from datetime import datetime, timezone
from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument


@FunctionRegistry.register
class GRABFunction(BaseFunction):
    """GRAB — Screenshot current page → email."""
    code = "GRAB"
    name = "Screenshot Email"
    category = "misc"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        target = params.get("url") or params.get("target") or "current_pane"
        recipient = params.get("recipient") or params.get("to") or ""
        send = _truthy(params.get("send"))
        rows = [
            {
                "step": "capture",
                "target": target,
                "status": "ready",
                "output": "local screenshot artifact",
                "transmits_data": False,
            },
            {
                "step": "email",
                "target": recipient or "not configured",
                "status": "draft_only" if recipient else "not_configured",
                "output": "requires user-confirmed mail integration",
                "transmits_data": True,
            },
        ]
        warnings = []
        if send:
            warnings.append("email send is not executed automatically; screenshot/email transmission requires explicit user confirmation")
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": "draft_only",
                "target": target,
                "recipient": recipient or None,
                "rows": rows,
                "cards": [
                    {"label": "Capture", "value": "local"},
                    {"label": "Email", "value": "draft only"},
                ],
                "methodology": (
                    "GRAB prepares a local screenshot-capture plan and separates it from email delivery. "
                    "Emailing a screenshot transmits user-visible data, so this function reports the required "
                    "send step instead of silently sending anything."
                ),
                "field_dictionary": {
                    "step": "Capture or delivery phase.",
                    "target": "Pane, URL, or recipient target for the phase.",
                    "status": "Current implementation state for the phase.",
                    "transmits_data": "Whether the phase would share user data outside the app.",
                },
                "next_actions": [
                    "Use a local capture command or configured mail integration for a real screenshot file.",
                    "Confirm the recipient before sending any screenshot by email.",
                ],
            },
            sources=["local_capture_plan"],
            warnings=warnings,
        )


@FunctionRegistry.register
class LANGFunction(BaseFunction):
    """LANG — i18n switcher (12 dil)."""
    code = "LANG"
    name = "Language Switch"
    category = "misc"
    SUPPORTED = ("tr", "en", "de", "fr", "es", "it", "pt", "ru", "zh", "ja", "ko", "ar")

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        target = (params.get("lang") or "tr").lower()
        if target not in self.SUPPORTED:
            return FunctionResult(code=self.code, instrument=None,
                                  data={"status": "input_error", "supported": list(self.SUPPORTED)},
                                  warnings=[f"unsupported language {target}"])
        from pathlib import Path
        Path("runtime/lang.txt").write_text(target)
        rows = [
            {
                "lang": code,
                "label": _language_label(code),
                "selected": code == target,
                "coverage": "core_labels",
                "requires_reload": code == target,
            }
            for code in self.SUPPORTED
        ]
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": "ready",
                "lang": target,
                "rows": rows,
                "cards": [
                    {"label": "Selected", "value": target.upper()},
                    {"label": "Languages", "value": len(self.SUPPORTED)},
                ],
                "methodology": (
                    "LANG persists the selected runtime language in runtime/lang.txt and reports supported "
                    "language coverage. Shell-wide text changes require preference-aware UI surfaces to read "
                    "the saved value and may require pane reload."
                ),
                "field_dictionary": {
                    "lang": "IETF-style language code.",
                    "coverage": "Translation coverage currently available in ShowMe.",
                    "requires_reload": "Whether the selected preference needs a pane reload to become visible.",
                },
            },
            sources=["showme_i18n_registry"],
        )


@FunctionRegistry.register
class BIOFunction(BaseFunction):
    """BIO — Biometric registration / login (WebAuthn) — endpoint stub."""
    code = "BIO"
    name = "Biometric Auth"
    category = "misc"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        rows = [
            {
                "action": "capabilities",
                "status": "native_bridge_available",
                "mechanism": "macOS LocalAuthentication via Tauri command biometric_capabilities",
            },
            {
                "action": "verify",
                "status": "user_initiated",
                "mechanism": "request_biometric opens the OS biometric/passcode prompt from the native pane",
            },
            {
                "action": "credential_registry",
                "status": "not_persisted_by_function",
                "mechanism": "ShowMe gates sensitive local actions; it does not export or store biometric secrets",
            },
        ]
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": "ready",
                "rows": rows,
                "cards": [
                    {"label": "Prompt", "value": "native"},
                    {"label": "Secrets", "value": "not exported"},
                ],
                "methodology": (
                    "BIO uses the native macOS LocalAuthentication bridge exposed by the Tauri shell. "
                    "The backend only documents the auth flow; the actual biometric prompt is initiated "
                    "by the BIO pane after the user clicks Verify."
                ),
                "field_dictionary": {
                    "action": "Authentication workflow step.",
                    "status": "Current support state.",
                    "mechanism": "Local system API used for the step.",
                },
            },
            sources=["macos_local_auth_bridge"],
        )


@FunctionRegistry.register
class BMCFunction(BaseFunction):
    """BMC — Bloomberg Market Concepts equivalent."""
    code = "BMC"
    name = "Market Concepts Education"
    category = "misc"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        module_filter = str(params.get("module") or "").strip().lower()
        rows = [row for row in _bmc_lessons() if not module_filter or module_filter in row["module"].lower()]
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": "ready",
                "rows": rows,
                "cards": [
                    {"label": "Modules", "value": len({row["module"] for row in rows})},
                    {"label": "Lessons", "value": len(rows)},
                ],
                "methodology": (
                    "BMC is a local market-concepts curriculum. Each row is a concrete lesson with topic, "
                    "learning objective, example, quiz prompt, and completion state instead of a static module count."
                ),
                "field_dictionary": {
                    "module": "Curriculum module.",
                    "lesson": "Lesson title.",
                    "objective": "What the user should understand after the lesson.",
                    "example": "Market example used in the lesson.",
                    "quiz": "Self-check prompt.",
                },
            },
            sources=["showme_curriculum"],
        )


@FunctionRegistry.register
class FLYFunction(BaseFunction):
    """FLY — Flight tracking via OpenSky."""
    code = "FLY"
    name = "Flight Tracking"
    category = "misc"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        callsign_filter = str(params.get("callsign") or params.get("flight") or "").strip().upper()
        country_filter = str(params.get("country") or "").strip().lower()
        limit = max(1, min(int(params.get("limit") or 25), 100))
        if not _truthy(params.get("live_flight") or params.get("live")) or not self.deps.opensky:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=_flight_unavailable(callsign_filter, country_filter),
                sources=["opensky"],
            )
        try:
            timeout = max(1.0, min(float(params.get("flight_timeout", params.get("timeout", 3))), 5.0))
            data = await asyncio.wait_for(self.deps.opensky.fetch(None), timeout=timeout)
        except Exception as exc:
            payload = _flight_unavailable(callsign_filter, country_filter)
            payload["reason"] = f"OpenSky request failed: {exc}"
            return FunctionResult(code=self.code, instrument=None, data=payload, sources=["opensky"])
        rows = _normalize_opensky(data, callsign_filter, country_filter, limit)
        if not rows:
            payload = _flight_unavailable(callsign_filter, country_filter)
            payload["reason"] = "OpenSky returned no matching live aircraft for the selected filter."
            return FunctionResult(code=self.code, instrument=None, data=payload, sources=["opensky"])
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": "live",
                "rows": rows,
                "surface": [
                    {
                        "callsign": row["callsign"],
                        "altitude_ft": row["altitude_ft"],
                        "value": row["altitude_ft"],
                    }
                    for row in rows
                    if row.get("altitude_ft") is not None
                ],
                "cards": [
                    {"label": "Aircraft", "value": len(rows)},
                    {"label": "Source time", "value": data.get("time") if isinstance(data, dict) else None},
                ],
                "methodology": (
                    "FLY reads OpenSky /states/all and normalizes aircraft state vectors into callsign, "
                    "country, position, altitude, speed, heading, and last-contact fields. Route origin/"
                    "destination is not inferred unless a flight-plan provider is connected."
                ),
                "field_dictionary": {
                    "callsign": "Aircraft callsign reported by ADS-B/OpenSky.",
                    "origin_country": "OpenSky origin country field.",
                    "altitude_ft": "Barometric altitude converted from meters to feet.",
                    "speed_kt": "Velocity converted from m/s to knots.",
                    "last_contact_utc": "Last contact timestamp in UTC.",
                },
            },
            sources=["opensky"],
        )


@FunctionRegistry.register
class DINEFunction(BaseFunction):
    """DINE — Restaurant info (Yelp Fusion)."""
    code = "DINE"
    name = "Restaurants"
    category = "misc"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        location = str(params.get("location") or "New York").strip()
        query = str(params.get("query") or "restaurant").strip()
        limit = max(1, min(int(params.get("limit") or 10), 25))
        try:
            rows = await _nominatim_restaurants(query, location, limit)
        except Exception as exc:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": f"OpenStreetMap lookup failed: {exc}",
                    "rows": [],
                    "next_actions": ["Try a more specific location such as 'SoHo New York' or connect a restaurant ratings provider."],
                },
                sources=["openstreetmap_nominatim"],
            )
        if not rows:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "empty",
                    "reason": f"No OpenStreetMap restaurants matched {query!r} near {location!r}.",
                    "rows": [],
                },
                sources=["openstreetmap_nominatim"],
            )
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": "live",
                "location": location,
                "query": query,
                "rows": rows,
                "surface": [
                    {"name": row["name"], "distance_km": row.get("distance_km"), "value": row.get("distance_km")}
                    for row in rows
                    if row.get("distance_km") is not None
                ],
                "cards": [
                    {"label": "Places", "value": len(rows)},
                    {"label": "Provider", "value": "OSM"},
                ],
                "methodology": (
                    "DINE uses OpenStreetMap Nominatim search results for real place names, addresses, "
                    "coordinates, OSM ids, and tags. Ratings/prices are not fabricated; those fields stay blank "
                    "unless a ratings provider is connected."
                ),
                "field_dictionary": {
                    "name": "Restaurant/place name from OSM.",
                    "display_name": "Full OSM display address.",
                    "lat": "Latitude.",
                    "lon": "Longitude.",
                    "osm_type": "OSM object type.",
                    "distance_km": "Approximate distance from the first matched result.",
                },
            },
            sources=["openstreetmap_nominatim"],
        )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _language_label(code: str) -> str:
    return {
        "tr": "Turkish",
        "en": "English",
        "de": "German",
        "fr": "French",
        "es": "Spanish",
        "it": "Italian",
        "pt": "Portuguese",
        "ru": "Russian",
        "zh": "Chinese",
        "ja": "Japanese",
        "ko": "Korean",
        "ar": "Arabic",
    }.get(code, code)


def _bmc_lessons() -> list[dict[str, str]]:
    catalog = {
        "Equities": [
            ("Equity index construction", "Compare price-weighted and market-cap-weighted indices.", "S&P 500 vs Dow Jones weighting", "Why can one large-cap stock move a cap-weighted index?"),
            ("Valuation multiples", "Read P/E, EV/EBITDA, and sales multiples without mixing denominators.", "High-growth software vs mature utilities", "When is EV/Sales more useful than P/E?"),
            ("Earnings revisions", "Connect analyst revisions to forward estimate momentum.", "EPS upgrades after guidance raise", "What does a rising revision breadth imply?"),
        ],
        "Fixed Income": [
            ("Yield and duration", "Estimate price sensitivity from yield changes.", "10Y Treasury duration shock", "What happens to price when yield rises?"),
            ("Credit spread", "Separate default compensation from risk-free rates.", "IG vs HY spread widening", "Why can spreads widen while Treasury yields fall?"),
        ],
        "FX": [
            ("Covered interest parity", "Relate spot, forward, and interest-rate differentials.", "EURUSD forward points", "Which rate differential makes EUR forward discount?"),
            ("Real effective exchange rates", "Interpret currency valuation against trade-weighted peers.", "REER deviation from long-run average", "What does a high REER suggest?"),
        ],
        "Commodities": [
            ("Futures curves", "Read contango/backwardation and roll yield.", "WTI front-month vs 6M", "When is roll yield positive for a long?"),
            ("Inventory cycles", "Connect stocks, seasonality, and spreads.", "Natural gas storage draw", "Why do inventories affect calendar spreads?"),
        ],
        "Macro": [
            ("Inflation surprise", "Compare actual releases with consensus and prior values.", "CPI 0.2 pp above forecast", "Why do surprises matter more than levels?"),
            ("Policy reaction", "Link data surprises to central-bank path probabilities.", "Fed hold/cut probabilities", "How does a soft CPI change implied cuts?"),
        ],
        "Alternatives": [
            ("Private-market marks", "Understand appraisal lag and smoothing.", "Quarterly NAV updates", "Why can private returns look less volatile?"),
            ("Hedge-fund risk", "Read beta, drawdown, and liquidity terms together.", "Event-driven fund exposure", "Why does lockup change liquidity risk?"),
        ],
    }
    rows: list[dict[str, str]] = []
    for module, lessons in catalog.items():
        for idx, (lesson, objective, example, quiz) in enumerate(lessons, start=1):
            rows.append({
                "module": module,
                "lesson_no": str(idx),
                "lesson": lesson,
                "objective": objective,
                "example": example,
                "quiz": quiz,
                "progress": "not_started",
            })
    return rows


def _flight_unavailable(callsign_filter: str, country_filter: str) -> dict[str, Any]:
    return {
        "status": "provider_unavailable",
        "reason": "OpenSky live tracking is unavailable or live_flight is disabled; no sample aircraft are shown.",
        "callsign": callsign_filter or None,
        "country": country_filter or None,
        "rows": [],
        "next_actions": [
            "Set live_flight=true and rerun.",
            "Use a callsign or origin-country filter to reduce the public OpenSky response.",
            "Set OPENSKY_USERNAME/OPENSKY_PASSWORD for higher public API reliability.",
        ],
    }


def _normalize_opensky(data: Any, callsign_filter: str, country_filter: str, limit: int) -> list[dict[str, Any]]:
    states = data.get("states") if isinstance(data, dict) else []
    rows: list[dict[str, Any]] = []
    for state in states or []:
        if not isinstance(state, list) or len(state) < 17:
            continue
        callsign = str(state[1] or "").strip().upper()
        origin_country = str(state[2] or "").strip()
        if callsign_filter and callsign_filter not in callsign:
            continue
        if country_filter and country_filter not in origin_country.lower():
            continue
        lon = _num(state[5])
        lat = _num(state[6])
        altitude_m = _num(state[7] if state[7] is not None else state[13])
        speed_ms = _num(state[9])
        last_contact = _unix_to_iso(state[4])
        rows.append({
            "icao24": state[0],
            "callsign": callsign or state[0],
            "origin_country": origin_country,
            "last_contact_utc": last_contact,
            "lon": lon,
            "lat": lat,
            "altitude_ft": round(altitude_m * 3.28084, 0) if altitude_m is not None else None,
            "speed_kt": round(speed_ms * 1.94384, 1) if speed_ms is not None else None,
            "heading": _num(state[10]),
            "vertical_rate_mps": _num(state[11]),
            "on_ground": bool(state[8]),
            "source_mode": "opensky_states_all",
        })
        if len(rows) >= limit:
            break
    return rows


async def _nominatim_restaurants(query: str, location: str, limit: int) -> list[dict[str, Any]]:
    import httpx

    headers = {"User-Agent": "showMe-local-restaurant-search/0.1"}
    params = {
        "q": f"{query} {location}",
        "format": "jsonv2",
        "addressdetails": 1,
        "extratags": 1,
        "limit": limit,
    }
    async with httpx.AsyncClient(timeout=8, headers=headers) as client:
        resp = await client.get("https://nominatim.openstreetmap.org/search", params=params)
        resp.raise_for_status()
        payload = resp.json() or []
    if not payload:
        return []
    origin_lat = _num(payload[0].get("lat"))
    origin_lon = _num(payload[0].get("lon"))
    rows: list[dict[str, Any]] = []
    for item in payload[:limit]:
        lat = _num(item.get("lat"))
        lon = _num(item.get("lon"))
        tags = item.get("extratags") if isinstance(item.get("extratags"), dict) else {}
        name = item.get("name") or str(item.get("display_name") or "").split(",")[0]
        rows.append({
            "name": name,
            "display_name": item.get("display_name"),
            "lat": lat,
            "lon": lon,
            "distance_km": _haversine(origin_lat, origin_lon, lat, lon),
            "osm_type": item.get("osm_type"),
            "osm_id": item.get("osm_id"),
            "category": item.get("category"),
            "type": item.get("type"),
            "opening_hours": tags.get("opening_hours"),
            "rating": None,
            "price": None,
            "source_mode": "openstreetmap_nominatim",
        })
    return rows


def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        number = float(value)
        if not math.isfinite(number):
            return None
        return number
    except (TypeError, ValueError):
        return None


def _unix_to_iso(value: Any) -> str | None:
    number = _num(value)
    if number is None:
        return None
    return datetime.fromtimestamp(number, tz=timezone.utc).isoformat()


def _haversine(lat1: float | None, lon1: float | None, lat2: float | None, lon2: float | None) -> float | None:
    if None in (lat1, lon1, lat2, lon2):
        return None
    r = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)), 3)
