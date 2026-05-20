"""Best-symbol agent route."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException

from . import AppDeps


def register(app: FastAPI, deps: AppDeps) -> None:
    from showme.server import _run_best_symbol_agent_blocking

    router = APIRouter()

    @router.post("/api/agent/best-symbol")
    async def best_symbol_agent(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run the full function set over candidate symbols and rank the winner."""
        if not deps.boot_state.get("engine_attached"):
            raise HTTPException(status_code=503, detail="ShowMe engine not attached")
        return await asyncio.to_thread(_run_best_symbol_agent_blocking, payload or {})

    app.include_router(router)
