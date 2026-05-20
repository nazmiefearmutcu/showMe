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
            raise HTTPException(status_code=500, detail=f"factory: {exc}") from exc
        body = payload or {}
        phases = body.get("phases")
        if isinstance(phases, list):
            phases = ",".join(str(p) for p in phases)
        req = ScanRequest(
            intent=str(body.get("intent") or ""),
            universe=body.get("universe"),
            asset_class=body.get("asset_class"),
            timeframes=body.get("timeframes"),
            top_n=int(body.get("top_n", 20)),
            phases=str(phases) if phases else "A,B",
            fine_top_k=int(body["fine_top_k"]) if body.get("fine_top_k") else None,
        )
        result = await run_scan(req, getattr(factory, "deps", None))
        return result.to_dict()

    app.include_router(router)
