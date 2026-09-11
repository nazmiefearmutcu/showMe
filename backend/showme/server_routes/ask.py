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
        from showme.agents.orchestrator import normalize_history
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
        # Optional multi-turn history (G4 OPP wave): sanitized here so a
        # malformed body is dropped, never trusted. The pane persists its
        # thread per session and sends the trailing Q/A pairs.
        req = AskRequest(
            query=str(body.get("query") or ""),
            history=normalize_history(body.get("history")),
        )
        result = await ask(req, getattr(factory, "deps", None))
        return result.to_dict()

    app.include_router(router)
