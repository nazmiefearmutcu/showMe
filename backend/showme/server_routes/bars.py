"""Keyless OHLCV bars route for the chart engine — ``GET /api/bars``.

Crypto symbols are served from Binance spot klines; every other instrument
(equities / ETFs / indices / FX / commodities) from the Yahoo chart API.
Both providers are keyless and the route never fabricates data:

* unsupported (instrument, interval) pairs return HTTP 200 with an empty
  ``bars`` list and an honest ``reason`` string the chart can render;
* any provider failure degrades the same way instead of raising.

A small process-local TTL cache (256 entries, keyed on symbol+interval+limit)
keeps charts polling cheap: 250 ms for 1 s bars (they must refresh FASTER
than the bar period), 1 s for other sub-minute intervals, 5 s otherwise;
concurrent panes share one upstream call per key per window.

The provider fetchers (``fetch_binance_bars`` / ``fetch_yahoo_bars``) are
module-level on purpose — tests monkeypatch them at this seam.
"""
from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote as _urlquote

import requests
from fastapi import APIRouter, FastAPI, Query

from . import AppDeps

LOG = logging.getLogger("showme.server_routes.bars")

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
USER_AGENT = "showMe/1.0"

DEFAULT_LIMIT = 300
MAX_LIMIT = 1000
_FETCH_TIMEOUT_S = 10.0

# Canonical showMe interval ids: ``m`` = minute, ``M`` = month.
CANDLE_INTERVALS: tuple[str, ...] = (
    "1s", "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "8h", "12h",
    "1d", "3d", "1w", "1M",
)
# Second ids beyond 1s are recognized ids but exist in no provider mapping —
# they earn the honest "not available" reason instead of silently falling
# back to the default interval.
_SECOND_ONLY_INTERVALS: tuple[str, ...] = ("5s", "15s", "30s")
KNOWN_INTERVALS: tuple[str, ...] = CANDLE_INTERVALS + _SECOND_ONLY_INTERVALS

# showMe canonical id -> Binance kline interval (spot supports all of these).
BINANCE_INTERVAL_MAP: dict[str, str] = {iv: iv for iv in CANDLE_INTERVALS}
BINANCE_INTERVAL_MAP["1M"] = "1mo"

# showMe canonical id -> (Yahoo interval, Yahoo range). Yahoo has no second
# intervals and no 3m/2h/4h/... — those pairs are honestly unavailable.
YAHOO_INTERVAL_MAP: dict[str, tuple[str, str]] = {
    "1m": ("1m", "7d"),
    "5m": ("5m", "60d"),
    "15m": ("15m", "60d"),
    "30m": ("30m", "60d"),
    "1h": ("60m", "730d"),
    "1d": ("1d", "10y"),
    "1w": ("1wk", "max"),
    "1M": ("1mo", "max"),
}

# Friendly aliases for ids users type with different casing (``1D``, ``1W``)
# or spelled out (``1day``). Case matters: ``1m`` stays minute while ``1M``
# is month, which is why the canonical table is consulted before these.
_INTERVAL_ALIASES: dict[str, str] = {
    "1D": "1d", "3D": "3d", "1W": "1w",
    "60m": "1h", "60M": "1h",
    "1day": "1d", "1week": "1w", "1min": "1m", "1minute": "1m",
    "1mo": "1M", "1mon": "1M", "1month": "1M",
}


def normalize_interval(value: Any, default: str = "1m") -> str:
    """Return the canonical showMe interval id for ``value``.

    Unknown/blank values fall back to ``default`` instead of raising — the
    route would rather serve the default horizon than a 422 for a typo.
    """
    text = str(value or "").strip()
    if not text:
        return default
    if text in KNOWN_INTERVALS:
        return text
    if text in _INTERVAL_ALIASES:
        return _INTERVAL_ALIASES[text]
    lowered = text.lower()
    if lowered in KNOWN_INTERVALS and lowered != "1m":
        # Case-insensitive match is safe for every id except m/M
        # (minute vs month), which the exact-case checks above disambiguate.
        return lowered
    upper = text.upper()
    if upper in _INTERVAL_ALIASES:
        return _INTERVAL_ALIASES[upper]
    return default


# ── 5 s process-local TTL cache (bounded, keyed symbol+interval+limit) ──────
_BARS_CACHE_TTL_S = 5.0
# The 1s chart polls every 500 ms; any cache window close to the bar period
# serves stale payloads and makes the stream look frozen. The 1s interval
# gets a 250 ms window (fresh bar per poll, upstream klines weight stays
# trivial) and 5s bars a 1s window.
_BARS_CACHE_TTL_FAST_S = 0.25
_BARS_CACHE_TTL_MID_S = 1.0
_BARS_CACHE_MAX_ENTRIES = 256
_bars_cache: OrderedDict[tuple[str, str, int], tuple[float, dict[str, Any]]] = OrderedDict()
_bars_cache_lock = threading.Lock()


def bars_cache_ttl_for(interval_id: str, source: str = "binance") -> float:
    """Cache window per provider (every chart now polls at 500 ms).

    Binance takes a 250 ms window so each poll can observe a fresh bar (a
    300-bar klines request is weight 2, so 2 req/s stays trivial); Yahoo's
    public endpoint rate-limits harder and keeps a 1 s window. ``interval_id``
    stays in the signature for future per-interval tuning.
    """
    if source == "yahoo":
        return _BARS_CACHE_TTL_MID_S
    return _BARS_CACHE_TTL_FAST_S


def bars_cache_clear() -> None:
    """Drop every cached payload. Used by tests + health resets."""
    with _bars_cache_lock:
        _bars_cache.clear()


def _cache_get(key: tuple[str, str, int], ttl: float = _BARS_CACHE_TTL_S) -> dict[str, Any] | None:
    now = time.monotonic()
    with _bars_cache_lock:
        entry = _bars_cache.get(key)
        if entry is None:
            return None
        set_at, payload = entry
        if now - set_at >= ttl:
            _bars_cache.pop(key, None)
            return None
        _bars_cache.move_to_end(key)
        # Shallow copy so callers can't mutate the cached record.
        return dict(payload)


def _cache_set(key: tuple[str, str, int], payload: dict[str, Any]) -> None:
    with _bars_cache_lock:
        if key in _bars_cache:
            _bars_cache.pop(key, None)
        elif len(_bars_cache) >= _BARS_CACHE_MAX_ENTRIES:
            _bars_cache.popitem(last=False)
        _bars_cache[key] = (time.monotonic(), payload)


# ── provider fetchers (module-level monkeypatch seam) ──────────────────────
def _bar(ts_ms: Any, o: Any, h: Any, l: Any, c: Any, v: Any) -> dict[str, Any] | None:
    """Build one normalized bar, or ``None`` when any field is unusable."""
    try:
        bar = {
            "t": int(ts_ms),
            "o": float(o),
            "h": float(h),
            "l": float(l),
            "c": float(c),
            "v": float(v),
        }
    except (TypeError, ValueError):
        return None
    for field in ("o", "h", "l", "c", "v"):
        if not math.isfinite(bar[field]):
            return None
    return bar


async def fetch_binance_bars(symbol: str, interval: str, limit: int) -> list[dict[str, Any]]:
    """Fetch spot klines for ``symbol`` at the already-mapped Binance id.

    ``interval`` is the Binance kline id (``1d``/``1w``/``1mo``), not a showMe
    id. Module-level on purpose — tests monkeypatch this seam.
    """

    def _fetch() -> list[dict[str, Any]]:
        response = requests.get(
            BINANCE_KLINES_URL,
            params={"symbol": symbol, "interval": interval, "limit": int(limit)},
            headers={"User-Agent": USER_AGENT},
            timeout=6.0,
        )
        response.raise_for_status()
        payload = response.json() or []
        bars: list[dict[str, Any]] = []
        for row in payload:
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                continue
            bar = _bar(row[0], row[1], row[2], row[3], row[4], row[5])
            if bar is not None:
                bars.append(bar)
        return bars

    return await asyncio.to_thread(_fetch)


async def fetch_yahoo_bars(symbol: str, interval: str, yahoo_range: str) -> list[dict[str, Any]]:
    """Fetch a Yahoo chart payload and flatten it to bars.

    ``interval``/``yahoo_range`` arrive already mapped (``60m``/``730d``).
    Module-level on purpose — tests monkeypatch this seam.
    """

    def _fetch() -> list[dict[str, Any]]:
        response = requests.get(
            YAHOO_CHART_URL.format(symbol=_urlquote(symbol, safe="")),
            params={"interval": interval, "range": yahoo_range},
            headers={"User-Agent": USER_AGENT},
            timeout=8.0,
        )
        response.raise_for_status()
        payload = response.json() or {}
        results = (payload.get("chart") or {}).get("result") or []
        if not results or not isinstance(results[0], dict):
            return []
        result = results[0]
        timestamps = result.get("timestamp") or []
        quote_blocks = (result.get("indicators") or {}).get("quote") or []
        quote = quote_blocks[0] if quote_blocks and isinstance(quote_blocks[0], dict) else {}
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []

        def _at(series: list[Any], idx: int) -> Any:
            return series[idx] if idx < len(series) else None

        bars: list[dict[str, Any]] = []
        for idx, ts in enumerate(timestamps):
            if ts is None:
                continue
            try:
                ts_ms = int(ts) * 1000
            except (TypeError, ValueError):
                continue
            volume = _at(volumes, idx)
            bar = _bar(
                ts_ms,
                _at(opens, idx),
                _at(highs, idx),
                _at(lows, idx),
                _at(closes, idx),
                0.0 if volume is None else volume,
            )
            if bar is not None:
                bars.append(bar)
        return bars

    return await asyncio.to_thread(_fetch)


def _finalize_bars(rows: Any, limit: int) -> list[dict[str, Any]]:
    """Validate provider rows, sort ascending and keep the latest ``limit``."""
    bars: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        bar = _bar(
            row.get("t"),
            row.get("o"),
            row.get("h"),
            row.get("l"),
            row.get("c"),
            row.get("v", 0.0),
        )
        if bar is not None:
            bars.append(bar)
    bars.sort(key=lambda item: item["t"])
    if len(bars) > limit:
        bars = bars[-limit:]
    return bars


def register(app: FastAPI, deps: AppDeps) -> None:
    from showme.crypto_aliases import is_crypto_symbol
    from showme.quotes import clean_symbol

    router = APIRouter()

    @router.get("/api/bars")
    async def bars(
        symbol: str = Query(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9._:=\-^]+$"),
        interval: str = Query("1m", max_length=12),
        limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    ) -> dict[str, Any]:
        """OHLCV bars for the chart engine (last ``limit``, ascending).

        ``t`` is the bar OPEN time in epoch milliseconds. Unsupported pairs
        and provider failures both return 200 with ``bars: []`` plus a
        ``reason`` the chart renders — never fabricated candles.
        """
        target = clean_symbol(symbol)
        interval_id = normalize_interval(interval)
        crypto = is_crypto_symbol(target)
        source = "binance" if crypto else "yahoo"
        payload: dict[str, Any] = {
            "symbol": target,
            "interval": interval_id,
            "bars": [],
            "source": source,
            "asOf": datetime.now(UTC).isoformat(),
        }

        key = (target, interval_id, int(limit))
        cached = _cache_get(key, bars_cache_ttl_for(interval_id, source))
        if cached is not None:
            return cached

        available = (
            interval_id in BINANCE_INTERVAL_MAP
            if crypto
            else interval_id in YAHOO_INTERVAL_MAP
        )
        # 5s/15s/30s (and every unmapped pair) land here for both sources:
        # the response is an honest empty with the reason the chart renders.
        if not available:
            payload["reason"] = (
                f"{interval_id} bars are not available for {source} instruments"
            )
            _cache_set(key, payload)
            return payload

        try:
            if crypto:
                fetched = await asyncio.wait_for(
                    fetch_binance_bars(
                        target, BINANCE_INTERVAL_MAP[interval_id], int(limit)
                    ),
                    timeout=_FETCH_TIMEOUT_S,
                )
            else:
                yahoo_interval, yahoo_range = YAHOO_INTERVAL_MAP[interval_id]
                fetched = await asyncio.wait_for(
                    fetch_yahoo_bars(target, yahoo_interval, yahoo_range),
                    timeout=_FETCH_TIMEOUT_S,
                )
            payload["bars"] = _finalize_bars(fetched, int(limit))
        except Exception as exc:  # noqa: BLE001 — honest empty on any provider failure
            LOG.warning(
                "bars: %s fetch failed for %s/%s: %r", source, target, interval_id, exc
            )
            payload["bars"] = []
            payload["reason"] = (
                f"{source} fetch failed: {str(exc) or type(exc).__name__}"
            )
        _cache_set(key, payload)
        return payload

    app.include_router(router)
