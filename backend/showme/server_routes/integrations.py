"""Routes: /api/integrations/* — GitHub search + HF classify/explain."""
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, FastAPI, HTTPException
from . import AppDeps


def register(app: FastAPI, deps: AppDeps) -> None:
    router = APIRouter()

    @router.get("/api/integrations/github/search")
    async def github_search(q: str, language: str | None = None, limit: int = 10) -> dict[str, Any]:
        # QA-fix: expose `metadata.degraded` + `metadata.degraded_reason` so
        # the UI no longer silently shows "0 hits" for anon-blocked queries.
        from showme.integrations.github import search_code_with_status
        if not q or not q.strip():
            raise HTTPException(400, detail="q is required")
        hits, status = await search_code_with_status(
            q, language=language, limit=min(max(limit, 1), 30)
        )
        metadata: dict[str, Any] = {"status": status}
        if status != "ok":
            metadata["degraded"] = True
            metadata["degraded_reason"] = {
                "anon_blocked": "github_anon_blocked",
                "rate_limited": "github_rate_limited",
                "network": "github_network_error",
                "other": "github_unexpected_error",
            }.get(status, "github_unknown")
        return {
            "q": q,
            "language": language,
            "hits": [h.to_dict() for h in hits],
            "metadata": metadata,
        }

    @router.post("/api/integrations/hf/classify")
    async def hf_classify(payload: dict[str, Any]) -> dict[str, Any]:
        from showme.integrations.hf import classify
        text = (payload or {}).get("text") or ""
        if not text.strip():
            raise HTTPException(400, detail="text is required")
        return classify(text)

    @router.post("/api/integrations/hf/explain")
    async def hf_explain(payload: dict[str, Any]) -> dict[str, Any]:
        from showme.integrations.hf import explain
        from showme.strategies.store import StrategyStore, UnknownStrategy
        body = payload or {}
        if "strategy_id" in body:
            try:
                spec = StrategyStore.fresh().get(body["strategy_id"])
            except UnknownStrategy:
                raise HTTPException(404, detail="unknown strategy")
            return {"explanation": explain(spec.model_dump())}
        if "spec" in body:
            return {"explanation": explain(body["spec"])}
        raise HTTPException(400, detail="provide either strategy_id or spec")

    app.include_router(router)
