"""Routes: /api/manifest, /api/manifest/{code}.

Read-only listing of every registered FunctionManifest. Seeds are loaded
lazily on first request so import-order is not load-bearing during boot.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException

from . import AppDeps

LOG = logging.getLogger("showme.server_routes.manifest")


_SEEDS_LOADED = False


def _ensure_seeds_loaded() -> None:
    """Import every bundled seed module exactly once."""
    global _SEEDS_LOADED
    if _SEEDS_LOADED:
        return
    from showme.manifest import load_seeds

    try:
        load_seeds()
    except ValueError as exc:
        # Duplicate registration during a test reload — log and continue.
        LOG.warning("manifest seeds reload: %s", exc)
    _SEEDS_LOADED = True


def register(app: FastAPI, deps: AppDeps) -> None:
    router = APIRouter()

    @router.get("/api/manifest")
    async def list_manifests() -> list[dict[str, Any]]:
        from showme.manifest import REGISTRY

        _ensure_seeds_loaded()
        return [m.model_dump(mode="json") for m in REGISTRY.all()]

    @router.get("/api/manifest/{code}")
    async def get_manifest(code: str) -> dict[str, Any]:
        from showme.manifest import REGISTRY

        _ensure_seeds_loaded()
        try:
            entry = REGISTRY.get(code.upper())
        except KeyError:
            raise HTTPException(404, detail=f"unknown manifest code: {code}")
        return entry.model_dump(mode="json")

    app.include_router(router)


__all__ = ["register"]
