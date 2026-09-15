"""Portfolio mutation routes (manual position add / close).

Read-only ``/api/state/positions`` lives in ``state.py``.
"""
from __future__ import annotations

import math
import re
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException

from . import AppDeps

# Same shape the quote routes accept: equities (AAPL, BRK.B), cash indices
# (^GSPC), FX pairs (EURUSD=X), futures (GC=F), 10Y yield (^TNX), crypto in
# no-slash Binance form (BTCUSDT).
_SYMBOL_RE = re.compile(r"^[A-Z0-9.^=\-]{1,24}$")


def _resolve_asset_class(requested: str, symbol: str) -> Any:
    """Validate a caller-supplied asset class or infer it from the symbol."""
    from showme.engine.core.instrument import AssetClass

    if requested:
        try:
            return AssetClass(requested)
        except ValueError:
            return None
    upper = symbol.upper()
    if upper.endswith("USDT") or upper.endswith("USDC"):
        return AssetClass.CRYPTO
    return AssetClass.EQUITY


def register(app: FastAPI, deps: AppDeps) -> None:
    from showme.server import _truthy_value

    router = APIRouter()

    @router.post("/api/portfolio/positions")
    async def portfolio_add_position(
        payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Add a manual position to the local portfolio book.

        This is the write half of the ``PORT``/``ACCT`` surfaces: before this
        route only *close* existed, so "attach a paper portfolio state" (the
        Welcome exposure panel's empty-state copy) had no way in. Validation is
        strict — a bad row must never silently corrupt ``runtime/portfolio.json``
        (the book load path treats corruption as degraded and locks saves).
        """
        body = payload or {}
        symbol = str(body.get("symbol") or "").strip().upper()
        if not symbol or not _SYMBOL_RE.match(symbol):
            raise HTTPException(
                status_code=400,
                detail="symbol is required and must match [A-Z0-9.^=-], max 24 chars",
            )
        try:
            quantity = float(body.get("quantity"))
            avg_cost = float(body.get("avg_cost"))
        except Exception:
            raise HTTPException(
                status_code=400, detail="quantity and avg_cost must be numeric"
            )
        if not (math.isfinite(quantity) and math.isfinite(avg_cost)):
            raise HTTPException(
                status_code=400, detail="quantity and avg_cost must be finite numbers"
            )
        if quantity <= 0:
            raise HTTPException(
                status_code=400, detail="quantity must be a positive number"
            )
        if avg_cost < 0:
            raise HTTPException(
                status_code=400, detail="avg_cost must be a non-negative number"
            )
        account = str(body.get("account") or "main").strip() or "main"
        if len(account) > 32:
            raise HTTPException(
                status_code=400, detail="account must be 32 characters or fewer"
            )
        notes = str(body.get("notes") or "").strip()[:280]
        requested_class = str(body.get("asset_class") or "").strip().upper()
        asset_class = _resolve_asset_class(requested_class, symbol)
        if asset_class is None:
            raise HTTPException(
                status_code=400, detail=f"unsupported asset_class: {requested_class}"
            )
        currency = str(body.get("currency") or "").strip().upper()
        try:
            from showme.engine.core.instrument import AssetClass, Instrument
            from showme.engine.portfolio.state import PortfolioPosition, PortfolioState
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=503, detail=f"portfolio state unavailable: {exc}"
            ) from exc
        portfolio = PortfolioState()
        if body.get("import_legacy", True):
            portfolio.import_legacy_crypto()
        if portfolio.degraded:
            # Writes would be refused by save(); fail loudly instead of
            # returning ok on a position that never persists.
            raise HTTPException(
                status_code=503,
                detail=f"portfolio book is degraded: {portfolio.degraded_reason}",
            )
        if any(p.instrument.symbol.upper() == symbol for p in portfolio.positions):
            raise HTTPException(
                status_code=409,
                detail=f"position already exists: {symbol} (close it before re-adding)",
            )
        if not currency:
            currency = "USDT" if asset_class == AssetClass.CRYPTO else "USD"
        instrument = Instrument(symbol=symbol, asset_class=asset_class, currency=currency)
        position = PortfolioPosition(
            instrument=instrument,
            quantity=quantity,
            avg_cost=avg_cost,
            currency=currency,
            notes=notes,
            account=account,
        )
        portfolio.add_position(position)
        return {
            "ok": True,
            "position": position.to_dict(),
            "positions_count": len(portfolio.positions),
            "degraded": bool(portfolio.degraded),
            "degraded_reason": portfolio.degraded_reason or None,
        }

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
        # F8: float("nan")/float("inf") parse fine but would book realized PnL
        # as NaN and serialize as an invalid JSON token. Require a finite,
        # non-negative price.
        if price is not None and not (math.isfinite(price) and price >= 0):
            raise HTTPException(
                status_code=400, detail="exit_price must be a finite, non-negative number"
            )
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
            # F5: surface degraded state so callers know mutations are NOT
            # being persisted while the on-disk book failed to load.
            "degraded": bool(portfolio.degraded),
            "degraded_reason": portfolio.degraded_reason or None,
        }

    app.include_router(router)
