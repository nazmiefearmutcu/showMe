"""Routes: /api/bots/* — CRUD + enable/disable + signals."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException

from . import AppDeps

LOG = logging.getLogger("showme.server_routes.bots")


def register(app: FastAPI, deps: AppDeps) -> None:
    router = APIRouter()

    def _store():
        from showme.bots.store import BotStore
        return BotStore.fresh()

    def _runner():
        from showme.bots.lifespan import get_runner
        return get_runner()

    def _credential_perm(credential_id: str) -> tuple[bool, str]:
        """Returns (has_trade_perm, account_label) — used by live-mode gates."""
        try:
            from showme.brokers import CredentialStore
            store = CredentialStore.fresh()
            rec, _ = store.get(credential_id)
            return ("trade" in rec.permissions, rec.account_label)
        except Exception as exc:  # noqa: BLE001
            LOG.debug("credential perm lookup failed for %s: %s", credential_id, exc)
            return (False, "")

    @router.get("/api/bots")
    async def list_bots() -> dict[str, Any]:
        return {"records": [m.to_dict() for m in _store().list()]}

    @router.post("/api/bots")
    async def create_bot(payload: dict[str, Any]) -> dict[str, Any]:
        from showme.bots.record import BotRecord
        for k in ("id", "created_at", "updated_at", "signal_log", "last_processed_event"):
            payload.pop(k, None)
        # Force mode=shadow on create — escalation to live happens via PUT or /enable.
        payload["mode"] = "shadow"
        payload["enabled"] = False
        try:
            rec = BotRecord(**payload)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, detail=f"invalid bot: {exc}")
        saved = _store().save(rec)
        return saved.model_dump()

    @router.get("/api/bots/feed")
    async def bots_feed(limit: int = 50) -> dict[str, Any]:
        """Aggregate latest signals across all bots, newest first."""
        from datetime import datetime, timezone
        store = _store()
        all_signals: list[dict[str, Any]] = []
        for meta in store.list():
            try:
                rec = store.get(meta.id)
            except Exception:  # noqa: BLE001
                continue
            for entry in rec.signal_log:
                d = entry.model_dump()
                d["bot_id"] = rec.id
                d["bot_symbol"] = rec.symbol
                d["bot_strategy_id"] = rec.strategy_id
                d["bot_exchange_id"] = rec.exchange_id
                d["bot_mode"] = rec.mode
                all_signals.append(d)
        all_signals.sort(
            key=lambda s: s.get("timestamp") or s.get("bar_time") or "",
            reverse=True,
        )
        capped = max(0, min(limit, 500))
        return {
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "signals": all_signals[:capped],
        }

    @router.get("/api/bots/performance")
    async def bots_performance_leaderboard() -> dict[str, Any]:
        from showme.bots.performance import compute_trades, compute_metrics
        from showme.strategies.store import StrategyStore, UnknownStrategy
        store = _store()
        sstore = StrategyStore.fresh()
        records = []
        for meta in store.list():
            try:
                rec = store.get(meta.id)
            except Exception:  # noqa: BLE001
                continue
            sizing = 100.0
            try:
                spec = sstore.get(rec.strategy_id)
                sizing = float(spec.position.sizing_value or 100.0)
            except UnknownStrategy:
                pass
            trades = compute_trades(rec.signal_log, sizing_value=sizing)
            metrics = compute_metrics(trades)
            records.append({
                "bot_id": rec.id,
                "symbol": rec.symbol,
                "strategy_id": rec.strategy_id,
                "mode": rec.mode,
                "enabled": rec.enabled,
                **metrics,
            })
        # Sort by total_pnl desc (best first), then by trade_count desc for stable tie-break.
        records.sort(key=lambda r: (-r["total_pnl"], -r["trade_count"]))
        return {"records": records}

    @router.get("/api/bots/{bot_id}/performance")
    async def bot_performance_detail(bot_id: str) -> dict[str, Any]:
        from showme.bots.performance import (
            compute_trades, compute_metrics, compute_equity_curve,
        )
        from showme.bots.store import UnknownBot
        from showme.strategies.store import StrategyStore, UnknownStrategy
        store = _store()
        try:
            rec = store.get(bot_id)
        except UnknownBot:
            raise HTTPException(404, detail=f"unknown bot: {bot_id}")
        sizing = 100.0
        try:
            spec = StrategyStore.fresh().get(rec.strategy_id)
            sizing = float(spec.position.sizing_value or 100.0)
        except UnknownStrategy:
            pass
        trades = compute_trades(rec.signal_log, sizing_value=sizing)
        return {
            "bot_id": bot_id,
            "symbol": rec.symbol,
            "strategy_id": rec.strategy_id,
            "metrics": compute_metrics(trades),
            "trades": [t.to_dict() for t in trades],
            "equity_curve": compute_equity_curve(trades, starting_equity=10_000),
        }

    @router.get("/api/bots/{bot_id}")
    async def get_bot(bot_id: str) -> dict[str, Any]:
        from showme.bots.store import UnknownBot
        try:
            return _store().get(bot_id).model_dump()
        except UnknownBot:
            raise HTTPException(404, detail=f"unknown bot: {bot_id}")

    @router.put("/api/bots/{bot_id}")
    async def update_bot(bot_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        from showme.bots.record import BotRecord
        from showme.bots.store import UnknownBot
        try:
            existing = _store().get(bot_id)
        except UnknownBot:
            raise HTTPException(404, detail=f"unknown bot: {bot_id}")
        for k in ("created_at", "updated_at"):
            payload.pop(k, None)
        payload["id"] = bot_id
        # Preserve runtime state (signal_log, last_processed_event, enabled)
        # unless explicitly provided.
        if "signal_log" not in payload:
            payload["signal_log"] = [e.model_dump() for e in existing.signal_log]
        if "last_processed_event" not in payload:
            payload["last_processed_event"] = (
                existing.last_processed_event.model_dump()
                if existing.last_processed_event else None
            )
        if "enabled" not in payload:
            payload["enabled"] = existing.enabled

        # Live-mode gate: trade-perm + account_label confirmation
        confirm_label = payload.pop("confirm_account_label", None)
        wants_live = payload.get("mode") == "live"
        if wants_live and existing.mode != "live":
            has_trade, label = _credential_perm(payload.get("credential_id", existing.credential_id))
            if not has_trade:
                raise HTTPException(400,
                    detail="live mode requires a credential with 'trade' permission")
            if confirm_label != label:
                raise HTTPException(400,
                    detail="live mode requires confirm_account_label matching the credential")
        try:
            rec = BotRecord(**payload)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, detail=f"invalid bot: {exc}")
        saved = _store().save(rec)
        return saved.model_dump()

    @router.delete("/api/bots/{bot_id}")
    async def delete_bot(bot_id: str) -> dict[str, Any]:
        store = _store()
        runner = _runner()
        try:
            await runner.disable(bot_id, store)
        except Exception:  # noqa: BLE001
            pass
        ok = store.delete(bot_id)
        if not ok:
            raise HTTPException(404, detail=f"unknown bot: {bot_id}")
        return {"ok": True}

    @router.post("/api/bots/{bot_id}/enable")
    async def enable_bot(bot_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        from showme.bots.store import UnknownBot
        store = _store()
        try:
            rec = store.get(bot_id)
        except UnknownBot:
            raise HTTPException(404, detail=f"unknown bot: {bot_id}")
        if rec.mode == "live":
            confirm = (payload or {}).get("confirm_account_label", "")
            has_trade, label = _credential_perm(rec.credential_id)
            if not has_trade:
                raise HTTPException(400,
                    detail="live mode requires a credential with 'trade' permission")
            if confirm != label:
                raise HTTPException(400,
                    detail="live mode enable requires confirm_account_label matching the credential")
        try:
            updated = await _runner().enable(bot_id, store)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, detail=f"enable failed: {exc}")
        return updated.model_dump()

    @router.post("/api/bots/{bot_id}/disable")
    async def disable_bot(bot_id: str) -> dict[str, Any]:
        from showme.bots.store import UnknownBot
        try:
            updated = await _runner().disable(bot_id, _store())
        except UnknownBot:
            raise HTTPException(404, detail=f"unknown bot: {bot_id}")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, detail=f"disable failed: {exc}")
        return updated.model_dump()

    @router.get("/api/bots/{bot_id}/signals")
    async def bot_signals(bot_id: str) -> dict[str, Any]:
        from showme.bots.store import UnknownBot
        try:
            rec = _store().get(bot_id)
        except UnknownBot:
            raise HTTPException(404, detail=f"unknown bot: {bot_id}")
        return {
            "bot_id": bot_id,
            "signals": [e.model_dump() for e in rec.signal_log],
            "last_processed_event": (rec.last_processed_event.model_dump()
                                     if rec.last_processed_event else None),
        }

    app.include_router(router)
