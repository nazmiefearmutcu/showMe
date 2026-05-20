"""X (Twitter) sentiment / instant-events routes."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Query

from . import AppDeps
from ._models import XAnalyzeBody, XClassifyBody

LOG = logging.getLogger("showme.server.xai")


def register(app: FastAPI, deps: AppDeps) -> None:
    router = APIRouter()

    @router.get("/api/x/health")
    async def x_health() -> dict[str, Any]:
        from showme.x_analysis import XAnalyzer

        return await asyncio.to_thread(XAnalyzer.instance().health)

    @router.post("/api/x/analyze")
    async def x_analyze(payload: XAnalyzeBody | None = None) -> dict[str, Any]:
        from showme.x_analysis import XAnalyzer

        # Permit legacy callers that pass {"query": "..."} alongside the
        # documented {"symbol", "topic"} shape; we promote either to ``query``.
        body = payload or XAnalyzeBody()
        query = (body.topic or body.symbol or "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="query or symbol is required")
        limit = max(1, min(len(body.posts) if body.posts else 120, 500))
        try:
            return await asyncio.to_thread(
                XAnalyzer.instance().analyze_topic,
                query,
                limit,
                None,
                None,
                body.lang or "en",
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            LOG.warning("x_analyze failed: %s", exc)
            return {"ok": False, "error": str(exc), "query": query}

    @router.post("/api/x/classify")
    async def x_classify(payload: XClassifyBody) -> dict[str, Any]:
        from showme.x_analysis import XAnalyzer

        try:
            return {
                "ok": True,
                "results": await asyncio.to_thread(
                    XAnalyzer.instance().classify, payload.texts
                ),
                "labels": XAnalyzer.instance().label_options(),
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            LOG.warning("x_classify failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    @router.get("/api/x/symbol_chip")
    async def x_symbol_chip(
        symbol: str = Query(..., max_length=32, pattern=r"^[A-Za-z0-9._:=\-]+$"),
        limit: int = Query(60, ge=1, le=200),
        since: str | None = Query(None, max_length=32),
        lang: str | None = Query("en", max_length=8),
    ) -> dict[str, Any]:
        from showme.x_analysis import XAnalyzer

        try:
            return await asyncio.to_thread(
                XAnalyzer.instance().symbol_chip,
                symbol,
                limit,
                since,
                lang,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            LOG.warning("x_symbol_chip failed: %s", exc)
            return {"ok": False, "symbol": symbol, "error": str(exc)}

    @router.get("/api/x/instant_events")
    async def x_instant_events(
        symbol: str | None = Query(None, max_length=32),
        query: str | None = Query(None, max_length=200),
        limit: int = Query(60, ge=1, le=200),
        since: str | None = Query(None, max_length=32),
        lang: str | None = Query("en", max_length=8),
    ) -> dict[str, Any]:
        from showme.x_analysis import XAnalyzer

        try:
            return await asyncio.to_thread(
                XAnalyzer.instance().analyze_topic_as_instant_events,
                symbol,
                query,
                limit,
                since,
                lang,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            LOG.warning("x_instant_events failed: %s", exc)
            return {"ok": False, "events": [], "error": str(exc)}

    app.include_router(router)
