"""Welcome-screen market gauge: CNN Fear & Greed read from Awareness.

``GET /api/sentiment/market-gauge`` returns the latest CNN Fear & Greed value or
``{"ok": false, "reason"}``. It never returns a default score.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, FastAPI

from showme.engine.data_sources.awareness import AwarenessUnavailable, get_awareness_client

from . import AppDeps

LOG = logging.getLogger("showme.server.market_gauge")
SOURCE_LABEL = "CNN Fear & Greed via Awareness"


def register(app: FastAPI, deps: AppDeps) -> None:
    router = APIRouter()

    @router.get("/api/sentiment/market-gauge")
    async def market_gauge() -> dict[str, Any]:
        try:
            response = await get_awareness_client().get("/sentiment/market")
        except AwarenessUnavailable as exc:
            return {"ok": False, "reason": exc.reason}
        except Exception as exc:  # noqa: BLE001 - the gauge must degrade, never 500 the welcome screen
            LOG.warning("market gauge failed: %s", exc)
            return {"ok": False, "reason": f"market gauge failed: {type(exc).__name__}"}
        data = response.data if isinstance(response.data, dict) else {}
        cnn = data.get("cnn") if isinstance(data.get("cnn"), dict) else None
        if not cnn or cnn.get("score") is None:
            return {"ok": False, "reason": "CNN Fear & Greed has no value from Awareness yet."}
        return {
            "ok": True,
            "score": cnn.get("score"),
            "rating": cnn.get("rating"),
            "as_of": cnn.get("as_of"),
            "source": SOURCE_LABEL,
            "previous_close": cnn.get("previous_close"),
        }

    app.include_router(router)
