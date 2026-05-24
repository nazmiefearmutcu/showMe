"""X (Twitter) sentiment / instant-events routes."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Query

from . import AppDeps
from ._models import XAnalyzeBody, XClassifyBody

LOG = logging.getLogger("showme.server.xai")

# QA-fix: bound every /api/x/* handler so a stalled scraper or model load
# can never hang the FastAPI worker indefinitely. Tunable via env for ops.
XAI_HANDLER_TIMEOUT_SECONDS = float(os.environ.get("SHOWME_XAI_TIMEOUT_SECONDS", "30"))


def register(app: FastAPI, deps: AppDeps) -> None:
    router = APIRouter()

    @router.get("/api/x/health")
    async def x_health() -> dict[str, Any]:
        from showme.x_analysis import XAnalyzer

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(XAnalyzer.instance().health),
                timeout=XAI_HANDLER_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            LOG.warning("x_health timed out after %.0fs", XAI_HANDLER_TIMEOUT_SECONDS)
            return {
                "ok": False,
                "model_loaded": False,
                "error": f"timed out after {XAI_HANDLER_TIMEOUT_SECONDS:.0f}s",
            }

    @router.post("/api/x/analyze")
    async def x_analyze(payload: XAnalyzeBody | None = None) -> dict[str, Any]:
        from showme.x_analysis import XAnalyzer

        # Legacy: support `query` from older UI builds; promote to symbol/topic.
        # `ui/src/lib/xai.ts:analyzeXTopic` sends {query: "..."} which used to
        # be silently dropped by ConfigDict(extra="ignore") on XAnalyzeBody,
        # causing every Run press to fail HTTP 400. We now accept all three.
        # See SHOWME_BUGHUNT 2026-05-24 Bug #10b.
        body = payload or XAnalyzeBody()
        query = (body.topic or body.symbol or (body.query or "")).strip()
        if not query:
            raise HTTPException(status_code=400, detail="query or symbol is required")
        # Resolve limit precedence: explicit `limit` field > len(posts) > default 120.
        if body.limit is not None:
            limit = max(1, min(int(body.limit), 500))
        elif body.posts:
            limit = max(1, min(len(body.posts), 500))
        else:
            limit = 120
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    XAnalyzer.instance().analyze_topic,
                    query,
                    limit,
                    body.since,
                    body.until,
                    body.lang or "en",
                ),
                timeout=XAI_HANDLER_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            LOG.warning("x_analyze timed out after %.0fs query=%s", XAI_HANDLER_TIMEOUT_SECONDS, query)
            return {
                "ok": False,
                "error": f"timed out after {XAI_HANDLER_TIMEOUT_SECONDS:.0f}s",
                "query": query,
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            LOG.warning("x_analyze failed: %s", exc)
            return {"ok": False, "error": str(exc), "query": query}

    @router.post("/api/x/classify")
    async def x_classify(payload: XClassifyBody) -> dict[str, Any]:
        from showme.x_analysis import XAnalyzer

        try:
            results = await asyncio.wait_for(
                asyncio.to_thread(XAnalyzer.instance().classify, payload.texts),
                timeout=XAI_HANDLER_TIMEOUT_SECONDS,
            )
            return {
                "ok": True,
                "results": results,
                "labels": XAnalyzer.instance().label_options(),
            }
        except asyncio.TimeoutError:
            LOG.warning("x_classify timed out after %.0fs", XAI_HANDLER_TIMEOUT_SECONDS)
            return {
                "ok": False,
                "error": f"timed out after {XAI_HANDLER_TIMEOUT_SECONDS:.0f}s",
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
            return await asyncio.wait_for(
                asyncio.to_thread(
                    XAnalyzer.instance().symbol_chip,
                    symbol,
                    limit,
                    since,
                    lang,
                ),
                timeout=XAI_HANDLER_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            LOG.warning("x_symbol_chip timed out after %.0fs symbol=%s", XAI_HANDLER_TIMEOUT_SECONDS, symbol)
            return {
                "ok": False,
                "symbol": symbol,
                "error": f"timed out after {XAI_HANDLER_TIMEOUT_SECONDS:.0f}s",
            }
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
            return await asyncio.wait_for(
                asyncio.to_thread(
                    XAnalyzer.instance().analyze_topic_as_instant_events,
                    symbol,
                    query,
                    limit,
                    since,
                    lang,
                ),
                timeout=XAI_HANDLER_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            LOG.warning("x_instant_events timed out after %.0fs", XAI_HANDLER_TIMEOUT_SECONDS)
            return {
                "ok": False,
                "events": [],
                "error": f"timed out after {XAI_HANDLER_TIMEOUT_SECONDS:.0f}s",
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            LOG.warning("x_instant_events failed: %s", exc)
            return {"ok": False, "events": [], "error": str(exc)}

    app.include_router(router)
