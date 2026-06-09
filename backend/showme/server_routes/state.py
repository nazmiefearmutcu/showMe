"""Read-only state routes: positions, trades, migrations, LLM cost."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, FastAPI, Query

from . import AppDeps


def register(app: FastAPI, deps: AppDeps) -> None:
    router = APIRouter()

    @router.get("/api/state/positions")
    async def state_positions() -> dict[str, Any]:
        from showme.state_api import list_positions
        out = list_positions()
        return {"rows": out.rows, "total": out.total, "source": out.source}

    @router.get("/api/state/trades")
    async def state_trades(
        limit: int = Query(200, ge=1, le=1000),
        symbol: str | None = Query(None, max_length=32, pattern=r"^[A-Z0-9._:=\-]+$"),
    ) -> dict[str, Any]:
        from showme.state_api import list_trades
        out = list_trades(limit=limit, symbol=symbol)
        # Freshness stamp for the TXNS blotter's "Son güncelleme" indicator.
        # Stamped at the route layer so the framework-light StateRead dataclass
        # stays unchanged. This marks when THIS response was served, not when
        # the underlying rows were imported (those carry their own imported_at).
        return {
            "rows": out.rows,
            "total": out.total,
            "source": out.source,
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        }

    @router.get("/api/state/migrations")
    async def state_migrations(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
        from showme.state_api import list_migrations
        out = list_migrations(limit=limit)
        return {"rows": out.rows, "total": out.total, "source": out.source}

    @router.get("/api/llm/cost")
    async def llm_cost() -> dict[str, Any]:
        """Expose today's LLM spend so the UI can render a live cost pill."""
        from showme.llm import (
            CostLedger, build_default_providers, daily_cap_usd,
        )
        led = CostLedger.load()
        cap = daily_cap_usd()
        spent = led.today_spend()
        providers = build_default_providers()
        return {
            "today_usd": round(spent, 6),
            "cap_usd": cap,
            "remaining_usd": max(0.0, cap - spent),
            "exhausted": spent >= cap,
            "providers": [{"name": p.name, "model": p.model} for p in providers],
            "entries": [e.to_dict() for e in led.entries[-50:]],
        }

    app.include_router(router)
