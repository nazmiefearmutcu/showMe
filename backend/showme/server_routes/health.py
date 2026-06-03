"""Health-probe routes: /api/health, /api/sidecar/info, /api/sidecar/ticker.

The X-Sentiment ``/api/x/health`` lives in ``xai.py`` because it shares the
RoBERTa singleton lifecycle with the other X routes.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, FastAPI

from . import AppDeps

LOG = logging.getLogger("showme.server.health")


def register(app: FastAPI, deps: AppDeps) -> None:
    from showme.server import _load_function_index, _safe_import

    router = APIRouter()

    @router.get("/api/health")
    async def health() -> dict[str, Any]:
        # Per ARCH-08 P0: surface registration health so a silently-dropped
        # function module shows up as `degraded=True` instead of "ok".
        expected_min = 138
        function_count = 0
        try:
            function_count = len(_load_function_index())
        except Exception as exc:  # noqa: BLE001
            LOG.warning("health: function index load failed: %s", exc)
        degraded = function_count < expected_min
        return {
            "ok": True,
            "engine": deps.boot_state,
            "function_count": function_count,
            "expected_min": expected_min,
            "degraded": degraded,
        }

    @router.get("/api/sidecar/info")
    async def sidecar_info() -> dict[str, Any]:
        return {
            "version": "0.1.1",
            "python": sys.version,
            "platform": sys.platform,
            "engine": deps.boot_state,
        }

    @router.get("/api/sidecar/ticker")
    async def sidecar_ticker() -> dict[str, Any]:
        """Compact live summary consumed by the Rust tray.

        Every nested fetch is best-effort: failures append to warnings,
        the rest of the payload still ships.
        """
        out: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "warnings": [],
            "bot": {"running": False, "cycle": None, "mode": None},
            "portfolio": {"n_positions": 0, "daily_pnl": None, "market_value": None},
            "alerts": {"active": 0, "fired_today": 0},
        }
        try:
            bot_mod = _safe_import("showme.engine.services.bot_service")
            if bot_mod and hasattr(bot_mod, "get_state"):
                state = bot_mod.get_state()
                out["bot"] = {
                    "running": bool(state.get("running", False)),
                    "cycle": state.get("cycle"),
                    "mode": state.get("mode") or "paper",
                }
        except Exception as exc:  # noqa: BLE001
            out["warnings"].append(f"bot_service: {exc}")
        try:
            ps_mod = _safe_import("showme.engine.portfolio.state")
            if ps_mod and hasattr(ps_mod, "PortfolioState"):
                ps = ps_mod.PortfolioState()
                positions = getattr(ps, "positions", []) or []
                out["portfolio"]["n_positions"] = len(positions)
                mv = sum(
                    float(getattr(p, "quantity", 0))
                    * float(getattr(p, "avg_cost", 0))
                    for p in positions
                )
                out["portfolio"]["market_value"] = mv
        except Exception as exc:  # noqa: BLE001
            out["warnings"].append(f"portfolio: {exc}")
        try:
            ae = _safe_import("showme.engine.services.alert_engine")
            if ae and hasattr(ae, "list_alerts"):
                items = ae.list_alerts() or []
                out["alerts"]["active"] = sum(1 for a in items if a.get("active"))
                out["alerts"]["fired_today"] = sum(
                    1 for a in items if a.get("fired_today")
                )
        except Exception as exc:  # noqa: BLE001
            out["warnings"].append(f"alert_engine: {exc}")
        return out

    app.include_router(router)
