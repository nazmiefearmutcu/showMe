"""Keyless FRED fredgraph.csv helper — shared live fallback for macro/bond.

FRED serves every series as a keyless CSV::

    https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID>

WIRP has used this endpoint in production since its CME-FedWatch rewrite
(see ``macro/wirp.py::_fetch_fred_latest``). This module extracts that
pattern into a shared helper so functions whose ``deps.fred`` adapter
hard-requires ``FRED_API_KEY`` (fred_adapter.py raises ``DataSourceError``
without a key) keep a live path with no keys: ECST, CRVF, WB, YAS, GC3D,
WACC (survey S2, item c#3).

``_KeylessFredCSV`` mirrors the subset of the fred adapter contract those
functions use — ``series(...)`` returning a DataFrame indexed by date with
a ``value`` column, and ``yield_curve()`` returning ``{series_id: value}``
— so call sites only need ``fred = fred_with_keyless_fallback(deps.fred)``.

Values are cached briefly (TTL) and concurrent CSV fetches are throttled
to stay polite to FRED. Every failure mode returns ``None`` / raises
plain exceptions the caller's existing ``except`` branches already handle
honestly.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd

_FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
_DEFAULT_TIMEOUT_S = 8.0
_CACHE_TTL_S = 900.0
# FRED is polite-tier: cap concurrent keyless GETs across the process.
_MAX_CONCURRENT_FETCHES = 2

_cache: dict[tuple[str, int], tuple[float, pd.DataFrame]] = {}
_semaphore: asyncio.Semaphore | None = None
_semaphore_loop: asyncio.AbstractEventLoop | None = None


def reset_fred_csv_cache() -> None:
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


def _parse_csv_frame(text: str) -> pd.DataFrame:
    """Parse a fredgraph.csv payload into a date-indexed ``value`` frame.

    Rows look like ``2026-05-28,4.50`` with ``.`` placeholders for missing
    observations and a ``observation_date,value`` header. Malformed rows
    are skipped rather than trusted.
    """
    records: list[tuple[str, float]] = []
    for line in text.strip().splitlines():
        if "," not in line:
            continue
        date_str, _, value_str = line.partition(",")
        value_str = value_str.strip()
        if (
            value_str in (".", "", "value", "VALUE")
            or date_str.strip().lower() in ("date", "observation_date")
        ):
            continue
        try:
            records.append((date_str.strip(), float(value_str)))
        except ValueError:
            continue
    if not records:
        return pd.DataFrame()
    frame = pd.DataFrame(records, columns=["date", "value"])
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(subset=["date"]).set_index("date").sort_index()
    return frame


async def fetch_fred_csv_series(
    series_id: str,
    *,
    client: Any = None,
    timeout: float = _DEFAULT_TIMEOUT_S,
    lookback_days: int | None = None,
) -> pd.DataFrame | None:
    """Fetch one FRED series as a date-indexed frame; ``None`` on failure.

    ``client`` is an optional injected httpx-like async client (test seam);
    otherwise the shared keyless pool is used. ``lookback_days`` trims the
    frame to the trailing window and keys the cache.
    """
    if not series_id or not str(series_id).strip():
        return None
    series_id = str(series_id).strip()
    cache_key = (series_id, int(lookback_days or 0))
    now = time.monotonic()
    cached = _cache.get(cache_key)
    if cached is not None and (now - cached[0]) < _CACHE_TTL_S:
        return cached[1].copy()

    if client is None:
        from showme.providers._http import get_client

        client = await get_client()
    url = _FRED_CSV_URL.format(series_id=series_id)
    try:
        async with _get_semaphore():
            try:
                resp = await client.get(url, timeout=timeout)
            except TypeError:
                # Minimal test fakes may not accept a per-request timeout.
                resp = await client.get(url)
        resp.raise_for_status()
        frame = _parse_csv_frame(resp.text)
    except Exception:  # noqa: BLE001 - any fetch/parse failure means 'no live data'
        return None
    if frame.empty:
        return None
    if lookback_days:
        # The parsed index is tz-naive (plain observation dates), so the
        # cutoff must be tz-naive too — comparing across tz-awareness
        # raises TypeError in pandas.
        cutoff = pd.Timestamp(datetime.now(UTC).replace(tzinfo=None)) - pd.Timedelta(days=lookback_days)
        frame = frame[frame.index >= cutoff]
        if frame.empty:
            return None
    _cache[cache_key] = (now, frame.copy())
    return frame.copy()


class _KeylessFredCSV:
    """Drop-in shim for the subset of the fred adapter contract in use.

    ``series()`` matches ``FredAdapter.series`` (date-indexed frame with a
    ``value`` column); ``yield_curve()`` matches the adapter's DGS set.
    Network failures raise so callers' existing ``except`` branches label
    the outage honestly.
    """

    _CURVE_IDS: tuple[str, ...] = (
        # R3 L-1: monthly bill ids included so the keyless tier can feed
        # CRVF's mapped short end (absent series stay NaN per-tenor).
        "DGS1MO", "DGS2MO", "DGS4MO", "DGS3MO", "DGS6MO", "DGS1", "DGS2",
        "DGS3", "DGS5", "DGS7", "DGS10", "DGS20", "DGS30",
    )

    def __init__(self, client: Any = None) -> None:
        self._client = client

    async def series(
        self,
        series_id: str,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        frequency: str | None = None,
        vintage: str | None = None,
    ) -> pd.DataFrame:
        lookback = None
        if start:
            if isinstance(start, datetime):
                delta = datetime.now(UTC) - start
                lookback = max(1, delta.days + 1)
            else:
                try:
                    start_dt = datetime.strptime(str(start)[:10], "%Y-%m-%d").replace(tzinfo=UTC)
                    lookback = max(1, (datetime.now(UTC) - start_dt).days + 1)
                except ValueError:
                    pass
        frame = await fetch_fred_csv_series(
            series_id, client=self._client, lookback_days=lookback,
        )
        if frame is None or frame.empty:
            raise RuntimeError(f"keyless FRED CSV unavailable for {series_id!r}")
        if end:
            try:
                end_dt = pd.Timestamp(end)
                frame = frame[frame.index <= end_dt]
            except (TypeError, ValueError):
                pass
        return frame

    async def yield_curve(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for sid in self._CURVE_IDS:
            try:
                frame = await fetch_fred_csv_series(sid, client=self._client)
                out[sid] = float(frame["value"].iloc[-1]) if frame is not None and not frame.empty else float("nan")
            except Exception:  # noqa: BLE001 - per-tenor failure stays NaN
                out[sid] = float("nan")
        return out


def fred_with_keyless_fallback(fred: Any, client: Any = None) -> Any:
    """Return the keyed adapter when wired, else the keyless CSV shim.

    A single call site line — ``fred = fred_with_keyless_fallback(deps.fred)``
    — is enough to give an existing keyed FRED consumer a no-key live path;
    all downstream ``series()``/``yield_curve()`` calls and their failure
    handling stay byte-identical.
    """
    if fred:
        return fred
    return _KeylessFredCSV(client)
