"""Shared httpx.AsyncClient factory for provider adapters.

A single AsyncClient instance is reused across all adapters so connections
get pooled across SEC EDGAR / FRED / TreasuryDirect / OpenFIGI calls and
the FastAPI lifespan teardown only has to close one transport.

Constructors of provider adapters must NOT call ``get_client()`` at import
time — they should resolve it lazily inside the request method so module
import stays side-effect free.
"""
from __future__ import annotations

import asyncio
from typing import Final

import httpx

__all__ = ["get_client", "aclose_shared", "DEFAULT_USER_AGENT"]

# SEC EDGAR REQUIRES a real User-Agent; share it across adapters so every
# upstream sees a consistent identifier.
DEFAULT_USER_AGENT: Final[str] = "showMe/2026.05 (contact@local)"

_DEFAULT_TIMEOUT_S: Final[float] = 20.0

_client: httpx.AsyncClient | None = None
# Track the event loop the cached client's connection pool is bound to. An
# httpx.AsyncClient (and its underlying connection pool) is tied to the loop on
# which its first request runs; reusing it from a *different* loop raises
# "RuntimeError: Event loop is closed". The server runs on one long-lived loop
# so reuse is correct in production, but the unit suite drives many functions via
# asyncio.run(), each spinning up and tearing down its own loop. Without this
# guard, the first function to open a pooled connection would poison the shared
# client for every later test on a fresh loop. We key the cache to the loop and
# rebuild transparently when the running loop changes.
_client_loop: asyncio.AbstractEventLoop | None = None
_lock: asyncio.Lock | None = None
_lock_loop: asyncio.AbstractEventLoop | None = None


def _build_client() -> httpx.AsyncClient:
    """Construct the shared client. Internal helper, not exported."""
    return httpx.AsyncClient(
        timeout=_DEFAULT_TIMEOUT_S,
        follow_redirects=True,
        headers={"User-Agent": DEFAULT_USER_AGENT},
    )


def _loop_lock() -> asyncio.Lock:
    """Return a lock bound to the running loop, rebuilding on loop change.

    A module-level ``asyncio.Lock`` would bind to whatever loop is current at
    import time (or none), which breaks once the suite switches loops between
    ``asyncio.run`` calls. Keying the lock to the running loop keeps the init
    guard valid on every loop.
    """
    global _lock, _lock_loop
    loop = asyncio.get_running_loop()
    if _lock is None or _lock_loop is not loop:
        _lock = asyncio.Lock()
        _lock_loop = loop
    return _lock


async def get_client() -> httpx.AsyncClient:
    """Return the shared AsyncClient, creating it on first use.

    The cached client is reused only while the running event loop matches the
    loop it was bound to; on a new loop (or after it was closed) we rebuild so a
    stale, loop-detached connection pool can never surface as a spurious
    "Event loop is closed" error to callers. Safe to call concurrently — a
    per-loop ``asyncio.Lock`` guards the lazy init.
    """
    global _client, _client_loop
    loop = asyncio.get_running_loop()
    if _client is not None and not _client.is_closed and _client_loop is loop:
        return _client
    async with _loop_lock():
        if _client is None or _client.is_closed or _client_loop is not loop:
            # Best-effort close of a client stranded on a previous loop so we
            # don't leak its transport; never let cleanup mask the rebuild.
            stale = _client
            if stale is not None and not stale.is_closed and _client_loop is loop:
                await stale.aclose()
            _client = _build_client()
            _client_loop = loop
        return _client


async def aclose_shared() -> None:
    """Close the shared client. Call from FastAPI lifespan shutdown.

    No-op when no client was ever instantiated (common in unit tests).
    """
    global _client, _client_loop
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None
    _client_loop = None
