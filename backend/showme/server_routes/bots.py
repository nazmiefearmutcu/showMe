"""Routes: /api/bots/* — CRUD + enable/disable + signals."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Query

from . import AppDeps

LOG = logging.getLogger("showme.server_routes.bots")


# Faz 2 / M-1 — explicit allowlist; "yolo" etc. are now rejected with a
# 400 instead of being silently coerced to "shadow" on create.
_VALID_MODES = ("shadow", "live")


# C-API-3 / FIX_CONTRACT.md C8 — PUT /api/bots/{id} MUST NOT accept these
# fields from the request body. They're either server-controlled runtime
# state (signal_log, last_processed_event, closed_trades_log) or audit
# metadata (created_at/updated_at) or have a dedicated route (/enable,
# /disable). Stripped BEFORE pydantic validation runs.
_PUT_STRIPPED_FIELDS = (
    "signal_log",
    "last_processed_event",
    "closed_trades_log",
    "created_at",
    "updated_at",
    "enabled",
)


def _broker_registered(exchange_id: str, credential_id: str) -> bool:
    """Return True iff a broker is registered under ``exchange:cred``.

    H-API-1 (BOT_AUDIT_REPORT.md): /enable used to consult only the
    credential-store; an enable could succeed without a corresponding
    broker registration, leaving the bot to fire "broker unavailable"
    skipped signals forever. We now require the factory entry too.
    """
    try:
        from showme.brokers import factory as factory_mod
        name = f"{exchange_id}:{credential_id}"
        return name in factory_mod._REGISTRY
    except Exception as exc:  # noqa: BLE001
        LOG.debug("broker registry lookup failed for %s:%s — %s",
                  exchange_id, credential_id, exc)
        return False


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

    def _credential_exists(credential_id: str) -> bool:
        """Truthy if credential_id resolves in the vault. Used by S5 FK check."""
        try:
            from showme.brokers import CredentialStore, UnknownCredential
            store = CredentialStore.fresh()
            store.get(credential_id)
            return True
        except UnknownCredential:
            return False
        except Exception as exc:  # noqa: BLE001
            # CredentialError (e.g. secrets missing) still means the
            # record is in the index — that's a server problem, not a
            # 'foreign key' problem. Treat as "exists" so callers can
            # surface the underlying broker error instead of a 400.
            LOG.debug("credential lookup non-fatal for %s: %s", credential_id, exc)
            return True

    def _exchange_in_catalog(exchange_id: str) -> bool:
        """Truthy if exchange_id is in the broker catalog (used by S5)."""
        try:
            from showme.brokers import factory as factory_mod
            factory_mod._ensure_catalog()
            factory_mod._CATALOG.by_id(exchange_id)
            return True
        except KeyError:
            return False
        except Exception as exc:  # noqa: BLE001
            LOG.debug("catalog lookup failed for %s: %s", exchange_id, exc)
            return False

    def _validate_fks(payload: dict[str, Any]) -> None:
        """Faz 2 / S5 — make POST/PUT /api/bots reject non-existent
        strategy_id / credential_id / exchange_id with a 400 instead of
        persisting permanently-broken records."""
        from showme.strategies.store import StrategyStore, UnknownStrategy
        sid = payload.get("strategy_id")
        if not isinstance(sid, str) or not sid:
            raise HTTPException(400, detail="strategy_id is required")
        try:
            StrategyStore.fresh().get(sid)
        except UnknownStrategy:
            raise HTTPException(400, detail="strategy_id not found")
        except ValueError:
            # _validate_id rejected the shape
            raise HTTPException(400, detail="strategy_id not found")

        cid = payload.get("credential_id")
        if not isinstance(cid, str) or not cid:
            raise HTTPException(400, detail="credential_id is required")
        if not _credential_exists(cid):
            raise HTTPException(400, detail="credential_id not found")

        eid = payload.get("exchange_id")
        if not isinstance(eid, str) or not eid:
            raise HTTPException(400, detail="exchange_id is required")
        if not _exchange_in_catalog(eid):
            raise HTTPException(400, detail="exchange_id not in catalog")

    @router.get("/api/bots")
    async def list_bots() -> dict[str, Any]:
        """List bots with per-bot ``signal_count``.

        H-SUP-2 (BOT_AUDIT_REPORT.md): the supervisor UI used to derive
        "Sinyaller" from the feed window which capped the count; this
        endpoint now reports the real per-bot length so the table can
        show an accurate per-row tally.
        """
        store = _store()
        out: list[dict[str, Any]] = []
        for meta in store.list():
            d = dict(meta.to_dict())
            try:
                rec = store.get(meta.id)
                d["signal_count"] = len(rec.signal_log)
            except Exception as exc:  # noqa: BLE001
                LOG.debug("signal_count lookup failed for %s: %s", meta.id, exc)
                d["signal_count"] = 0
            out.append(d)
        return {"records": out}

    @router.post("/api/bots")
    async def create_bot(payload: dict[str, Any]) -> dict[str, Any]:
        from showme.bots.record import BotRecord
        if not isinstance(payload, dict):
            raise HTTPException(400, detail="payload must be a JSON object")
        for k in ("id", "created_at", "updated_at", "signal_log", "last_processed_event"):
            payload.pop(k, None)
        # Faz 2 / M-1 — reject unknown ``mode`` instead of silently
        # coercing to "shadow"; users typing "yolo" should learn about it.
        # The ``enabled`` clamp stays defensive (force off on create).
        mode = payload.get("mode", "shadow")
        if mode not in _VALID_MODES:
            raise HTTPException(
                400, detail=f"invalid mode {mode!r}; must be one of {_VALID_MODES}",
            )
        # Force mode=shadow on create — escalation to live happens via PUT or /enable.
        payload["mode"] = "shadow"
        payload["enabled"] = False
        # Faz 2 / S5 — refuse to persist orphan / fake FKs.
        _validate_fks(payload)
        try:
            rec = BotRecord(**payload)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, detail=f"invalid bot: {exc}")
        try:
            saved = _store().save(rec)
        except ValueError as exc:
            # Defence in depth: BotRecord.id is uuid4().hex which passes
            # the store regex, but if a caller smuggled a weird id past
            # the model we still want a 400.
            raise HTTPException(400, detail=str(exc))
        return saved.model_dump()

    @router.get("/api/bots/feed")
    async def bots_feed(
        # H-API-4 (BOT_AUDIT_REPORT.md): limit=-1 / limit=0 used to silently
        # return an empty list with 200 OK. Pinning ge=1/le=500 makes the
        # invariant match /api/strategies/{id}/preview (already ge=1/le=10000)
        # and returns a 422 with a useful field error instead of silent
        # empty success.
        limit: int = Query(50, ge=1, le=500),
    ) -> dict[str, Any]:
        """Aggregate latest signals across all bots, newest first."""
        from datetime import datetime, timezone
        store = _store()
        all_signals: list[dict[str, Any]] = []
        per_bot_counts: dict[str, int] = {}
        for meta in store.list():
            try:
                rec = store.get(meta.id)
            except Exception:  # noqa: BLE001
                continue
            per_bot_counts[rec.id] = len(rec.signal_log)
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
        return {
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "signals": all_signals[:limit],
            # H-SUP-2 — per-bot real signal counts (not window-truncated).
            "per_bot_signal_count": per_bot_counts,
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
        except ValueError:
            raise HTTPException(400, detail="invalid bot id")
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
        except ValueError:
            # Faz 2 / S7 — invalid id shape → 400, not 404 or 5xx.
            raise HTTPException(400, detail="invalid bot id")

    @router.put("/api/bots/{bot_id}")
    async def update_bot(bot_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        from showme.bots.record import BotRecord
        from showme.bots.store import UnknownBot
        if not isinstance(payload, dict):
            raise HTTPException(400, detail="payload must be a JSON object")
        try:
            existing = _store().get(bot_id)
        except UnknownBot:
            raise HTTPException(404, detail=f"unknown bot: {bot_id}")
        except ValueError:
            # Faz 2 / S7 — store rejected an invalid bot_id segment.
            raise HTTPException(400, detail="invalid bot id")
        # C-API-3 / FIX_CONTRACT.md C8 — strip server-controlled and
        # runtime-state fields from the PUT body. This blocks the
        # "PUT 100 forged signal_log entries" injection from the audit
        # repro. The legitimate path is /enable, /disable, and the
        # runner's tick() loop for signal_log.
        for k in _PUT_STRIPPED_FIELDS:
            payload.pop(k, None)
        payload["id"] = bot_id
        # Re-attach the server-side runtime state from the existing record.
        # Clients never set these directly anymore.
        payload["signal_log"] = [e.model_dump() for e in existing.signal_log]
        payload["last_processed_event"] = (
            existing.last_processed_event.model_dump()
            if existing.last_processed_event else None
        )
        payload["enabled"] = existing.enabled

        # Faz 2 / M-1 — same explicit mode allowlist as POST.
        mode = payload.get("mode", existing.mode)
        if mode not in _VALID_MODES:
            raise HTTPException(
                400, detail=f"invalid mode {mode!r}; must be one of {_VALID_MODES}",
            )
        payload["mode"] = mode
        # Faz 2 / S5 — re-validate FK existence on every PUT. Empty
        # ``strategy_id``/``credential_id`` (C-H5) and stale references
        # now 400 instead of being silently persisted.
        _validate_fks(payload)

        # Live-mode gate: trade-perm + account_label confirmation.
        # Faz 2 / H-6 — drop the ``existing.mode != "live"`` short-circuit;
        # if you are submitting a credential change while in live mode
        # (or staying in live mode with a new credential), the new
        # credential MUST still have ``trade`` permission and the caller
        # must re-affirm the account label. The previous code allowed an
        # already-live bot to silently swap to a credential lacking
        # trade perm.
        confirm_label = payload.pop("confirm_account_label", None)
        wants_live = mode == "live"
        cred_changed = payload.get("credential_id") != existing.credential_id
        transitioning_to_live = wants_live and existing.mode != "live"
        if wants_live and (transitioning_to_live or cred_changed):
            has_trade, label = _credential_perm(
                payload.get("credential_id", existing.credential_id),
            )
            if not has_trade:
                raise HTTPException(
                    400,
                    detail="live mode requires a credential with 'trade' permission",
                )
            if confirm_label != label:
                raise HTTPException(
                    400,
                    detail="live mode requires confirm_account_label matching the credential",
                )
        try:
            rec = BotRecord(**payload)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, detail=f"invalid bot: {exc}")
        try:
            saved = _store().save(rec)
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc))
        return saved.model_dump()

    @router.delete("/api/bots/{bot_id}")
    async def delete_bot(bot_id: str) -> dict[str, Any]:
        store = _store()
        runner = _runner()
        try:
            await runner.disable(bot_id, store)
        except Exception:  # noqa: BLE001
            pass
        # H-API-2 (BOT_AUDIT_REPORT.md): the runner's ``_locks`` dict
        # was leaking entries on bot delete. Pop it here as a defensive
        # cleanup — Agent 1's runner refactor may add the same line, in
        # which case this becomes a no-op (pop with default is idempotent).
        locks = getattr(runner, "_locks", None)
        if isinstance(locks, dict):
            locks.pop(bot_id, None)
        try:
            ok = store.delete(bot_id)
        except ValueError:
            # Faz 2 / S7 — block ``DELETE /api/bots/..%2Fetc%2Fpasswd``
            # at the route layer rather than 500-ing.
            raise HTTPException(400, detail="invalid bot id")
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
        except ValueError:
            raise HTTPException(400, detail="invalid bot id")
        # H-API-1 (BOT_AUDIT_REPORT.md): before flipping ``enabled``, make
        # sure the broker factory actually has an entry for
        # ``{exchange_id}:{credential_id}``. Without this check a bot can
        # be ``enabled=True`` but every tick emits "broker unavailable"
        # skipped signals. Failing fast here keeps the UI honest.
        if not _broker_registered(rec.exchange_id, rec.credential_id):
            raise HTTPException(
                400,
                detail=(
                    f"broker not registered: {rec.exchange_id}:{rec.credential_id}. "
                    "Reconnect the credential before enabling the bot."
                ),
            )
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
        except ValueError:
            raise HTTPException(400, detail="invalid bot id")
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
        except ValueError:
            raise HTTPException(400, detail="invalid bot id")
        return {
            "bot_id": bot_id,
            "signals": [e.model_dump() for e in rec.signal_log],
            "last_processed_event": (rec.last_processed_event.model_dump()
                                     if rec.last_processed_event else None),
        }

    app.include_router(router)
