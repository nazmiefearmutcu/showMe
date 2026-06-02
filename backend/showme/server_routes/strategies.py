"""Routes: /api/strategies/* — CRUD + /preview + /dependents + cascade DELETE."""
from __future__ import annotations

import logging
import math
from typing import Any

import pandas as pd
from fastapi import APIRouter, FastAPI, HTTPException, Query

from . import AppDeps

LOG = logging.getLogger("showme.server_routes.strategies")


# Faz 2 / M-3 — Hard guard against indicator-array DoS at the route
# layer. We enforce it here so the constraint applies regardless of
# whether the StrategySpec model is later relaxed by a different phase.
_MAX_INDICATORS = 64


def _enforce_indicator_cap(payload: dict[str, Any]) -> None:
    inds = payload.get("indicators")
    if isinstance(inds, list) and len(inds) > _MAX_INDICATORS:
        raise HTTPException(
            400,
            detail=f"too many indicators: {len(inds)} > {_MAX_INDICATORS}",
        )


# C-API-1 (BOT_AUDIT_REPORT.md): the Position model in ``strategies/spec.py``
# does not validate ``sizing_value`` numerically, so ``-100`` /``+200``-as-
# risk-pct / NaN / inf bodies persist and reach the live runner. We guard at
# the route layer so the constraint holds regardless of what the model accepts.
# FIX_CONTRACT.md C1 documents the runtime semantics (mirrors sizing.py).
_VALID_SIZING_KINDS = ("fixed_quote", "fixed_base", "risk_pct")


def _enforce_position_sizing(payload: dict[str, Any]) -> None:
    pos = payload.get("position")
    if not isinstance(pos, dict):
        return
    if "sizing_value" in pos:
        try:
            sv = float(pos["sizing_value"])
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                400, detail=f"position.sizing_value must be numeric: {exc}",
            )
        if not math.isfinite(sv):
            raise HTTPException(
                400, detail="position.sizing_value must be a finite number",
            )
        if sv <= 0:
            raise HTTPException(
                400, detail="position.sizing_value must be > 0",
            )
        kind = pos.get("sizing_kind", "fixed_quote")
        if kind not in _VALID_SIZING_KINDS:
            raise HTTPException(
                400,
                detail=f"position.sizing_kind must be one of {_VALID_SIZING_KINDS}",
            )
        if kind == "risk_pct" and sv > 100.0:
            raise HTTPException(
                400, detail="position.sizing_value must be <= 100 when sizing_kind='risk_pct'",
            )
    for fld in ("stop_loss_pct", "take_profit_pct"):
        if fld in pos and pos[fld] is not None:
            try:
                v = float(pos[fld])
            except (TypeError, ValueError):
                raise HTTPException(400, detail=f"position.{fld} must be numeric")
            if not math.isfinite(v) or v < 0:
                raise HTTPException(
                    400, detail=f"position.{fld} must be >= 0 and finite",
                )


def _bot_refs_for_strategy(strategy_id: str) -> list[Any]:
    """Return BotMeta entries that reference ``strategy_id`` (used by cascade)."""
    from showme.bots.store import BotStore
    return [m for m in BotStore.fresh().list() if m.strategy_id == strategy_id]


async def _cascade_disable_bots(bot_ids: list[str]) -> list[dict[str, str]]:
    """Best-effort cascade-disable for each bot id. Returns a per-id status list.

    Mirrors the FIX_CONTRACT.md C3 cascade contract. Errors are logged and
    returned in the response so the UI can surface partial failures instead
    of pretending everything is clean.
    """
    from showme.bots.lifespan import get_runner
    from showme.bots.store import BotStore
    results: list[dict[str, str]] = []
    runner = get_runner()
    store = BotStore.fresh()
    for bid in bot_ids:
        try:
            await runner.disable(bid, store)
            # H-API-2 — clean up the runner's per-bot lock so the map
            # cannot grow unbounded across cascade-delete cycles. The
            # runner's own DELETE flow doesn't reach here; this is the
            # cascade path's hygiene.
            locks = getattr(runner, "_locks", None)
            if isinstance(locks, dict):
                locks.pop(bid, None)
            results.append({"bot_id": bid, "status": "disabled"})
        except Exception as exc:  # noqa: BLE001
            LOG.warning("cascade disable failed for bot %s: %s", bid, exc)
            results.append({"bot_id": bid, "status": "error", "error": str(exc)})
    return results


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
        if not isinstance(payload, dict):
            raise HTTPException(400, detail="payload must be a JSON object")
        # Strip server-controlled fields if client supplied them.
        for k in ("id", "created_at", "updated_at"):
            payload.pop(k, None)
        # Faz 2 / M-3 — array DoS guard before pydantic crunches it.
        _enforce_indicator_cap(payload)
        # C-API-1 — reject negative / NaN / over-100 sizing at the route layer.
        _enforce_position_sizing(payload)
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
        try:
            saved = _store().save(spec)
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc))
        return saved.model_dump()

    @router.get("/api/strategies/{strategy_id}")
    async def get_strategy(strategy_id: str) -> dict[str, Any]:
        from showme.strategies.store import UnknownStrategy
        try:
            return _store().get(strategy_id).model_dump()
        except UnknownStrategy:
            raise HTTPException(404, detail=f"unknown strategy: {strategy_id}")
        except ValueError:
            # Faz 2 / S7 — invalid id shape (path traversal) → 400.
            raise HTTPException(400, detail="invalid strategy id")

    @router.put("/api/strategies/{strategy_id}")
    async def update_strategy(strategy_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        from showme.strategies.spec import StrategySpec
        from showme.strategies.store import UnknownStrategy
        if not isinstance(payload, dict):
            raise HTTPException(400, detail="payload must be a JSON object")
        try:
            _store().get(strategy_id)
        except UnknownStrategy:
            raise HTTPException(404, detail=f"unknown strategy: {strategy_id}")
        except ValueError:
            raise HTTPException(400, detail="invalid strategy id")
        # Force id to match path; drop client timestamps.
        for k in ("created_at", "updated_at"):
            payload.pop(k, None)
        payload["id"] = strategy_id
        # Faz 2 / M-3 — array DoS guard before pydantic crunches it.
        _enforce_indicator_cap(payload)
        # C-API-1 — reject negative / NaN / over-100 sizing at the route layer.
        _enforce_position_sizing(payload)
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
        try:
            saved = _store().save(updated)
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc))
        return saved.model_dump()

    @router.get("/api/strategies/{strategy_id}/dependents")
    async def strategy_dependents(strategy_id: str) -> dict[str, Any]:
        """List bots that reference ``strategy_id``.

        Used by the Strategy editor UI (FIX_CONTRACT.md C9) so the
        confirmation dialog can show "X bot etkilenecek" before the
        cascade-delete POST.
        """
        # Validate the id shape early — keeps the response deterministic
        # regardless of whether the strategy exists.
        try:
            from showme.strategies.store import _validate_id as _vid
            _vid(strategy_id)
        except ValueError:
            raise HTTPException(400, detail="invalid strategy id")
        refs = _bot_refs_for_strategy(strategy_id)
        return {
            "strategy_id": strategy_id,
            "bot_count": len(refs),
            "bot_ids": [m.id for m in refs],
            "bots": [
                {
                    "id": m.id, "symbol": m.symbol, "mode": m.mode,
                    "enabled": m.enabled,
                }
                for m in refs
            ],
        }

    @router.delete("/api/strategies/{strategy_id}")
    async def delete_strategy(
        strategy_id: str,
        force: bool = Query(False),
    ) -> dict[str, Any]:
        """Delete a strategy. Without ``force=true``, refuses with 409 when
        any bot still references the strategy. With ``force=true``, the
        referencing bots are cascade-disabled (their store records flipped
        to ``enabled=False`` + their asyncio task cancelled) BEFORE the
        strategy file is removed. C-INT-2 / FIX_CONTRACT.md C3.
        """
        # Validate id early so 400 wins over 404/409 race.
        try:
            from showme.strategies.store import _validate_id as _vid
            _vid(strategy_id)
        except ValueError:
            # Faz 2 / S7 — block ``DELETE /api/strategies/..%2F..%2Fetc%2Fpasswd``.
            raise HTTPException(400, detail="invalid strategy id")
        # FK check: refuse the destructive op when bots still reference it.
        refs = _bot_refs_for_strategy(strategy_id)
        if refs and not force:
            raise HTTPException(
                409,
                detail={
                    "error": "strategy_has_bots",
                    "bot_count": len(refs),
                    "bot_ids": [m.id for m in refs[:10]],
                    "hint": "Use ?force=true to cascade-disable referencing bots.",
                },
            )
        cascade_results: list[dict[str, str]] = []
        if refs and force:
            cascade_results = await _cascade_disable_bots([m.id for m in refs])
        try:
            ok = _store().delete(strategy_id)
        except ValueError:
            raise HTTPException(400, detail="invalid strategy id")
        if not ok:
            raise HTTPException(404, detail=f"unknown strategy: {strategy_id}")
        return {
            "ok": True,
            "cascade": cascade_results,
            "bots_affected": len(cascade_results),
        }

    @router.post("/api/strategies/{strategy_id}/preview")
    async def preview_strategy(
        strategy_id: str,
        symbol: str = "BTC/USDT",
        timeframe: str = "1h",
        # Faz 2 / S9 — bound the random-walk size at the FastAPI layer:
        # FastAPI now answers ``limit=-5`` and ``limit=99999`` with 422
        # instead of bubbling the ``np.random.normal`` ``ValueError`` /
        # gigabyte allocations.
        limit: int = Query(200, ge=1, le=10_000),
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
        except ValueError:
            raise HTTPException(400, detail="invalid strategy id")
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
