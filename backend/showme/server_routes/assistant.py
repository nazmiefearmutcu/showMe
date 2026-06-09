"""Routes: /api/assistant/* — NL→spec parsing + explain delegation."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from fastapi import APIRouter, FastAPI, HTTPException
from . import AppDeps

LOG = logging.getLogger("showme.server_routes.assistant")


def _indicator_catalog_ids() -> set[str]:
    """Known indicator ids for catalog validation of generated specs.

    Mirrors ``templates.py:_indicator_catalog_ids`` so an assistant-produced
    spec is held to the SAME catalog contract the strategies create/update
    routes enforce — a generated spec must only reference real catalog
    indicators. A failed catalog load degrades to an empty set (validation
    skipped) so a broken catalog never blocks generation that the strategies
    routes would otherwise allow.
    """
    try:
        from showme.indicators.catalog.loader import load_indicator_catalog
        cat = load_indicator_catalog(
            Path(__file__).resolve().parents[1]
            / "indicators" / "catalog" / "indicators.yml"
        )
        return {e.id for e in cat.entries}
    except Exception as exc:  # noqa: BLE001
        LOG.warning("indicator catalog unavailable for validation: %s", exc)
        return set()


def register(app: FastAPI, deps: AppDeps) -> None:
    router = APIRouter()

    @router.post("/api/assistant/strategy-from-text")
    async def strategy_from_text(payload: dict[str, Any]) -> dict[str, Any]:
        from showme.assistant.parser import parse_request
        from showme.strategies.spec import StrategySpec
        from showme.strategies.store import StrategyStore

        # Faz 2 / S10 — explicit type guard. The old
        # ``(payload or {}).get("text") or ""`` path crashed with a
        # ``AttributeError: 'int' object has no attribute 'strip'`` on
        # ``text=42``, which surfaced as a sidecar 500. Now any non-string
        # ``text`` (int, float, list, dict, bool) is a 400 contract
        # violation; ``None`` and empty/whitespace strings still surface
        # the friendlier "text is required" 400.
        if not isinstance(payload, dict):
            raise HTTPException(400, detail="payload must be a JSON object")
        raw = payload.get("text")
        if raw is None:
            raise HTTPException(400, detail="text is required")
        if not isinstance(raw, str):
            raise HTTPException(400, detail="text must be a string")
        text = raw
        save = bool(payload.get("save", False))
        if not text.strip():
            raise HTTPException(400, detail="text is required")

        spec_dict, notes = parse_request(text)
        if spec_dict is None:
            return {"spec": None, "notes": notes, "saved_id": None}

        try:
            spec = StrategySpec(**spec_dict)
        except Exception as exc:  # noqa: BLE001
            return {"spec": spec_dict, "notes": notes + [f"validation failed: {exc}"],
                    "saved_id": None}

        # B5 — catalog-validate the produced spec against the SAME indicator
        # catalog STRA/the engine enforces. A catalog-invalid spec is NEVER
        # persisted (even when save=True); we return it for transparency with
        # an honest note so the user sees why nothing was saved.
        try:
            spec.validate_against_catalog(_indicator_catalog_ids())
        except ValueError as err:
            return {
                "spec": spec_dict,
                "notes": notes + [f"katalog doğrulaması başarısız: {err}"],
                "saved_id": None,
            }

        saved_id = None
        if save:
            saved = StrategyStore.fresh().save(spec)
            saved_id = saved.id

        return {
            "spec": spec.model_dump(),
            "notes": notes,
            "saved_id": saved_id,
        }

    @router.post("/api/assistant/explain-strategy")
    async def explain_strategy(payload: dict[str, Any]) -> dict[str, Any]:
        from showme.integrations.hf import explain
        from showme.strategies.store import StrategyStore, UnknownStrategy

        sid = (payload or {}).get("strategy_id")
        if not sid:
            raise HTTPException(400, detail="strategy_id is required")
        try:
            spec = StrategyStore.fresh().get(sid)
        except UnknownStrategy:
            raise HTTPException(404, detail=f"unknown strategy: {sid}")
        return {"explanation": explain(spec.model_dump())}

    app.include_router(router)
