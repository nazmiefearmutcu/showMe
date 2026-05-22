"""Routes: /api/assistant/* — NL→spec parsing + explain delegation."""
from __future__ import annotations

from typing import Any
from fastapi import APIRouter, FastAPI, HTTPException
from . import AppDeps


def register(app: FastAPI, deps: AppDeps) -> None:
    router = APIRouter()

    @router.post("/api/assistant/strategy-from-text")
    async def strategy_from_text(payload: dict[str, Any]) -> dict[str, Any]:
        from showme.assistant.parser import parse_request
        from showme.strategies.spec import StrategySpec
        from showme.strategies.store import StrategyStore

        text = (payload or {}).get("text") or ""
        save = bool((payload or {}).get("save", False))
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
