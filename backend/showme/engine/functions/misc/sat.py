"""SAT — Satellite imagery / NDVI for an arbitrary bbox.

Plan §6.6 + EK D: alt-veri katmanı. Basit rapor: image fetch + NDVI stats.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument


@FunctionRegistry.register
class SATFunction(BaseFunction):
    code = "SAT"
    name = "Satellite Imagery"
    category = "misc"
    description = "Sentinel-2 true-color PNG + NDVI stats for a bbox + date window."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        bbox_raw = params.get("bbox") or "-122.55,37.70,-122.30,37.85"
        bbox = _parse_bbox(bbox_raw)
        date_from, date_to = _date_window(params)
        if bbox is None:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "input_error",
                    "reason": "bbox must be minLon,minLat,maxLon,maxLat",
                    "requested": {"bbox": bbox_raw, "date_from": date_from, "date_to": date_to},
                    "rows": [],
                    "next_actions": ["Use a bbox such as -122.55,37.70,-122.30,37.85."],
                },
                sources=["showme_satellite_contract"],
            )
        adapter = getattr(self.deps, "sentinelhub", None)
        if adapter is None:
            return _provider_unavailable_result(
                self.code,
                bbox,
                date_from,
                date_to,
                "Sentinel Hub adapter is not configured.",
            )
        if not (bbox and date_from and date_to):
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "input_error",
                    "reason": "bbox + date_from + date_to required",
                    "requested": {"bbox": bbox, "date_from": date_from, "date_to": date_to},
                    "rows": [],
                    "next_actions": ["Set BBox and Range controls, or provide date_from/date_to in Advanced."],
                },
                sources=["showme_satellite_contract"],
            )
        warnings: list[str] = []
        out: dict[str, Any] = {
            "status": "ok",
            "bbox": list(bbox),
            "bbox_label": ",".join(f"{value:.5f}" for value in bbox),
            "date_from": date_from,
            "date_to": date_to,
            "preview": _bbox_preview(bbox),
            "rows": [_bbox_row(bbox, date_from, date_to)],
            "next_actions": [],
        }
        try:
            img = await adapter.process_image(
                bbox=bbox, date_from=date_from, date_to=date_to,
                width=int(params.get("width", 512)),
                height=int(params.get("height", 512)),
            )
            out["png_base64"] = base64.b64encode(img).decode()
            out["true_color_png"] = {
                "label": "Sentinel-2 true-color PNG",
                "data_url": "data:image/png;base64," + out["png_base64"],
                "size_bytes": len(img),
            }
            out["png_size_bytes"] = len(img)
        except Exception as e:
            warnings.append(f"image: {e}")
        try:
            stats = await adapter.statistics(
                bbox=bbox, date_from=date_from, date_to=date_to,
            )
            out["ndvi_stats"] = stats
            out["ndvi_summary"] = _ndvi_summary(stats)
        except Exception as e:
            warnings.append(f"stats: {e}")
        if warnings:
            out["status"] = "provider_unavailable" if "png_base64" not in out and "ndvi_stats" not in out else "partial"
            out["reason"] = "; ".join(warnings)
            out["next_actions"] = [
                "Configure SENTINELHUB_CLIENT_ID and SENTINELHUB_CLIENT_SECRET for true imagery and NDVI.",
                "Verify the bbox and date window are inside Sentinel-2 coverage.",
            ]
        return FunctionResult(
            code=self.code,
            instrument=None,
            data=out,
            sources=["sentinelhub", "showme_bbox_preview"],
            warnings=[],
            metadata={"fallback": out["status"] == "provider_unavailable", "degraded": out["status"] != "ok"},
        )


def _provider_unavailable_result(
    code: str,
    bbox: tuple[float, float, float, float],
    date_from: str,
    date_to: str,
    reason: str,
) -> FunctionResult:
    return FunctionResult(
        code=code,
        instrument=None,
        data={
            "status": "provider_unavailable",
            "reason": reason,
            "bbox": list(bbox),
            "bbox_label": ",".join(f"{value:.5f}" for value in bbox),
            "date_from": date_from,
            "date_to": date_to,
            "preview": _bbox_preview(bbox),
            "rows": [_bbox_row(bbox, date_from, date_to)],
            "next_actions": [
                "Configure SENTINELHUB_CLIENT_ID and SENTINELHUB_CLIENT_SECRET.",
                "Retry SAT after credentials are available; preview shown is a bbox footprint, not satellite imagery.",
            ],
        },
        sources=["showme_bbox_preview"],
        metadata={"fallback": True, "degraded": True},
    )


def _parse_bbox(value: Any) -> tuple[float, float, float, float] | None:
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
    if params.get("date_from"):
        return str(params["date_from"]), date_to
    try:
        days = max(1, min(int(params.get("days", 7)), 365))
    except Exception:
        days = 7
    end = datetime.fromisoformat(date_to).date()
    start = end - timedelta(days=days)
    return start.isoformat(), end.isoformat()


def _bbox_row(bbox: tuple[float, float, float, float], date_from: str, date_to: str) -> dict[str, Any]:
    lon1, lat1, lon2, lat2 = bbox
    return {
        "bbox": ",".join(f"{value:.5f}" for value in bbox),
        "date_from": date_from,
        "date_to": date_to,
        "center_lon": round((lon1 + lon2) / 2, 5),
        "center_lat": round((lat1 + lat2) / 2, 5),
        "width_deg": round(lon2 - lon1, 5),
        "height_deg": round(lat2 - lat1, 5),
    }


def _bbox_preview(bbox: tuple[float, float, float, float]) -> dict[str, Any]:
    lon1, lat1, lon2, lat2 = bbox
    label = f"BBox preview {lon1:.2f},{lat1:.2f} to {lon2:.2f},{lat2:.2f}"
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">
<rect width="640" height="360" fill="#071018"/>
<path d="M0 210 C120 150 230 260 360 190 C470 130 550 160 640 105 L640 360 L0 360 Z" fill="#142b28"/>
<path d="M0 235 C150 190 220 285 360 225 C480 172 560 205 640 150" fill="none" stroke="#24433c" stroke-width="3"/>
<rect x="148" y="82" width="344" height="178" fill="rgba(15,178,117,0.12)" stroke="#10b981" stroke-width="4"/>
<circle cx="320" cy="171" r="6" fill="#22d3ee"/>
<text x="24" y="42" fill="#d7f3ed" font-family="Arial" font-size="22" font-weight="700">Satellite bbox preview</text>
<text x="24" y="70" fill="#8ea3ad" font-family="Arial" font-size="15">Not a Sentinel-2 image. Credentials are required for true-color PNG and NDVI.</text>
<text x="24" y="320" fill="#d7f3ed" font-family="Arial" font-size="16">{label}</text>
</svg>"""
    encoded = base64.b64encode(svg.encode()).decode()
    return {
        "label": "BBox preview (not satellite imagery)",
        "data_url": "data:image/svg+xml;base64," + encoded,
        "is_satellite": False,
    }


def _ndvi_summary(stats: Any) -> dict[str, Any]:
    if not isinstance(stats, dict):
        return {}
    try:
        intervals = stats.get("data") or []
        outputs = ((intervals[0] or {}).get("outputs") or {}) if intervals else {}
        bands = (((outputs.get("ndvi") or {}).get("bands") or {}).get("B0") or {}).get("stats") or {}
        return {
            "mean": bands.get("mean"),
            "min": bands.get("min"),
            "max": bands.get("max"),
            "sample_count": bands.get("sampleCount") or bands.get("sample_count"),
        }
    except Exception:
        return {}
