"""Legacy `/api/proxy/*` route.

Round 14 replaced this with `/api/fn/{code}`; keep the stub so old clients
get a clear 410 Gone instead of a vague 404.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException

from . import AppDeps


def register(app: FastAPI, deps: AppDeps) -> None:
    router = APIRouter()

    @router.api_route("/api/proxy/{path:path}", methods=["GET", "POST", "DELETE"])
    async def proxy(path: str) -> Any:
        raise HTTPException(
            status_code=410,
            detail=f"/api/proxy/* removed in Round 14; use /api/fn/{{code}} (was: {path})",
        )

    app.include_router(router)
