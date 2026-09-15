"""GRAB, LANG, BIO, BMC, FLY, DINE — yardımcı fonksiyonlar."""

from __future__ import annotations

import asyncio
import math
import time
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument


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
    """LANG — i18n switcher (12 languages)."""
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
        from showme.app_paths import runtime_path
        runtime_path("lang.txt").write_text(target)
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
        # Default-polarity flip (2026-09-08): FLY polls the live OpenSky
        # feed by default; ``reference=true`` skips the provider and every
        # failure path stays honest (no sample aircraft, ever).
        if _truthy(params.get("reference")):
            payload = _flight_unavailable(callsign_filter, country_filter)
            payload["status"] = "empty"
            payload["reason"] = "reference=true; live OpenSky tracking skipped. No sample aircraft are shown."
            return FunctionResult(code=self.code, instrument=None, data=payload,
                                  sources=["no_live_source"],
                                  metadata={"live": False, "data_mode": "empty"})
        if not self.deps.opensky:
            payload = _flight_unavailable(callsign_filter, country_filter)
            payload["reason"] = "OpenSky adapter is not configured; no sample aircraft are shown."
            return FunctionResult(code=self.code, instrument=None, data=payload,
                                  sources=["no_live_source"],
                                  metadata={"live": False, "fallback": True,
                                            "data_mode": "provider_unavailable"})
        try:
            timeout = max(1.0, min(float(params.get("flight_timeout", params.get("timeout", 3))), 5.0))
            data = await asyncio.wait_for(self.deps.opensky.fetch(None), timeout=timeout)
        except Exception as exc:
            payload = _flight_unavailable(callsign_filter, country_filter)
            payload["reason"] = f"OpenSky request failed: {exc}"
            return FunctionResult(code=self.code, instrument=None, data=payload,
                                  sources=["no_live_source"],
                                  metadata={"live": False, "fallback": True,
                                            "data_mode": "provider_unavailable",
                                            "provider_errors": [f"opensky: {exc}"]})
        rows = _normalize_opensky(data, callsign_filter, country_filter, limit)
        if not rows:
            payload = _flight_unavailable(callsign_filter, country_filter)
            payload["status"] = "empty"
            payload["reason"] = "OpenSky returned no matching live aircraft for the selected filter."
            return FunctionResult(code=self.code, instrument=None, data=payload,
                                  sources=["opensky"],
                                  metadata={"live": True, "data_mode": "live_official"})
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
            metadata={"live": True, "data_mode": "live_official"},
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
        # Nominatim's documented maximum is 40 (provider policy, not a
        # local choice) — request denser result sets up to that cap.
        limit = max(1, min(int(params.get("limit") or 25), _NOMINATIM_MAX_LIMIT))
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
                    "DINE searches OpenStreetMap Nominatim bounded to a viewbox around the requested "
                    "location (the city is geocoded first, then the place query runs with bounded=1 so "
                    "results are inside the area, not name matches anywhere on the planet). Amenity "
                    "keywords such as 'restaurant' use Nominatim's tagged-object search; other keywords "
                    "fall back to text matching. Results are cached ~5 minutes in-process, requests are "
                    "throttled to the provider's 1 req/sec policy, and ratings/prices are never fabricated "
                    "— those fields stay blank unless a ratings provider is connected."
                ),
                "field_dictionary": {
                    "name": "Restaurant/place name from OSM.",
                    "display_name": "Full OSM display address.",
                    "address": "Compact street address composed from the OSM address tags (street, district, city, postcode).",
                    "lat": "Latitude.",
                    "lon": "Longitude.",
                    "category": "OSM category (e.g. amenity).",
                    "type": "OSM place type (e.g. restaurant, cafe, fast_food).",
                    "cuisine": "OSM cuisine tag when the mapper supplied one.",
                    "opening_hours": "OSM opening_hours tag when the mapper supplied one.",
                    "osm_type": "OSM object type.",
                    "distance_km": "Approximate distance from the bounded search area's centre (city centre).",
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
        "reason": "OpenSky live tracking is unavailable; no sample aircraft are shown.",
        "callsign": callsign_filter or None,
        "country": country_filter or None,
        "rows": [],
        "next_actions": [
            "Retry once the OpenSky service or network recovers.",
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


_NOMINATIM_USER_AGENT = (
    "showMe-local-restaurant-search/0.2 (+https://github.com/nazmiefearmutcu/showMe; "
    "contact: showme-dine@users.noreply.github.com)"
)
_NOMINATIM_MIN_INTERVAL_SEC = 1.0  # OSM Nominatim policy: ≤1 req/sec absolute.
# Nominatim's documented maximum for the ``limit`` parameter ("cannot be
# more than 40"). We never ask for more, whatever the caller sends.
_NOMINATIM_MAX_LIMIT = 40
# Results are cached in-process for ~5 minutes so repeated pane polls and
# manual refreshes do not hammer the public instance (usage-policy ask).
_NOMINATIM_CACHE_TTL_SEC = 300.0
_NOMINATIM_CACHE_MAX_ENTRIES = 128
_nominatim_last_call_ts: float = 0.0
_nominatim_lock: asyncio.Lock | None = None
_nominatim_cache: dict[str, tuple[float, Any]] = {}

# Amenity tags where Nominatim's bounded viewbox search accepts the
# ``[keyword]`` special-phrase form and returns every tagged object in
# the area (instead of only places whose NAME contains the word).
_NOMINATIM_AMENITY_KEYWORDS = frozenset({
    "restaurant", "cafe", "fast_food", "bar", "pub", "biergarten",
    "food_court", "ice_cream",
})


async def _nominatim_throttle() -> None:
    """Enforce OSM Nominatim's 1 req/sec policy so we never trip a ban.

    A single process-wide async lock + monotonic clock is enough because
    every DINE call goes through this helper; concurrent DINE requests
    queue behind one another rather than firing parallel HTTP requests."""
    global _nominatim_last_call_ts, _nominatim_lock
    if _nominatim_lock is None:
        _nominatim_lock = asyncio.Lock()
    async with _nominatim_lock:
        now = asyncio.get_running_loop().time()
        wait = _NOMINATIM_MIN_INTERVAL_SEC - (now - _nominatim_last_call_ts)
        if wait > 0:
            await asyncio.sleep(wait)
        _nominatim_last_call_ts = asyncio.get_running_loop().time()


def _nominatim_cache_get(key: str) -> Any | None:
    entry = _nominatim_cache.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    if expires_at < time.monotonic():
        _nominatim_cache.pop(key, None)
        return None
    return value


def _nominatim_cache_set(key: str, value: Any) -> None:
    if len(_nominatim_cache) >= _NOMINATIM_CACHE_MAX_ENTRIES:
        oldest = min(_nominatim_cache, key=lambda k: _nominatim_cache[k][0])
        _nominatim_cache.pop(oldest, None)
    _nominatim_cache[key] = (time.monotonic() + _NOMINATIM_CACHE_TTL_SEC, value)


async def _nominatim_get(params: dict[str, Any]) -> list[dict[str, Any]]:
    """One throttled Nominatim search request (policy-compliant headers).

    Raises on HTTP 429 so DINE flips to ``provider_unavailable`` instead
    of pretending success.
    """
    import httpx

    await _nominatim_throttle()
    headers = {
        "User-Agent": _NOMINATIM_USER_AGENT,
        # OSM policy also accepts a separate ``From`` header for the contact
        # email — providing both keeps us policy-compliant regardless of
        # which header the operator inspects.
        "From": "showme-dine@users.noreply.github.com",
    }
    async with httpx.AsyncClient(timeout=8, headers=headers) as client:
        resp = await client.get("https://nominatim.openstreetmap.org/search", params=params)
        if resp.status_code == 429:
            raise RuntimeError(
                f"Nominatim rate-limited (HTTP 429); Retry-After: {resp.headers.get('Retry-After')}"
            )
        resp.raise_for_status()
        payload = resp.json() or []
    return payload if isinstance(payload, list) else []


async def _nominatim_viewbox(location: str) -> dict[str, Any]:
    """Geocode ``location`` once → ``{"viewbox": ..., "center": (lat, lon)}``.

    Empty dict when Nominatim has no usable bounding box for the string,
    in which case the caller falls back to the legacy free-text search.
    """
    payload = await _nominatim_get({"q": location, "format": "jsonv2", "limit": 1})
    if not payload or not isinstance(payload[0], dict):
        return {}
    bbox = payload[0].get("boundingbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return {}
    south = _num(bbox[0])
    north = _num(bbox[1])
    west = _num(bbox[2])
    east = _num(bbox[3])
    if None in (south, north, west, east) or south >= north or west >= east:
        return {}
    return {
        "viewbox": f"{west},{south},{east},{north}",
        "center": ((south + north) / 2.0, (west + east) / 2.0),
    }


def _nominatim_address(item: dict[str, Any]) -> str | None:
    """Compact one-line address from the OSM ``address`` tags, or None."""
    address = item.get("address")
    if not isinstance(address, dict):
        return None
    street = " ".join(
        str(part) for part in (address.get("house_number"), address.get("road")) if part
    )
    district = (
        address.get("suburb")
        or address.get("neighbourhood")
        or address.get("city_district")
    )
    city = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("municipality")
    )
    postcode = address.get("postcode")
    compact = ", ".join(str(part) for part in (street, district, city, postcode) if part)
    return compact or None


async def _nominatim_restaurants(query: str, location: str, limit: int) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 25), _NOMINATIM_MAX_LIMIT))
    cache_key = f"search|{query.casefold()}|{location.casefold()}|{limit}"
    cached = _nominatim_cache_get(cache_key)
    if cached is not None:
        return [dict(row) for row in cached]

    # 1) Geocode the location (cached separately) so the place search can
    #    be bounded to the area instead of name-matching the whole planet.
    geo_key = f"geo|{location.casefold()}"
    geo = _nominatim_cache_get(geo_key)
    if geo is None:
        geo = await _nominatim_viewbox(location)
        _nominatim_cache_set(geo_key, geo)

    keyword = query.strip().casefold().replace(" ", "_")
    viewbox = geo.get("viewbox") if isinstance(geo, dict) else None
    params: dict[str, Any] = {
        "format": "jsonv2",
        "addressdetails": 1,
        "extratags": 1,
        "limit": limit,
    }
    if viewbox and keyword in _NOMINATIM_AMENITY_KEYWORDS:
        # Nominatim special phrase: every object tagged with this amenity
        # inside the bounded viewbox, not just places named "restaurant".
        # (Amenity-only search requires a bounded area per provider docs.)
        params["q"] = f"[{keyword}]"
    else:
        params["q"] = query
    if viewbox:
        params["viewbox"] = viewbox
        params["bounded"] = 1
    payload = await _nominatim_get(params)
    if not payload and viewbox:
        # A bounded search can legitimately come back empty (small area /
        # unmapped keyword); retry the legacy free-text form once so the
        # pane still answers honestly instead of showing a false zero.
        payload = await _nominatim_get({
            "q": f"{query} {location}",
            "format": "jsonv2",
            "addressdetails": 1,
            "extratags": 1,
            "limit": limit,
        })

    center = geo.get("center") if isinstance(geo, dict) else None
    if center:
        origin_lat, origin_lon = center
    elif payload:
        origin_lat = _num(payload[0].get("lat"))
        origin_lon = _num(payload[0].get("lon"))
    else:
        origin_lat, origin_lon = None, None

    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any]] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        identity: tuple[Any, Any] = (item.get("osm_type"), item.get("osm_id"))
        if identity[1] is None:
            identity = ("place_id", item.get("place_id"))
        if identity in seen:
            continue
        seen.add(identity)
        lat = _num(item.get("lat"))
        lon = _num(item.get("lon"))
        tags = item.get("extratags") if isinstance(item.get("extratags"), dict) else {}
        name = item.get("name") or str(item.get("display_name") or "").split(",")[0]
        rows.append({
            "name": name,
            "display_name": item.get("display_name"),
            "address": _nominatim_address(item),
            "lat": lat,
            "lon": lon,
            "distance_km": _haversine(origin_lat, origin_lon, lat, lon),
            "osm_type": item.get("osm_type"),
            "osm_id": item.get("osm_id"),
            # ``place_id`` is the canonical Nominatim identifier; callers
            # need it to round-trip back to the OSM details endpoint or to
            # deduplicate identical hits across queries.
            "place_id": item.get("place_id"),
            "category": item.get("category"),
            "type": item.get("type"),
            "cuisine": tags.get("cuisine"),
            "opening_hours": tags.get("opening_hours"),
            "rating": None,
            "price": None,
            "source_mode": "openstreetmap_nominatim",
        })
        if len(rows) >= limit:
            break
    _nominatim_cache_set(cache_key, rows)
    return [dict(row) for row in rows]


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
