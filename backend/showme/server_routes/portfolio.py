"""Portfolio mutation routes (manual position close).

Read-only ``/api/state/positions`` lives in ``state.py``.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException

from . import AppDeps


def register(app: FastAPI, deps: AppDeps) -> None:
    from showme.server import _truthy_value

    router = APIRouter()

    @router.post("/api/portfolio/positions/{symbol}/close")
    async def portfolio_close_position(
        symbol: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        body = payload or {}
        try:
            from showme.engine.portfolio.state import PortfolioState
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=503, detail=f"portfolio state unavailable: {exc}"
            ) from exc
        dry_run = _truthy_value(body.get("dry_run", True))
        exit_price = body.get("exit_price")
        try:
            price = float(exit_price) if exit_price not in (None, "") else None
        except Exception:
            raise HTTPException(status_code=400, detail="exit_price must be numeric")
        portfolio = PortfolioState()
        if body.get("import_legacy", True):
            portfolio.import_legacy_crypto()
        record = portfolio.close_position(
            symbol,
            exit_price=price,
            reason=str(body.get("reason") or "manual_close"),
            dry_run=dry_run,
        )
        if record is None:
            raise HTTPException(status_code=404, detail=f"position not found: {symbol.upper()}")
        return {
            "ok": True,
            "dry_run": dry_run,
            "record": record,
            "remaining_positions": len(portfolio.positions),
            "closed_symbols": sorted(portfolio.closed_symbols),
        }

    app.include_router(router)
