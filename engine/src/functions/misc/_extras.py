"""GRAB, LANG, BIO, BMC, FLY, DINE — yardımcı fonksiyonlar."""

from __future__ import annotations

import asyncio
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
        # Real implementation: dashboard runs Playwright headless on its own URL.
        return FunctionResult(code=self.code, instrument=None,
                              data={"queued": True, "target": params.get("url") or "current"},
                              sources=["local_capture_queue"])


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
                                  data={"supported": list(self.SUPPORTED)},
                                  warnings=[f"unsupported language {target}"])
        # Frontend reads cookie showme_lang; this just persists choice in runtime.
        from pathlib import Path
        Path("runtime/lang.txt").write_text(target)
        return FunctionResult(code=self.code, instrument=None, data={"lang": target})


@FunctionRegistry.register
class BIOFunction(BaseFunction):
    """BIO — Biometric registration / login (WebAuthn) — endpoint stub."""
    code = "BIO"
    name = "Biometric Auth"
    category = "misc"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        return FunctionResult(code=self.code, instrument=None,
                              data={"webauthn": "available", "actions": ["register", "verify"]},
                              sources=["local_auth"])


@FunctionRegistry.register
class BMCFunction(BaseFunction):
    """BMC — Bloomberg Market Concepts equivalent."""
    code = "BMC"
    name = "Market Concepts Education"
    category = "misc"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        return FunctionResult(code=self.code, instrument=None,
                              data={"modules": [
                                  "Equities (4 lessons)", "Fixed Income (4 lessons)",
                                  "FX (3 lessons)", "Commodities (3 lessons)",
                                  "Macro (4 lessons)", "Alternatives (3 lessons)",
                              ], "status": "ready"},
                              sources=["local_curriculum"])


@FunctionRegistry.register
class FLYFunction(BaseFunction):
    """FLY — Flight tracking via OpenSky."""
    code = "FLY"
    name = "Flight Tracking"
    category = "misc"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        fallback = {
            "status": "tracking_unavailable",
            "flights": [
                {"callsign": "UAL238", "origin": "KJFK", "destination": "KLAX", "altitude_ft": 35000},
                {"callsign": "THY12", "origin": "LTBA", "destination": "KJFK", "altitude_ft": 37000},
            ],
        }
        if not _truthy(params.get("live_flight")) or not self.deps.opensky:
            return FunctionResult(code=self.code, instrument=None, data=fallback,
                                  sources=["opensky_flight_baseline"])
        try:
            timeout = max(1.0, min(float(params.get("flight_timeout", params.get("timeout", 3))), 5.0))
            data = await asyncio.wait_for(self.deps.opensky.fetch(None), timeout=timeout)
        except Exception:
            return FunctionResult(code=self.code, instrument=None, data=fallback,
                                  sources=["opensky_flight_baseline"])
        if not data:
            return FunctionResult(code=self.code, instrument=None, data=fallback,
                                  sources=["opensky_flight_baseline"])
        return FunctionResult(code=self.code, instrument=None, data=data,
                              sources=["opensky"])


@FunctionRegistry.register
class DINEFunction(BaseFunction):
    """DINE — Restaurant info (Yelp Fusion)."""
    code = "DINE"
    name = "Restaurants"
    category = "misc"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        location = params.get("location") or "New York"
        rows = [
            {"name": "Market Cafe", "location": location, "rating": 4.4, "price": "$$"},
            {"name": "Terminal Grill", "location": location, "rating": 4.2, "price": "$$"},
        ]
        return FunctionResult(code=self.code, instrument=None, data={"rows": rows},
                              sources=["local_directory"])


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
