"""Route: GET /api/portfolio/aggregate — read-only fan-out across credentials."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI

from . import AppDeps


def register(app: FastAPI, deps: AppDeps) -> None:
    router = APIRouter()

    @router.get("/api/portfolio/aggregate")
    async def aggregate_endpoint(
        include_orders: bool = False,
        credential_ids: str | None = None,
    ) -> dict[str, Any]:
        from showme.portfolio_aggregate import aggregate
        ids = None
        if credential_ids:
            ids = [s.strip() for s in credential_ids.split(",") if s.strip()]
        return await aggregate(credential_ids=ids, include_orders=include_orders)

    app.include_router(router)
