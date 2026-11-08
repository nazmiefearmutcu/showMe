"""Scanner routes: universes index + run."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException

from . import AppDeps

LOG = logging.getLogger("showme.server.scanner")


def register(app: FastAPI, deps: AppDeps) -> None:
    from showme.server import _safe_import

    router = APIRouter()

    def _as_int(value: Any, default: int, *, low: int | None = None, high: int | None = None) -> int:
        # mis.py parity (HNT-13): ``top_n: "fast"`` or ``fine_top_k: [1]``
        # used to raise ValueError/TypeError -> 500. Validate to a clean 400.
        try:
            out = int(value) if value not in (None, "") else default
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail=f"invalid integer value: {value!r} ({str(exc) or type(exc).__name__})"
            ) from exc
        if low is not None:
            out = max(low, out)
        if high is not None:
            out = min(high, out)
        return out

    @router.get("/api/scanner/universes")
    async def scanner_universes() -> list[dict[str, Any]]:
        from showme.scanner import list_universes
        return list_universes()

    @router.post("/api/scanner/run")
    async def scanner_run(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        from showme.scanner import ScanRequest, run_scan

        if not deps.boot_state.get("engine_attached"):
            raise HTTPException(status_code=503, detail="ShowMe engine not attached")
        factory_mod = _safe_import("showme.engine.services.function_factory")
        if factory_mod is None:
            raise HTTPException(status_code=503, detail="ShowMe modules unavailable")
        try:
            factory = factory_mod.get_factory()
        except Exception as exc:  # noqa: BLE001
            LOG.exception("get_factory failed")
            raise HTTPException(status_code=500, detail=f"factory: {str(exc) or type(exc).__name__}") from exc
        body = payload or {}
        phases = body.get("phases")
        if isinstance(phases, list):
            phases = ",".join(str(p) for p in phases)
        top_n = _as_int(body.get("top_n"), 20, low=1, high=500)
        fine_top_k = (
            _as_int(body["fine_top_k"], 20, low=1, high=500)
            if body.get("fine_top_k") not in (None, "")
            else None
        )
        req = ScanRequest(
            intent=str(body.get("intent") or ""),
            universe=body.get("universe"),
            asset_class=body.get("asset_class"),
            timeframes=body.get("timeframes"),
            top_n=top_n,
            phases=str(phases) if phases else "A,B",
            fine_top_k=fine_top_k,
        )
        result = await run_scan(req, getattr(factory, "deps", None))
        return result.to_dict()

    app.include_router(router)
