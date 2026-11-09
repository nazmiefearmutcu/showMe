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
        # M-6: a CNN provider that Awareness reports down or degraded keeps its last value but is flagged stale,
        # so the Welcome card can say the reading may not be current.
        failing = next(
            (
                p for p in response.providers
                if "cnn" in str(p.get("provider", "")).lower() and p.get("status") in {"down", "degraded"}
            ),
            None,
        )
        crypto = data.get("crypto") if isinstance(data.get("crypto"), dict) else {}
        crypto_score = crypto.get("score") if isinstance(crypto.get("score"), (int, float)) else None
        return {
            "ok": True,
            "score": cnn.get("score"),
            "rating": cnn.get("rating"),
            "as_of": cnn.get("as_of"),
            "source": SOURCE_LABEL,
            "previous_close": cnn.get("previous_close"),
            "stale": failing is not None,
            "provider_status": (
                {
                    "provider": failing.get("provider"),
                    "status": failing.get("status"),
                    "last_ok_at": failing.get("last_ok_at"),
                    "last_error": failing.get("last_error"),
                }
                if failing is not None else None
            ),
            # Crypto Fear & Greed for the Welcome footnote; null when Awareness has no crypto reading.
            "crypto_score": crypto_score,
            "crypto_rating": crypto.get("rating") if crypto_score is not None else None,
        }

    app.include_router(router)
