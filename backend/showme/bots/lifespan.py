"""Lifespan hooks: BotRunner singleton tied to the sidecar process."""
from __future__ import annotations

import logging

from showme.bots.runner import BotRunner
from showme.bots.store import BotStore

LOG = logging.getLogger("showme.bots.lifespan")

_RUNNER: BotRunner | None = None


def get_runner() -> BotRunner:
    """Return the process-wide runner (constructs on first call)."""
    global _RUNNER
    if _RUNNER is None:
        _RUNNER = BotRunner()
    return _RUNNER


async def startup() -> None:
    """Called from server.py lifespan. Replay enabled bots."""
    runner = get_runner()
    try:
        store = BotStore.fresh()
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
