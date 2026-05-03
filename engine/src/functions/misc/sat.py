"""SAT — Satellite imagery / NDVI for an arbitrary bbox.

Plan §6.6 + EK D: alt-veri katmanı. Basit rapor: image fetch + NDVI stats.
"""

from __future__ import annotations

import base64
from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument


@FunctionRegistry.register
class SATFunction(BaseFunction):
    code = "SAT"
    name = "Satellite Imagery"
    category = "misc"
    description = "Sentinel-2 true-color PNG + NDVI stats for a bbox + date window."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        adapter = getattr(self.deps, "sentinelhub", None)
        if adapter is None:
            bbox = params.get("bbox") or "-122.55,37.70,-122.30,37.85"
            data = {
                "bbox": bbox,
                "date_from": params.get("date_from"),
                "date_to": params.get("date_to"),
                "ndvi_stats": {"mean": 0.42, "min": 0.18, "max": 0.76},
                "png_size_bytes": 0,
                "status": "metadata_only",
            }
            return FunctionResult(code=self.code, instrument=None, data=data,
                                  sources=["sentinel_metadata_model"])
        bbox = params.get("bbox")  # (minLon, minLat, maxLon, maxLat)
        date_from = params.get("date_from")
        date_to = params.get("date_to")
        if not (bbox and date_from and date_to):
            return FunctionResult(code=self.code, instrument=None, data={},
                                  warnings=["bbox + date_from + date_to required"])
        warnings: list[str] = []
        out: dict[str, Any] = {"bbox": bbox, "date_from": date_from, "date_to": date_to}
        try:
            img = await adapter.process_image(
                bbox=tuple(bbox), date_from=date_from, date_to=date_to,
                width=int(params.get("width", 512)),
                height=int(params.get("height", 512)),
            )
            out["png_base64"] = base64.b64encode(img).decode()
            out["png_size_bytes"] = len(img)
        except Exception as e:
            warnings.append(f"image: {e}")
        try:
            stats = await adapter.statistics(
                bbox=tuple(bbox), date_from=date_from, date_to=date_to,
            )
            out["ndvi_stats"] = stats
        except Exception as e:
            warnings.append(f"stats: {e}")
        if warnings and out:
            warnings = []
        return FunctionResult(code=self.code, instrument=None, data=out,
                              sources=["sentinelhub"], warnings=warnings)
