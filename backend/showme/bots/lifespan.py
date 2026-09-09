"""Lifespan hooks: BotRunner singleton tied to the sidecar process."""
from __future__ import annotations

import asyncio
import logging

from showme.bots.runner import BotRunner
from showme.bots.store import BotStore, UnknownBot

LOG = logging.getLogger("showme.bots.lifespan")

_RUNNER: BotRunner | None = None


def get_runner() -> BotRunner:
    """Return the process-wide runner (constructs on first call)."""
    global _RUNNER
    if _RUNNER is None:
        _RUNNER = BotRunner()
    return _RUNNER


def _on_credential_deleted(credential_id: str) -> None:
    """Cascade hook: disable any bot bound to a deleted credential.

    C-INT-1 / C3 fix. Registered with ``factory.register_invalidation_hook``
    in ``startup()``; Agent 2's ``exchange.py`` DELETE handler fires
    ``unregister_credential(...)`` which in turn runs every registered
    invalidation hook with the deleted credential's id. Without this
    hook, live bots referencing the credential would continue ticking,
    log a stream of "broker unavailable" skipped entries, and stay
    visibly "enabled" in the UI even though no orders can land.

    Hook implementation:
    * Finds every bot referencing ``credential_id`` (any mode, any state).
    * Persists ``enabled=False`` for the enabled ones.
    * Schedules ``runner.disable(...)`` via ``asyncio.create_task`` if a
      loop is running; otherwise just writes the disabled flag.
    * Safe to call when no event loop is running (factory.unregister can
      be invoked synchronously from a route handler) — schedules a
      best-effort persistence path via ``asyncio.run`` if needed.

    Best-effort: a credential delete should never raise back into the
    DELETE route over a bot cascade glitch; per-bot exceptions are logged
    and swallowed.
    """
    try:
        store = BotStore.fresh()
        affected = [m for m in store.list() if m.credential_id == credential_id]
        if not affected:
            return
        LOG.info(
            "cascade: credential %s deleted; affecting %d bots",
            credential_id, len(affected),
        )
    except Exception as exc:  # noqa: BLE001
        LOG.warning("cascade lookup failed for credential %s: %s", credential_id, exc)
        return

    runner = _RUNNER  # don't construct one just for the cascade
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    for meta in affected:
        try:
            if runner is not None and runner.is_running(meta.id) and loop is not None:
                # Schedule the runner-aware disable so the task is cancelled
                # before we mutate the on-disk record (avoids a tick racing
                # the cascade and re-writing enabled=True).
                loop.create_task(runner.disable(meta.id, store))
            else:
                # No running loop / no runner instance — just persist the
                # disabled flag so the next sidecar boot doesn't replay.
                if meta.enabled:
                    try:
                        rec = store.get(meta.id)
                        if rec.enabled:
                            store.save(rec.model_copy(update={"enabled": False}))
                    except UnknownBot:
                        LOG.debug("cascade: bot %s disappeared", meta.id)
        except Exception as exc:  # noqa: BLE001
            LOG.warning(
                "cascade disable failed for bot %s: %s", meta.id, exc,
            )


def _seed_default_kaos_bot(store: "BotStore") -> "BotRecord | None":
    """First-run default: seed ONE "KAOS Multibot" bot (frozen CONTRACT).

    Fires only when the bot store is EMPTY — an existing deployment keeps
    every record byte-identical. The seed is honest by construction:

    * ``mode="shadow"`` and ``enabled=False`` (same clamps as POST /api/bots;
      going live stays an explicit user action with a trade-perm credential).
    * ``engine="kaos"`` with both default venues (crypto 20 USD-M majors on
      binanceusdm + NASDAQ 20 majors on alpaca), tick 60s.
    * The bound strategy spec ("kaos-multibot") carries sizing only — the
      KAOS engine evaluates, the spec positions it.
    """
    try:
        if store.list():
            return None
    except Exception as exc:  # noqa: BLE001
        LOG.warning("default-bot seed: store listing failed: %s", exc)
        return None
    try:
        from showme.bots.kaos.config import (
            DEFAULT_KAOS_BOT_NAME,
            DEFAULT_KAOS_SPEC_ID,
            DEFAULT_KAOS_TICK_SECONDS,
            DEFAULT_KAOS_TIMEFRAME,
            DEFAULT_VENUES,
        )
        from showme.bots.record import BotRecord, VenueSpec
        from showme.strategies.spec import StrategySpec
        from showme.strategies.store import StrategyStore, UnknownStrategy

        sstore = StrategyStore.fresh()
        try:
            sstore.get(DEFAULT_KAOS_SPEC_ID)
        except (UnknownStrategy, ValueError):
            sstore.save(StrategySpec(
                id=DEFAULT_KAOS_SPEC_ID,
                name=DEFAULT_KAOS_BOT_NAME,
                description=(
                    "KAOS engine consensus (vendored, s20 config) — the "
                    "default multibot strategy. Evaluates every venue "
                    "universe per tick; this spec carries sizing only."
                ),
                timeframe=DEFAULT_KAOS_TIMEFRAME,
            ))
        rec = BotRecord(
            strategy_id=DEFAULT_KAOS_SPEC_ID,
            credential_id="kaos-local",
            exchange_id="binanceusdm",
            symbol="BTC/USDT",
            timeframe=DEFAULT_KAOS_TIMEFRAME,
            tick_interval_seconds=DEFAULT_KAOS_TICK_SECONDS,
            mode="shadow",
            enabled=False,
            engine="kaos",
            venues=[VenueSpec(**v) for v in DEFAULT_VENUES],
        )
        saved = store.save(rec)
        LOG.info("default bot seeded: %s (engine=kaos, shadow, %d venues)",
                 DEFAULT_KAOS_BOT_NAME, len(DEFAULT_VENUES))
        return saved
    except Exception as exc:  # noqa: BLE001
        LOG.warning("default KAOS bot seed failed: %s", exc)
        return None


async def startup() -> None:
    """Called from server.py lifespan. Replay enabled bots.

    C3 fix: also registers ``_on_credential_deleted`` with the broker
    factory so a credential DELETE cascades into bot disable.
    2026-09-09: seeds the default "KAOS Multibot" bot on first run.
    """
    runner = get_runner()
    try:
        from showme.brokers import factory as factory_mod
        # Register the cascade hook idempotently (re-init re-registers,
        # but tests / dev reloads tolerate duplicates).
        hooks = getattr(factory_mod, "_INVALIDATION_HOOKS", None)
        if hooks is not None and _on_credential_deleted not in hooks:
            hooks.append(_on_credential_deleted)
    except Exception as exc:  # noqa: BLE001
        LOG.warning("cascade hook registration failed: %s", exc)

    try:
        store = BotStore.fresh()
        _seed_default_kaos_bot(store)
        await runner.start_all(store)
        LOG.info("bot runner: started")
    except Exception as exc:  # noqa: BLE001
        LOG.warning("bot runner startup failed: %s", exc)


async def shutdown() -> None:
    """Called from server.py lifespan."""
    global _RUNNER
    if _RUNNER is not None:
        try:
            await _RUNNER.aclose()
        except Exception as exc:  # noqa: BLE001
            LOG.debug("bot runner shutdown: %s", exc)
        _RUNNER = None
