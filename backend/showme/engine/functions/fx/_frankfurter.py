"""Keyless Frankfurter (ECB) FX rates helper — shared live spot fallback.

Frankfurter (https://frankfurter.app) serves the ECB's official published
reference rates with NO API key::

    https://api.frankfurter.app/latest?from=EUR&to=TRY,USD

Lane E / H-4 (2026-09-09): the FX suite used to fall straight from the
keyed providers (yfinance quote, keyed ECB adapter, exchangerate.host)
to the stamped 2024-06 reference constants. This module gives the fx
functions a keyless live tier in between, following the exact pattern of
``showme.engine.functions._fred_csv`` (timeout, small TTL cache, injection
seam for tests, ``None`` on any failure so callers keep their honest
labelled fallbacks).

Note: Frankfurter only carries the ~30 ECB reference currencies. Any
pair/matrix currency outside that set is simply absent from the response
— callers must treat that as "no live data", never as 0.0.
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any

_FRANKFURTER_URL = "https://api.frankfurter.app/latest?from={base}&to={quotes}"
_DEFAULT_TIMEOUT_S = 6.0
_CACHE_TTL_S = 900.0
# Frankfurter is a free public API: cap concurrent keyless GETs.
_MAX_CONCURRENT_FETCHES = 2

_cache: dict[tuple[str, tuple[str, ...]], tuple[float, dict[str, float]]] = {}
_semaphore: asyncio.Semaphore | None = None
_semaphore_loop: asyncio.AbstractEventLoop | None = None


def reset_frankfurter_cache() -> None:
    """Clear the TTL cache (test seam)."""
    _cache.clear()


def _get_semaphore() -> asyncio.Semaphore:
    """Return a semaphore bound to the running loop (rebuild on change)."""
    global _semaphore, _semaphore_loop
    loop = asyncio.get_running_loop()
    if _semaphore is None or _semaphore_loop is not loop:
        _semaphore = asyncio.Semaphore(_MAX_CONCURRENT_FETCHES)
        _semaphore_loop = loop
    return _semaphore


def _parse_rates(payload: Any, quotes: list[str]) -> dict[str, float] | None:
    """Extract {quote: rate} for the requested quotes; None when unusable.

    Only positive finite rates for REQUESTED quotes are returned — a
    currency Frankfurter does not carry is absent, never zero.
    """
    if not isinstance(payload, dict):
        return None
    rates = payload.get("rates")
    if not isinstance(rates, dict):
        return None
    out: dict[str, float] = {}
    for quote in quotes:
        raw = rates.get(quote)
        try:
            value = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value > 0:
            out[quote] = value
    return out or None


async def fetch_frankfurter_rates(
    base: str,
    quotes: list[str],
    *,
    client: Any = None,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> dict[str, float] | None:
    """Fetch ECB reference rates for ``base`` -> ``quotes``; None on failure.

    ``client`` is an optional injected httpx-like async client (test seam);
    otherwise the shared keyless pool is used. The result is cached briefly
    (TTL) keyed by ``(base, quotes)``.
    """
    base = str(base or "").strip().upper()
    wanted = [str(q).strip().upper() for q in quotes if str(q).strip()]
    wanted = [q for q in wanted if q != base]
    if not base or len(base) != 3 or not wanted:
        return None
    cache_key = (base, tuple(sorted(wanted)))
    now = time.monotonic()
    cached = _cache.get(cache_key)
    if cached is not None and (now - cached[0]) < _CACHE_TTL_S:
        return dict(cached[1])

    if client is None:
        from showme.providers._http import get_client

        client = await get_client()
    url = _FRANKFURTER_URL.format(base=base, quotes=",".join(wanted))
    try:
        async with _get_semaphore():
            try:
                resp = await client.get(url, timeout=timeout)
            except TypeError:
                # Minimal test fakes may not accept a per-request timeout.
                resp = await client.get(url)
        resp.raise_for_status()
        payload = resp.json()
        rates = _parse_rates(payload, wanted)
    except Exception:  # noqa: BLE001 - any fetch/parse failure means 'no live data'
        return None
    if not rates:
        return None
    _cache[cache_key] = (now, dict(rates))
    return dict(rates)


async def fetch_frankfurter_rate(
    base: str,
    quote: str,
    *,
    client: Any = None,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> float | None:
    """Fetch one ECB reference rate ``base -> quote``; None on failure."""
    rates = await fetch_frankfurter_rates(
        base, [quote], client=client, timeout=timeout
    )
    if not rates:
        return None
    return rates.get(str(quote).strip().upper())
