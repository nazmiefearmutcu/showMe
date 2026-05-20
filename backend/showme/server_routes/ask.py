"""Natural-language `/api/ask` route."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException

from . import AppDeps

LOG = logging.getLogger("showme.server.ask")


def register(app: FastAPI, deps: AppDeps) -> None:
    from showme.server import _safe_import

    router = APIRouter()

    @router.post("/api/ask")
    async def ask_endpoint(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        from showme.agents import AskRequest, ask
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
        req = AskRequest(query=str(body.get("query") or ""))
        result = await ask(req, getattr(factory, "deps", None))
        return result.to_dict()

    app.include_router(router)
