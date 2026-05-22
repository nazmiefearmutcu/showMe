"""Routes: /api/strategies/* — CRUD + /preview."""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from fastapi import APIRouter, FastAPI, HTTPException

from . import AppDeps

LOG = logging.getLogger("showme.server_routes.strategies")


def register(app: FastAPI, deps: AppDeps) -> None:
    router = APIRouter()

    def _store():
        from showme.strategies.store import StrategyStore
        return StrategyStore.fresh()

    def _catalog_ids() -> set[str]:
        try:
            from showme.indicators.catalog.loader import load_indicator_catalog
            from pathlib import Path as _P
            cat = load_indicator_catalog(_P(__file__).resolve().parents[1] /
                                          "indicators" / "catalog" / "indicators.yml")
            return {e.id for e in cat.entries}
        except Exception as exc:  # noqa: BLE001
            LOG.warning("indicator catalog unavailable for validation: %s", exc)
            return set()

    @router.get("/api/strategies")
    async def list_strategies() -> dict[str, Any]:
        return {"records": [m.to_dict() for m in _store().list()]}

    @router.post("/api/strategies")
    async def create_strategy(payload: dict[str, Any]) -> dict[str, Any]:
        from showme.strategies.spec import StrategySpec
        # Strip server-controlled fields if client supplied them.
        for k in ("id", "created_at", "updated_at"):
            payload.pop(k, None)
        try:
            spec = StrategySpec(**payload)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, detail=f"invalid spec: {exc}")
        cat_ids = _catalog_ids()
        if cat_ids:
            try:
                spec.validate_against_catalog(cat_ids)
            except ValueError as exc:
                raise HTTPException(400, detail=str(exc))
        saved = _store().save(spec)
        return saved.model_dump()

    @router.get("/api/strategies/{strategy_id}")
    async def get_strategy(strategy_id: str) -> dict[str, Any]:
        from showme.strategies.store import UnknownStrategy
        try:
            return _store().get(strategy_id).model_dump()
        except UnknownStrategy:
            raise HTTPException(404, detail=f"unknown strategy: {strategy_id}")

    @router.put("/api/strategies/{strategy_id}")
    async def update_strategy(strategy_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        from showme.strategies.spec import StrategySpec
        from showme.strategies.store import UnknownStrategy
        try:
            existing = _store().get(strategy_id)
        except UnknownStrategy:
            raise HTTPException(404, detail=f"unknown strategy: {strategy_id}")
        # Force id to match path; drop client timestamps.
        for k in ("created_at", "updated_at"):
            payload.pop(k, None)
        payload["id"] = strategy_id
        try:
            updated = StrategySpec(**payload)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, detail=f"invalid spec: {exc}")
        cat_ids = _catalog_ids()
        if cat_ids:
            try:
                updated.validate_against_catalog(cat_ids)
            except ValueError as exc:
                raise HTTPException(400, detail=str(exc))
        saved = _store().save(updated)
        return saved.model_dump()

    @router.delete("/api/strategies/{strategy_id}")
    async def delete_strategy(strategy_id: str) -> dict[str, Any]:
        ok = _store().delete(strategy_id)
        if not ok:
            raise HTTPException(404, detail=f"unknown strategy: {strategy_id}")
        return {"ok": True}

    @router.post("/api/strategies/{strategy_id}/preview")
    async def preview_strategy(
        strategy_id: str,
        symbol: str = "BTC/USDT",
        timeframe: str = "1h",
        limit: int = 200,
    ) -> dict[str, Any]:
        """Run evaluate() against a synthetic price series of `limit` bars.

        For v1, the price series is a deterministic random walk seeded by the
        strategy id so previews are reproducible. Live exchange OHLCV fetch
        lands in a later sub-system (D bot runner already needs that path).
        """
        from showme.strategies.evaluate import evaluate
        from showme.strategies.store import UnknownStrategy
        import numpy as np
        try:
            spec = _store().get(strategy_id)
        except UnknownStrategy:
            raise HTTPException(404, detail=f"unknown strategy: {strategy_id}")
        # Seeded random walk for reproducible previews.
        seed = int.from_bytes(strategy_id.encode()[:8].ljust(8, b"\x00"), "big") % (2**31)
        rng = np.random.default_rng(seed=seed)
        close = 100 + np.cumsum(rng.normal(0, 1, limit))
        high = close + np.abs(rng.normal(0, 0.5, limit))
        low = close - np.abs(rng.normal(0, 0.5, limit))
        open_ = close + rng.normal(0, 0.3, limit)
        volume = (1000 + rng.normal(0, 100, limit)).clip(min=1)
        idx = pd.date_range("2026-01-01", periods=limit, freq="h")
        df = pd.DataFrame({"open": open_, "high": high, "low": low,
                           "close": close, "volume": volume}, index=idx)
        events = evaluate(spec, df)
        return {
            "strategy_id": strategy_id,
            "symbol": symbol,
            "timeframe": timeframe,
            "bars": limit,
            "events": [e.to_dict() for e in events],
            "source": "synthetic_random_walk",  # honest about the data source
        }

    app.include_router(router)
