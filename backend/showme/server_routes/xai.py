"""X (Twitter) sentiment / instant-events routes."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Query

from showme.engine.services.stocktwits_sentiment import (
    fetch_symbol_chip,
    to_stocktwits_symbol,
)

from . import AppDeps
from ._models import XAnalyzeBody, XClassifyBody

LOG = logging.getLogger("showme.server.xai")

# QA-fix: bound every /api/x/* handler so a stalled scraper or model load
# can never hang the FastAPI worker indefinitely. Tunable via env for ops.
XAI_HANDLER_TIMEOUT_SECONDS = float(os.environ.get("SHOWME_XAI_TIMEOUT_SECONDS", "30"))

# ---- XSEN route-level Stocktwits fallback ---------------------------------
# The X scraper chain (search-engine scrape + bundled RoBERTa model) can be
# dead on a host while a live source still exists: Stocktwits' public
# author-tagged Bullish/Bearish stream (see
# ``showme.engine.services.stocktwits_sentiment``). Only ticker-shaped
# queries may ride that fallback — free text ("solar stocks") keeps the
# honest X empty/503 path unchanged.
_XSEN_TICKER_RE = re.compile(r"[A-Za-z0-9.^=-]{1,12}")

_XSEN_FALLBACK_WARNING = (
    "X scraper chain unavailable — live Stocktwits labels (author-tagged "
    "Bullish/Bearish) shown instead; emotion/topic heads need the local "
    "model bundle."
)


def _xsen_ticker_like(query: str) -> bool:
    return bool(_XSEN_TICKER_RE.fullmatch(query.strip()))


def _xsen_empty_payload(query: str) -> dict[str, Any]:
    """Honest zero-post shape for the dead-chain fast path."""
    return {
        "query": query,
        "post_count": 0,
        "scrape_seconds": 0.0,
        "warning": "x sentiment chain cooling down — no posts fetched",
    }


async def _xsen_stocktwits_fallback(query: str) -> dict[str, Any] | None:
    """Serve a ticker-like query from the live Stocktwits stream.

    Returns an analyze-shaped payload the XSEN pane renders, or ``None``
    when Stocktwits has no labelled posts (fail-closed — never fabricate a
    verdict from noise).
    """
    if to_stocktwits_symbol(query) is None:
        return None
    started = time.monotonic()
    chip = await asyncio.to_thread(fetch_symbol_chip, query)
    if not chip:
        return None
    return {
        "query": query,
        "post_count": chip["post_count"],
        "scrape_seconds": round(time.monotonic() - started, 2),
        "fetched_at": chip.get("fetched_at"),
        "device": "stocktwits",
        "mood": chip["mood"],
        "scores": {
            "bullish_score_avg": chip["bullish_score"],
            "bullish_score_engagement_weighted": chip["bullish_score"],
            "confidence": chip["confidence"],
        },
        "distributions": chip["distributions"],
        "dominant": {"sentiment": chip["mood"], "emotion": "", "topic": ""},
        "examples": chip["examples"],
        "summary": chip["summary"],
        "summary_en": chip["summary"],
        "summary_tr": chip.get("summary_tr", chip["summary"]),
        "warning": _XSEN_FALLBACK_WARNING,
        "source": "stocktwits",
    }


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
        from showme import x_analysis
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

        ticker_like = _xsen_ticker_like(query)
        if not x_analysis._x_chain_available():
            # Dead-chain fast path (circuit breaker): every X attempt would
            # pay external timeouts. Ticker-shaped queries go straight to the
            # live Stocktwits labels; free text (never routed to the
            # fallback) gets the honest empty payload without the wait.
            if ticker_like:
                fallback = await _xsen_stocktwits_fallback(query)
                if fallback is not None:
                    return fallback
            return _xsen_empty_payload(query)

        try:
            result = await asyncio.wait_for(
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
            # Model bundle missing — the classifier can never score scraped
            # posts on this host. Cool the chain down (analyzer doctrine) and
            # let the live Stocktwits labels serve ticker queries; free text
            # keeps the legacy 503 so the honest error is not masked.
            x_analysis._note_x_chain_failure(
                f"model bundle missing: {exc}",
                cooldown=x_analysis.X_MODEL_MISSING_COOLDOWN_SECONDS,
            )
            if ticker_like:
                fallback = await _xsen_stocktwits_fallback(query)
                if fallback is not None:
                    return fallback
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            LOG.warning("x_analyze failed: %s", exc)
            return {"ok": False, "error": str(exc), "query": query}

        # Empty/insufficient X result for a ticker means the chain is
        # effectively down for this query even though it did not raise. Cool
        # it down and let the live labels take over when Stocktwits has them;
        # otherwise return the original honest payload untouched.
        if ticker_like and (
            result.get("post_count") == 0
            or result.get("verdict") == "insufficient_data"
        ):
            x_analysis._note_x_chain_failure(str(result.get("warning") or "no posts"))
            fallback = await _xsen_stocktwits_fallback(query)
            if fallback is not None:
                return fallback
        return result

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
