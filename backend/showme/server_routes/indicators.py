"""Routes: /api/indicators/* — indicator catalog discovery."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException

from . import AppDeps

LOG = logging.getLogger("showme.server_routes.indicators")

_CATALOG = None  # lazy-loaded singleton


def _catalog_path() -> Path:
    return Path(__file__).resolve().parents[1] / "indicators" / "catalog" / "indicators.yml"


def _get_catalog():
    global _CATALOG
    if _CATALOG is None:
        from showme.indicators.catalog.loader import load_indicator_catalog
        try:
            _CATALOG = load_indicator_catalog(_catalog_path())
        except Exception as exc:  # noqa: BLE001
            LOG.warning("indicator catalog load failed: %s", exc)
            from showme.indicators.catalog.loader import IndicatorCatalog
            _CATALOG = IndicatorCatalog()
    return _CATALOG


def register(app: FastAPI, deps: AppDeps) -> None:
    router = APIRouter()

    @router.get("/api/indicators/catalog")
    async def indicators_catalog() -> list[dict[str, Any]]:
        return _get_catalog().to_payload()

    @router.get("/api/indicators/{indicator_id}")
    async def indicator_detail(indicator_id: str) -> dict[str, Any]:
        try:
            entry = _get_catalog().by_id(indicator_id)
        except KeyError:
            raise HTTPException(404, detail=f"unknown indicator: {indicator_id}")
        return entry.to_dict()

    app.include_router(router)
