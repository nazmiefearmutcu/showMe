"""SAT — Satellite imagery / alt-data for a curated AOI.

Plan §6.6 + EK D: alt-veri katmanı. Keyless implementation.

The old handler returned a key-gated Sentinel Hub stub (provider_unavailable
unless SENTINELHUB_CLIENT_ID/SECRET were configured) and a synthetic SVG
"bbox preview" that pretended nothing real was available. This version
returns REAL, keyless data:

  * Real satellite *tile* URLs from NASA GIBS (Global Imagery Browse
    Services) for the requested AOI + layer + capture date. GIBS serves
    daily true-color (MODIS/VIIRS) and derived layers as public WMTS/WMS
    tiles with no API key. The returned `tile_url` is a live, fetchable
    PNG of the actual AOI on the actual capture day.
  * A real weather / conditions summary for the AOI centroid from
    Open-Meteo (https://api.open-meteo.com) — keyless — which doubles as
    a cloud-cover proxy (Open-Meteo exposes a `cloud_cover` field) so the
    manifest's `cloud_pct` column carries a genuine numeric value instead
    of a fabricated one.

Only a real network outage downgrades the result to provider_unavailable.
"""

from __future__ import annotations

import asyncio
import base64
import struct
import zlib
from datetime import date, datetime, timedelta, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument

# Curated AOIs (lon, lat, span_deg) matching the manifest `aoi` SELECT options.
# Each entry: (center_lon, center_lat, half_span_deg, human label).
_AOI_PRESETS: dict[str, tuple[float, float, float, str]] = {
    "cushing_ok": (-96.7651, 35.9851, 0.15, "Cushing OK tank farm"),
    "singapore_strait": (103.8198, 1.2500, 0.30, "Singapore Strait"),
    "shanghai_port": (121.8000, 30.6300, 0.25, "Shanghai / Yangshan port"),
    "rotterdam_port": (4.0500, 51.9500, 0.20, "Rotterdam port"),
    "saudi_ras_tanura": (50.1600, 26.6400, 0.20, "Ras Tanura terminal"),
    "iowa_corn_belt": (-93.6000, 42.0300, 0.50, "Iowa corn belt"),
}

# GIBS layer ids (EPSG:4326 best/daily) keyed by the manifest `layer` SELECT.
_GIBS_LAYERS: dict[str, tuple[str, str]] = {
    # ui_layer -> (gibs_layer_id, tile_matrix_set)
    "true_color": ("MODIS_Terra_CorrectedReflectance_TrueColor", "250m"),
    "ndvi": ("MODIS_Terra_NDVI_8Day", "1km"),
    "moisture": ("MODIS_Terra_CorrectedReflectance_Bands721", "250m"),
    "thermal": ("MODIS_Terra_Land_Surface_Temp_Day", "1km"),
    "swir": ("MODIS_Terra_CorrectedReflectance_Bands721", "250m"),
}

_GIBS_BASE = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
_OPEN_METEO = "https://api.open-meteo.com/v1/forecast"

# GIBS answers HTTP 200 with an all-black PNG for days it has not processed yet.
# A tile counts as imagery only when at least this share of its pixels carry colour;
# otherwise the search walks back up to _TILE_LOOKBACK_DAYS days for a real tile.
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_MIN_IMAGERY_FRACTION = 0.01
_TILE_LOOKBACK_DAYS = 4
_TILE_RESOLVE_TIMEOUT = 10.0
# Open-Meteo runs after the tile walk-back, so its own budget is kept small:
# worst case is _TILE_RESOLVE_TIMEOUT + _CONDITIONS_TIMEOUT, inside the 14 s router timeout.
_CONDITIONS_TIMEOUT = 3.0


@FunctionRegistry.register
class SATFunction(BaseFunction):
    code = "SAT"
    name = "Satellite Imagery"
    category = "misc"
    description = "Keyless NASA GIBS tile URLs + Open-Meteo conditions for a curated AOI."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        aoi_key = str(params.get("aoi") or "cushing_ok").strip()
        layer_key = str(params.get("layer") or "true_color").strip()

        # Allow a raw bbox override (legacy) but default to curated AOI presets.
        bbox_override = _parse_bbox(params.get("bbox"))
        # An unknown area or layer the caller asked for is an input error, not a
        # silent switch to Cushing / true colour (data policy: no default
        # location for an unknown input - review of SAT#1).
        unknown = []
        if aoi_key not in _AOI_PRESETS and bbox_override is None:
            unknown.append(f"aoi {aoi_key!r} (presets: {', '.join(sorted(_AOI_PRESETS))})")
        if layer_key not in _GIBS_LAYERS:
            unknown.append(f"layer {layer_key!r} (layers: {', '.join(sorted(_GIBS_LAYERS))})")
        if unknown:
            return FunctionResult(
                code=self.code, instrument=None,
                data={"status": "input_error", "reason": "Unknown " + "; ".join(unknown) + ".",
                      "next_actions": ["Pick a preset area and layer, or pass bbox=minLon,minLat,maxLon,maxLat."],
                      "rows": []},
                warnings=["unknown " + "; ".join(unknown)],
            )

        if bbox_override is not None:
            bbox = bbox_override
            aoi_label = "custom bbox"
            center_lon = (bbox[0] + bbox[2]) / 2
            center_lat = (bbox[1] + bbox[3]) / 2
        else:
            clon, clat, half, aoi_label = _AOI_PRESETS[aoi_key]
            bbox = (clon - half, clat - half, clon + half, clat + half)
            center_lon, center_lat = clon, clat

        date_from, date_to = _date_window(params)
        requested_date = date_to  # the window end the caller asked for

        gibs_layer_id, _matrix = _GIBS_LAYERS[layer_key]

        methodology = (
            "SAT surfaces real, keyless satellite tiles from NASA GIBS (Global Imagery "
            "Browse Services) for the selected AOI, layer and capture date. The tile_url is a "
            "live WMS PNG of the actual area (MODIS/VIIRS daily mosaics, no API key). A tile is "
            "only used when it carries imagery: GIBS returns blank black tiles for days it has "
            "not processed, so SAT walks back to the newest real tile and reports the lag "
            "(capture_lag_days). Cloud cover is the real value reported by Open-Meteo for the AOI "
            "centroid on the capture date (keyless), used as the cloud_pct proxy. No synthetic "
            "tiles and no fabricated cloud percentages: on a real network outage SAT degrades to "
            "provider_unavailable with an honest warning."
        )
        field_dictionary = {
            "capture_utc": "Image capture day (UTC) for the GIBS daily mosaic.",
            "aoi": "Curated area-of-interest label.",
            "layer": "Requested GIBS visualisation layer.",
            "cloud_pct": "Cloud cover % at the AOI centroid on the capture date (Open-Meteo).",
            "tile_url": "Live NASA GIBS WMS PNG tile URL for the AOI + layer + date.",
            "source": "Provider that supplied the tile / metadata.",
        }

        now_iso = datetime.now(timezone.utc).isoformat()
        sources = ["nasa_gibs"]
        warnings: list[str] = []

        def _provider_unavailable(reason: str, tile_checks: list[dict[str, Any]]) -> FunctionResult:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "data_mode": "not_configured",
                    "reason": reason,
                    "rows": [],
                    "cards": [],
                    "methodology": methodology,
                    "field_dictionary": field_dictionary,
                    "aoi": aoi_key,
                    "aoi_label": aoi_label,
                    "layer": layer_key,
                    "bbox": list(bbox),
                    "as_of": now_iso,
                    "tile_checks": tile_checks,
                    "next_actions": [
                        "Retry SAT; NASA GIBS and Open-Meteo are keyless public services and may be briefly unavailable.",
                        "Pick a different capture date inside GIBS coverage (last ~2 weeks are most reliable).",
                    ],
                },
                sources=sources,
                warnings=warnings,
                metadata={"fallback": True, "degraded": True, "latency_ms": None},
            )

        # --- Newest GIBS tile that actually carries imagery -------------------
        tile = await self._resolve_tile(bbox, gibs_layer_id, requested_date)
        if tile["capture_date"] is None and tile["state"] != "empty":
            # No tile was verified as imagery and no capture day can be attributed.
            # Presenting the requested day here would show an unverified or blank tile.
            warnings.append(tile["reason"])
            return _provider_unavailable(tile["reason"], tile["checks"])
        if tile["state"] == "empty":
            # Every candidate day is blank: explicit empty state, no tile row.
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "empty",
                    "data_mode": "delayed_reference",
                    "reason": tile["reason"],
                    "rows": [],
                    "cards": [],
                    "methodology": methodology,
                    "field_dictionary": field_dictionary,
                    "aoi": aoi_key,
                    "aoi_label": aoi_label,
                    "layer": layer_key,
                    "bbox": list(bbox),
                    "requested_date": requested_date,
                    "date_from": date_from,
                    "date_to": date_to,
                    "tile_checks": tile["checks"],
                    "as_of": now_iso,
                    "next_actions": [
                        "GIBS has no processed imagery for this window yet; pick an earlier capture date.",
                        "Retry SAT later for a newer capture.",
                    ],
                },
                sources=sources,
                warnings=[tile["reason"]],
                metadata={"fallback": False, "degraded": True, "latency_ms": None},
            )

        capture_date = tile["capture_date"] or requested_date
        tile_url = tile["tile_url"] or _gibs_wms_url(bbox, gibs_layer_id, capture_date)
        tile_reachable = tile["state"] == "imagery"
        if not tile_reachable:
            warnings.append(tile["reason"])
        capture_lag_days = _lag_days(requested_date, capture_date)
        if capture_lag_days > 0:
            warnings.append(
                f"GIBS has no imagery for {requested_date}; newest real tile is {capture_date} "
                f"({capture_lag_days} day(s) earlier)."
            )

        # --- Real conditions / cloud cover from Open-Meteo (keyless) ---------
        cloud_pct: float | None = None
        weather_summary: dict[str, Any] = {}
        try:
            weather_summary, cloud_pct = await asyncio.wait_for(
                self._fetch_conditions(center_lat, center_lon, capture_date),
                timeout=_CONDITIONS_TIMEOUT,
            )
            sources.append("open_meteo")
        except Exception as exc:  # genuine outage of the conditions provider
            warnings.append(f"open_meteo: {str(exc) or type(exc).__name__}")

        if not tile_reachable and cloud_pct is None and not weather_summary:
            # Both providers down -> honest outage, no fabrication.
            return _provider_unavailable(
                "; ".join(warnings) or "No live satellite/conditions source reachable.",
                tile["checks"],
            )

        row = {
            "capture_utc": capture_date,
            "aoi": aoi_label,
            "aoi_key": aoi_key,
            "layer": layer_key,
            "cloud_pct": round(cloud_pct, 1) if isinstance(cloud_pct, (int, float)) else None,
            "tile_url": tile_url,
            "source": "nasa_gibs",
            "bbox": ",".join(f"{v:.5f}" for v in bbox),
            "center_lon": round(center_lon, 5),
            "center_lat": round(center_lat, 5),
            "tile_reachable": tile_reachable,
        }

        cards = [
            {
                "aoi": aoi_label,
                "latest_capture": capture_date,
                "cloud_pct": round(cloud_pct, 1) if isinstance(cloud_pct, (int, float)) else None,
                "data_mode": "delayed_reference",
                "capture_lag_days": capture_lag_days,
                "as_of": now_iso,
            }
        ]

        # partial = the card is not the requested day (lagged) or the tile could not be verified.
        status = "ok"
        if not tile_reachable:
            status = "partial"
            warnings.append("GIBS tile probe failed; conditions still live.")
        elif capture_lag_days > 0:
            status = "partial"

        data: dict[str, Any] = {
            "status": status,
            "data_mode": "delayed_reference",
            "aoi": aoi_key,
            "aoi_label": aoi_label,
            "layer": layer_key,
            "bbox": list(bbox),
            "bbox_label": ",".join(f"{v:.5f}" for v in bbox),
            "date_from": date_from,
            "date_to": date_to,
            "requested_date": requested_date,
            "capture_date": capture_date,
            "capture_lag_days": capture_lag_days,
            "tile_checks": tile["checks"],
            "tile_url": tile_url,
            "true_color_tile": {
                "label": f"NASA GIBS {gibs_layer_id} ({capture_date})",
                "url": tile_url,
                "is_satellite": True,
            },
            "conditions": weather_summary,
            "cloud_pct": round(cloud_pct, 1) if isinstance(cloud_pct, (int, float)) else None,
            "rows": [row],
            "cards": cards,
            "methodology": methodology,
            "field_dictionary": field_dictionary,
            "as_of": now_iso,
            "next_actions": [],
        }
        if capture_lag_days > 0:
            data["next_actions"].append(
                f"Newest processed GIBS imagery is {capture_date}, {capture_lag_days} day(s) before the requested date."
            )
        if not tile_reachable:
            data["next_actions"].append(
                "Some sub-providers were briefly unavailable; retry for a fully-populated card."
            )

        return FunctionResult(
            code=self.code,
            instrument=None,
            data=data,
            sources=sources,
            warnings=warnings,
            metadata={
                "fallback": False,
                "degraded": status != "ok",
                "latency_ms": None,
            },
        )

    # ------------------------------------------------------------------ helpers
    async def _fetch_conditions(
        self, lat: float, lon: float, date: str
    ) -> tuple[dict[str, Any], float | None]:
        """Real keyless conditions (and cloud-cover proxy) from Open-Meteo."""
        params = {
            "latitude": f"{lat:.4f}",
            "longitude": f"{lon:.4f}",
            "current": "temperature_2m,cloud_cover,wind_speed_10m,weather_code",
            "daily": "cloud_cover_mean,temperature_2m_max,temperature_2m_min,precipitation_sum",
            "start_date": date,
            "end_date": date,
            "timezone": "UTC",
        }
        payload = await _http_get_json(_OPEN_METEO, params)
        if not isinstance(payload, dict):
            raise ValueError("unexpected Open-Meteo payload")

        current = payload.get("current") or {}
        daily = payload.get("daily") or {}

        # Prefer the daily mean cloud cover for the capture day; fall back to current.
        cloud_pct: float | None = None
        daily_cloud = daily.get("cloud_cover_mean")
        if isinstance(daily_cloud, list) and daily_cloud and isinstance(daily_cloud[0], (int, float)):
            cloud_pct = float(daily_cloud[0])
        elif isinstance(current.get("cloud_cover"), (int, float)):
            cloud_pct = float(current["cloud_cover"])

        def _first(seq: Any) -> Any:
            return seq[0] if isinstance(seq, list) and seq else None

        summary = {
            "current_temp_c": current.get("temperature_2m"),
            "current_cloud_pct": current.get("cloud_cover"),
            "current_wind_ms": current.get("wind_speed_10m"),
            "weather_code": current.get("weather_code"),
            "daily_cloud_mean_pct": cloud_pct,
            "daily_temp_max_c": _first(daily.get("temperature_2m_max")),
            "daily_temp_min_c": _first(daily.get("temperature_2m_min")),
            "daily_precip_mm": _first(daily.get("precipitation_sum")),
            "source": "open_meteo",
        }
        return summary, cloud_pct

    async def _resolve_tile(self, bbox: tuple[float, float, float, float], layer_id: str, requested: str) -> dict[str, Any]:
        """Newest GIBS tile with imagery at or before ``requested`` (bounded by a timeout)."""
        try:
            return await asyncio.wait_for(
                _resolve_tile_candidates(bbox, layer_id, requested),
                timeout=_TILE_RESOLVE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return {
                "state": "unreachable",
                "capture_date": None,
                "tile_url": None,
                "checks": [],
                "reason": f"nasa_gibs: tile lookup exceeded {_TILE_RESOLVE_TIMEOUT:.0f}s",
            }


def _gibs_wms_url(bbox: tuple[float, float, float, float], layer_id: str, date: str) -> str:
    """Build a live keyless NASA GIBS WMS GetMap PNG URL for the AOI."""
    lon1, lat1, lon2, lat2 = bbox
    # WMS 1.3.0 EPSG:4326 expects bbox as minLat,minLon,maxLat,maxLon.
    bbox_str = f"{lat1:.6f},{lon1:.6f},{lat2:.6f},{lon2:.6f}"
    query = (
        f"{_GIBS_BASE}?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0"
        f"&LAYERS={layer_id}&STYLES="
        f"&CRS=EPSG:4326&BBOX={bbox_str}"
        f"&WIDTH=768&HEIGHT=768&FORMAT=image/png&TIME={date}"
    )
    return query


async def _http_get_json(url: str, params: dict[str, Any]) -> Any:
    resp = await _http_get_raw(url, params=params)
    # httpx-like client exposes .json(); fall back to stdlib json on .text.
    json_fn = getattr(resp, "json", None)
    if callable(json_fn):
        result = json_fn()
        if asyncio.iscoroutine(result):
            result = await result
        return result
    import json as _json

    return _json.loads(getattr(resp, "text", "") or "{}")


async def _http_get_raw(url: str, params: dict[str, Any] | None = None):
    """Fetch with the shared keyless httpx.AsyncClient.

    ``get_client()`` is an async factory returning a pooled httpx.AsyncClient,
    so it MUST be awaited before issuing the request. The client already sends
    a descriptive default User-Agent; we add a research contact on top.
    """
    from showme.providers._http import get_client

    client = get_client()
    if asyncio.iscoroutine(client):
        client = await client
    headers = {"User-Agent": "showMe research contact@example.com"}
    kwargs: dict[str, Any] = {"timeout": 12, "headers": headers}
    if params is not None:
        kwargs["params"] = params
    try:
        result = client.get(url, **kwargs)
    except TypeError:
        # Client may not accept headers/timeout kwargs; retry minimally.
        kwargs.pop("headers", None)
        try:
            result = client.get(url, **kwargs)
        except TypeError:
            kwargs.pop("timeout", None)
            result = client.get(url, **kwargs)
    if asyncio.iscoroutine(result):
        result = await result
    return result


async def _resolve_tile_candidates(
    bbox: tuple[float, float, float, float], layer_id: str, requested: str
) -> dict[str, Any]:
    """Check the requested day, then walk back day by day until a tile has imagery."""
    try:
        base = date.fromisoformat(requested)
    except ValueError:
        return {
            "state": "unreachable",
            "capture_date": None,
            "tile_url": None,
            "checks": [],
            "reason": f"invalid capture date {requested!r}",
        }
    checks: list[dict[str, Any]] = []
    unreachable: list[str] = []
    for back in range(_TILE_LOOKBACK_DAYS + 1):
        day = (base - timedelta(days=back)).isoformat()
        url = _gibs_wms_url(bbox, layer_id, day)
        state, detail = await _check_tile(url)
        check: dict[str, Any] = {"date": day, "state": state}
        if detail:
            check["detail"] = detail
        checks.append(check)
        if state == "imagery":
            return {"state": "imagery", "capture_date": day, "tile_url": url, "checks": checks, "reason": ""}
        if state == "unreachable":
            unreachable.append(detail)
    if unreachable:
        # No day was verified as imagery and at least one probe failed. The requested
        # day may be blank (checked above), so no capture date is attributed here.
        return {
            "state": "unreachable",
            "capture_date": None,
            "tile_url": None,
            "checks": checks,
            "reason": unreachable[0] or "nasa_gibs: tile could not be verified",
        }
    return {
        "state": "empty",
        "capture_date": None,
        "tile_url": None,
        "checks": checks,
        "reason": (
            f"GIBS returned blank tiles for {requested} and the {_TILE_LOOKBACK_DAYS} days before it; "
            "no imagery to show."
        ),
    }


async def _check_tile(url: str) -> tuple[str, str]:
    """Classify one GIBS tile as ("imagery" | "blank" | "unreachable", detail)."""
    try:
        resp = await _http_get_raw(url)
    except Exception as exc:
        return "unreachable", f"nasa_gibs: {exc}"
    try:
        status = int(getattr(resp, "status_code", 0) or 0)
    except (TypeError, ValueError):
        status = 0
    if not 200 <= status < 300:
        return "unreachable", f"nasa_gibs: HTTP {status}"
    body = getattr(resp, "content", b"") or b""
    if not isinstance(body, (bytes, bytearray)) or not bytes(body).startswith(_PNG_SIGNATURE):
        return "unreachable", "nasa_gibs: response is not a PNG tile"
    fraction = await asyncio.to_thread(_png_nonzero_fraction, bytes(body))
    if fraction is None:
        return "unreachable", "nasa_gibs: PNG tile could not be decoded"
    if fraction < _MIN_IMAGERY_FRACTION:
        return "blank", f"only {fraction:.2%} of pixels carry colour"
    return "imagery", ""


def _lag_days(requested: str, capture: str) -> int:
    try:
        return max(0, (date.fromisoformat(requested) - date.fromisoformat(capture)).days)
    except ValueError:
        return 0


def _png_nonzero_fraction(data: bytes) -> float | None:
    """Share of pixels whose R, G or B is nonzero, from an 8-bit RGB/RGBA PNG.

    Pure-stdlib decoder (zlib + the five scanline filters). Returns None when the
    bytes are not a PNG this decoder handles, so callers never guess.
    """
    if not data.startswith(_PNG_SIGNATURE):
        return None
    pos = len(_PNG_SIGNATURE)
    width = height = 0
    bit_depth = color_type = interlace = None
    idat: list[bytes] = []
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR" and len(body) >= 13:
            width, height, bit_depth, color_type, _comp, _filt, interlace = struct.unpack(">IIBBBBB", body[:13])
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
    if not width or not height or bit_depth != 8 or color_type not in (2, 6) or interlace != 0:
        return None
    bpp = 3 if color_type == 2 else 4
    stride = width * bpp
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error:
        return None
    if len(raw) < height * (stride + 1):
        return None
    prev = bytearray(stride)
    lit = 0
    for y in range(height):
        start = y * (stride + 1)
        cur = _unfilter_scanline(raw[start], raw[start + 1:start + 1 + stride], prev, bpp)
        if cur is None:
            return None
        # Per-pixel colour test on whole channel slices (C-level max over bytes).
        colour = bytes(map(max, cur[0::bpp], cur[1::bpp], cur[2::bpp]))
        lit += len(colour) - colour.count(0)
        prev = cur
    return lit / float(width * height)


def _unfilter_scanline(ftype: int, line: bytes, prev: bytearray, bpp: int) -> bytearray | None:
    n = len(line)
    if ftype == 0:
        return bytearray(line)
    cur = bytearray(n)
    if ftype == 1:
        for i in range(n):
            left = cur[i - bpp] if i >= bpp else 0
            cur[i] = (line[i] + left) & 0xFF
    elif ftype == 2:
        for i in range(n):
            cur[i] = (line[i] + prev[i]) & 0xFF
    elif ftype == 3:
        for i in range(n):
            left = cur[i - bpp] if i >= bpp else 0
            cur[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
    elif ftype == 4:
        for i in range(n):
            a = cur[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            p = a + b - c
            pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
            if pa <= pb and pa <= pc:
                pred = a
            elif pb <= pc:
                pred = b
            else:
                pred = c
            cur[i] = (line[i] + pred) & 0xFF
    else:
        return None
    return cur


def _parse_bbox(value: Any) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
    elif isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        return None
    if len(parts) != 4:
        return None
    try:
        lon1, lat1, lon2, lat2 = [float(part) for part in parts]
    except Exception:
        return None
    if not (-180 <= lon1 <= 180 and -180 <= lon2 <= 180 and -90 <= lat1 <= 90 and -90 <= lat2 <= 90):
        return None
    if lon1 >= lon2 or lat1 >= lat2:
        return None
    return (lon1, lat1, lon2, lat2)


def _date_window(params: dict[str, Any]) -> tuple[str, str]:
    date_to = str(params.get("date_to") or datetime.now(timezone.utc).date().isoformat())
    # capture_date is the manifest's preferred field name.
    if params.get("capture_date"):
        cd = str(params["capture_date"])
        if "," in cd:  # DATE_RANGE "from,to"
            a, b = [p.strip() for p in cd.split(",", 1)]
            return a, b
        date_to = cd
    if params.get("date_from"):
        return str(params["date_from"]), date_to
    try:
        days = max(1, min(int(params.get("days", 7)), 365))
    except Exception:
        days = 7
    try:
        end = datetime.fromisoformat(date_to).date()
    except Exception:
        end = datetime.now(timezone.utc).date()
        date_to = end.isoformat()
    start = end - timedelta(days=days)
    return start.isoformat(), end.isoformat()


__all__ = ["SATFunction"]
