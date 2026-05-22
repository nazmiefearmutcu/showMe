"""Routes: /api/templates/* — list, get, instantiate."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException

from . import AppDeps

LOG = logging.getLogger("showme.server_routes.templates")


_CATALOG = None


def _catalog_path() -> Path:
    return Path(__file__).resolve().parents[1] / "templates" / "catalog" / "templates.yml"


def _get_catalog():
    global _CATALOG
    if _CATALOG is None:
        from showme.templates.loader import load_template_catalog
        try:
            _CATALOG = load_template_catalog(_catalog_path())
        except Exception as exc:  # noqa: BLE001
            LOG.warning("template catalog unavailable: %s", exc)
            from showme.templates.loader import TemplateCatalog
            _CATALOG = TemplateCatalog()
    return _CATALOG


def register(app: FastAPI, deps: AppDeps) -> None:
    router = APIRouter()

    @router.get("/api/templates")
    async def templates_list() -> list[dict[str, Any]]:
        return _get_catalog().to_payload()

    @router.get("/api/templates/{template_id}")
    async def templates_detail(template_id: str) -> dict[str, Any]:
        try:
            return _get_catalog().by_id(template_id).to_dict()
        except KeyError:
            raise HTTPException(404, detail=f"unknown template: {template_id}")

    @router.post("/api/templates/{template_id}/instantiate")
    async def templates_instantiate(
        template_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from showme.strategies.spec import StrategySpec
        from showme.strategies.store import StrategyStore

        payload = payload or {}
        try:
            entry = _get_catalog().by_id(template_id)
        except KeyError:
            raise HTTPException(404, detail=f"unknown template: {template_id}")

        body = dict(entry.spec_template)
        if "name" in payload and payload["name"]:
            body["name"] = str(payload["name"])
        if "symbol" in payload and payload["symbol"]:
            af = dict(body.get("asset_filter") or {})
            af["symbols"] = [str(payload["symbol"])]
            body["asset_filter"] = af
        # Strip server-controlled fields if they snuck in.
        for k in ("id", "created_at", "updated_at"):
            body.pop(k, None)

        try:
            spec = StrategySpec(**body)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, detail=f"invalid template spec: {exc}")
        saved = StrategyStore.fresh().save(spec)
        return {
            "template_id": template_id,
            "strategy": saved.model_dump(),
        }

    app.include_router(router)
