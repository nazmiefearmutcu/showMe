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
_lock = asyncio.Lock()


def _build_client() -> httpx.AsyncClient:
    """Construct the shared client. Internal helper, not exported."""
    return httpx.AsyncClient(
        timeout=_DEFAULT_TIMEOUT_S,
        follow_redirects=True,
        headers={"User-Agent": DEFAULT_USER_AGENT},
    )


async def get_client() -> httpx.AsyncClient:
    """Return the shared AsyncClient, creating it on first use.

    Safe to call concurrently from multiple coroutines — the asyncio.Lock
    guards the lazy init so we don't accidentally create two clients during
    server warm-up.
    """
    global _client
    if _client is not None and not _client.is_closed:
        return _client
    async with _lock:
        if _client is None or _client.is_closed:
            _client = _build_client()
        return _client


async def aclose_shared() -> None:
    """Close the shared client. Call from FastAPI lifespan shutdown.

    No-op when no client was ever instantiated (common in unit tests).
    """
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None
