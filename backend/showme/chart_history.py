"""Deep OHLCV history helpers for terminal-grade chart panes.

The normal ShowMe data-source adapters optimize for broad function execution,
not chart UX. In practice that meant crypto charts often stopped around one
page of candles. This module gives GP/HP/WATCH a direct, pageable history path:
Binance klines for crypto and Yahoo chart history for listed assets.

The ``fetch_longest_history`` orchestrator races every viable provider in
parallel and picks the one whose earliest returned bar is oldest, so HP/GP
always render the deepest history available for a given symbol — across
markets, with no asset-class gating.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from io import StringIO
import math
import os
from typing import Any

import httpx

from showme.crypto_aliases import split_crypto_symbol

STOOQ_API_KEY_ENV = "STOOQ_API_KEY"


INTERVAL_SECONDS: dict[str, int] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14_400,
    "1d": 86_400,
    "1w": 604_800,
    "1mo": 2_592_000,
}

YAHOO_INTERVALS: dict[str, str] = {
    "1m": "1m",
    "2m": "2m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "60m",
    "4h": "60m",
    "1d": "1d",
    "1w": "1wk",
    "1mo": "1mo",
}

BINANCE_INTERVALS: dict[str, str] = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "1d": "1d",
    "1w": "1w",
    "1mo": "1M",
}

STOOQ_INTERVALS: dict[str, str] = {
    "1d": "d",
    "1w": "w",
    "1mo": "m",
}

DEFAULT_BARS = 1_500
MAX_BARS = 20_000
BINANCE_PAGE_LIMIT = 1_000
# Used by ``fetch_longest_history`` to give every provider a fair shot at
# reaching its deepest available bar — independent of the user's range pill.
RACE_LOOKBACK_DAYS = 365 * 60


@dataclass
class DeepHistoryResult:
    rows: list[dict[str, Any]]
    source: str
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def normalize_history_interval(value: Any, default: str = "1d") -> str:
    raw = str(value or default).strip().lower()
    aliases = {
        "60m": "1h",
        "1hr": "1h",
        "1hour": "1h",
        "1wk": "1w",
        "1mo": "1mo",
        "1mth": "1mo",
        "1month": "1mo",
        "daily": "1d",
        "day": "1d",
        "weekly": "1w",
    }
    normalized = aliases.get(raw, raw)
    return normalized if normalized in INTERVAL_SECONDS else default


def parse_history_bars(value: Any, default: int = DEFAULT_BARS) -> int:
    try:
        bars = int(float(value))
    except Exception:
        bars = default
    return max(10, min(MAX_BARS, bars))


async def fetch_deep_history(
    *,
    symbol: str,
    asset_class: str,
    interval: str,
    days: int,
    bars: int,
) -> DeepHistoryResult:
    """Fetch chart history from a direct pageable provider.

    Kept for backward compatibility. Single-provider path: Binance for crypto,
    Yahoo otherwise. Prefer :func:`fetch_longest_history` for HP/GP/WATCH.
    """
    normalized_interval = normalize_history_interval(interval)
    normalized_bars = parse_history_bars(bars)
    normalized_days = max(1, int(days))
    asset = str(asset_class or "").upper()
    if asset == "CRYPTO":
        return await fetch_binance_history(
            symbol=symbol,
            interval=normalized_interval,
            days=normalized_days,
            bars=normalized_bars,
        )
    return await fetch_yahoo_history(
        symbol=symbol,
        asset_class=asset,
        interval=normalized_interval,
        days=normalized_days,
        bars=normalized_bars,
    )


async def fetch_longest_history(
    *,
    symbol: str,
    asset_class: str,
    interval: str,
    days: int,
    bars: int,
    deep_history: bool = True,
) -> DeepHistoryResult:
    """Race every viable provider concurrently; return the source whose
    earliest returned bar is oldest.

    No market exception: a stock symbol gets asked of Binance too (it will
    fail fast), a crypto symbol gets asked of Yahoo and Stooq too. The
    winner is whichever source actually went furthest back in history.

    Provider order in the response metadata is preserved for the UI so
    users can see what was tried and why the winner won.
    """
    normalized_interval = normalize_history_interval(interval)
    normalized_days = max(1, int(days))
    user_bars = parse_history_bars(bars)
    # For the depth race, ALWAYS push each provider to its deepest reach
    # rather than the user's range slider. This is what lets the chart
    # show AAPL from 1980 even when the user picked the "Max" 25Y pill —
    # the user-visible window is enforced AFTER the winner is chosen.
    if deep_history:
        race_days = max(normalized_days, RACE_LOOKBACK_DAYS)
        fetch_bars = MAX_BARS
    else:
        race_days = normalized_days
        fetch_bars = user_bars
    asset = str(asset_class or "").upper()

    providers: list[tuple[str, Any]] = [
        (
            "yahoo",
            fetch_yahoo_history(
                symbol=symbol,
                asset_class=asset,
                interval=normalized_interval,
                days=race_days,
                bars=fetch_bars,
            ),
        ),
    ]
    # Binance only carries crypto pairs — racing it for equity/ETF/FX/etc.
    # produces a 400 per timeframe per endpoint (SPOT + FUTURES), which at
    # scan scale is ~50k wasted HTTP calls.
    if asset == "CRYPTO":
        providers.append(
            (
                "binance",
                fetch_binance_history(
                    symbol=symbol,
                    interval=normalized_interval,
                    days=race_days,
                    bars=fetch_bars,
                ),
            )
        )
    # Stooq is gated on STOOQ_API_KEY because the keyless CSV endpoint now
    # returns a captcha link instead of CSV. When the key is present Stooq
    # is typically the deepest source (e.g. AAPL back to 1980, ^SPX to 1957).
    if (
        normalized_interval in STOOQ_INTERVALS
        and os.environ.get(STOOQ_API_KEY_ENV)
    ):
        providers.append(
            (
                "stooq",
                fetch_stooq_history(
                    symbol=symbol,
                    asset_class=asset,
                    interval=normalized_interval,
                    days=race_days,
                    bars=fetch_bars,
                ),
            )
        )

    raw_results = await asyncio.gather(
        *(coro for _, coro in providers), return_exceptions=True
    )

    successful: list[DeepHistoryResult] = []
    provider_errors: list[str] = []
    considered: list[dict[str, Any]] = []
    for (name, _), outcome in zip(providers, raw_results, strict=True):
        if isinstance(outcome, Exception):
            provider_errors.append(f"{name}: {outcome}")
            considered.append({"name": name, "ok": False, "error": str(outcome)})
            continue
        if not isinstance(outcome, DeepHistoryResult) or not outcome.rows:
            provider_errors.append(f"{name}: empty result")
            considered.append({"name": name, "ok": False, "error": "empty"})
            continue
        first_ts = _row_time_ms(outcome.rows[0])
        considered.append(
            {
                "name": name,
                "source": outcome.source,
                "ok": True,
                "first_ts_ms": first_ts,
                "bars_available": len(outcome.rows),
            }
        )
        successful.append(outcome)

    if not successful:
        raise RuntimeError(
            "; ".join(provider_errors) or f"no history available for {symbol}"
        )

    winner = min(
        successful,
        key=lambda result: _row_time_ms(result.rows[0]),
    )

    # Two-stage trim of the winner:
    # (1) drop rows older than the user's requested window so the chart still
    #     respects the 1M/3M/Max pill they clicked, but
    # (2) honor ``bars`` as a hard cap on the most-recent rows we return.
    user_window_start_ms = max(
        0,
        int((datetime.now(tz=timezone.utc).timestamp() - normalized_days * 86_400)) * 1000,
    )
    windowed_rows = [
        row for row in winner.rows if _row_time_ms(row) >= user_window_start_ms
    ] if user_window_start_ms else list(winner.rows)
    if not windowed_rows:
        # Window is narrower than even the most recent bar from the winner —
        # fall back to whatever rows the winner has so we don't return empty.
        windowed_rows = list(winner.rows)
    trimmed_rows = windowed_rows[-user_bars:] if user_bars > 0 else windowed_rows
    winner_first_ts = _row_time_ms(winner.rows[0])
    winner_metadata = dict(winner.metadata)
    winner_metadata.update(
        {
            "selection_reason": "oldest_first_bar",
            "sources_considered": considered,
            "winner": winner.source,
            "winner_first_ts_ms": winner_first_ts,
            "bars_available": len(winner.rows),
            "bars_returned": len(trimmed_rows),
            "deep_history": True,
        }
    )

    winner_warnings = list(winner.warnings)
    for err in provider_errors:
        if err not in winner_warnings:
            winner_warnings.append(err)

    return DeepHistoryResult(
        rows=trimmed_rows,
        source=winner.source,
        warnings=winner_warnings,
        metadata=winner_metadata,
    )


async def fetch_binance_history(
    *,
    symbol: str,
    interval: str,
    days: int,
    bars: int,
) -> DeepHistoryResult:
    provider_interval = BINANCE_INTERVALS.get(normalize_history_interval(interval), "1d")
    provider_symbol = _binance_symbol(symbol)
    end_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    start_ms = int((datetime.now(tz=timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    async with httpx.AsyncClient(timeout=12, headers={"User-Agent": "showMe-chart/1.0"}) as client:
        for endpoint, source in _binance_kline_endpoints():
            rows.clear()
            cursor = end_ms
            pages = math.ceil(bars / BINANCE_PAGE_LIMIT)
            try:
                for _ in range(max(1, pages)):
                    remaining = bars - len(rows)
                    if remaining <= 0 or cursor <= start_ms:
                        break
                    params = {
                        "symbol": provider_symbol,
                        "interval": provider_interval,
                        "limit": min(BINANCE_PAGE_LIMIT, remaining),
                        "endTime": cursor,
                    }
                    response = await client.get(endpoint, params=params)
                    response.raise_for_status()
                    page = response.json() or []
                    if not page:
                        break
                    shaped = _rows_from_binance_klines(page)
                    rows[:0] = shaped
                    first_open = int(page[0][0])
                    cursor = first_open - 1
                    if first_open <= start_ms:
                        break
                rows = [row for row in rows if _row_time_ms(row) >= start_ms]
                rows = _dedupe_sort_trim(rows, bars)
                if rows:
                    return DeepHistoryResult(
                        rows=rows,
                        source=source,
                        warnings=[],
                        metadata={
                            "provider_symbol": provider_symbol,
                            "interval": interval,
                            "provider_interval": provider_interval,
                            "days": days,
                            "bars_requested": bars,
                            "bars_returned": len(rows),
                            "deep_history": True,
                        },
                    )
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"{source}: {exc}")
    raise RuntimeError("; ".join(warnings) or f"no Binance history for {provider_symbol}")


def _binance_kline_endpoints() -> tuple[tuple[str, str], ...]:
    return (
        ("https://api.binance.com/api/v3/klines", "binance_spot"),
        ("https://fapi.binance.com/fapi/v1/klines", "binance_futures"),
    )


def longest_history_rows_to_dataframe(rows: list[dict[str, Any]]) -> Any:
    """Convert ``DeepHistoryResult.rows`` to the DataFrame shape that
    ``yfinance_adapter._fetch_ohlcv`` returns: a ``DatetimeIndex`` with
    lowercase ``open/high/low/close/volume`` columns (plus ``dividends``
    and ``splits`` as zero-filled placeholders so callers that touch
    those columns don't blow up).
    """
    import pandas as pd

    if not rows:
        return pd.DataFrame(
            columns=["open", "high", "low", "close", "volume", "dividends", "splits"]
        )
    frame = pd.DataFrame(rows)
    if "date" in frame.columns:
        idx = pd.to_datetime(frame["date"], utc=True, errors="coerce")
    elif "time" in frame.columns:
        idx = pd.to_datetime(frame["time"], unit="s", utc=True, errors="coerce")
    else:
        idx = pd.RangeIndex(len(frame))
    frame.index = idx
    frame.index.name = None
    for col in ("date", "time"):
        if col in frame.columns:
            frame = frame.drop(columns=[col])
    for col in ("open", "high", "low", "close", "volume"):
        if col not in frame.columns:
            frame[col] = pd.NA
        else:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
    if "dividends" not in frame.columns:
        frame["dividends"] = 0.0
    if "splits" not in frame.columns:
        frame["splits"] = 0.0
    return frame.sort_index()


class OhlcvLongestHistoryWrapper:
    """Drop-in proxy for an OHLCV-capable adapter (e.g. the bundled
    ``YFinanceAdapter``) that intercepts ``DataKind.OHLCV`` requests and
    routes them through :func:`fetch_longest_history`.

    All non-OHLCV kinds (``QUOTE``, ``REFDATA``, ``NEWS``, ...) pass
    through to the wrapped adapter unchanged. The wrapper exposes
    ``__getattr__`` so callers that read attributes (``.name``,
    ``.supported_kinds``) on the original adapter still work transparently.

    The wrapper is INTENTIONALLY conservative: any failure inside
    :func:`fetch_longest_history` falls back to the wrapped adapter, so
    existing behavior is preserved if the new path can't satisfy the
    request (e.g. obscure intervals).
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        # Proxy any attribute access that doesn't exist on us (e.g. name,
        # rate_limit_rps, supported_kinds, _client, etc.) to the inner
        # adapter so existing code that introspects the adapter still works.
        return getattr(self._inner, name)

    async def fetch(self, request: Any) -> Any:
        # Lazy import to avoid a hard dependency on the engine module
        # graph from chart_history (which is in the top-level package).
        try:
            from showme.engine.core.base_data_source import DataKind
        except Exception:
            return await self._inner.fetch(request)

        kind = getattr(request, "kind", None)
        if kind != DataKind.OHLCV:
            return await self._inner.fetch(request)

        instrument = getattr(request, "instrument", None)
        if instrument is None:
            return await self._inner.fetch(request)
        symbol = str(getattr(instrument, "symbol", "") or "").strip()
        if not symbol:
            return await self._inner.fetch(request)

        asset_class = str(
            getattr(getattr(instrument, "asset_class", None), "value", "") or ""
        ).upper()
        interval = normalize_history_interval(
            getattr(request, "interval", None) or "1d"
        )

        days = _days_from_request(request)
        limit = getattr(request, "limit", None)
        # When the caller didn't impose a bar cap we MATCH yfinance's
        # "return everything in the window" semantics by pushing the cap
        # all the way to MAX_BARS — otherwise functions like TECH/BETA
        # that omit ``limit`` would silently lose deep history.
        bars = parse_history_bars(limit if limit is not None else MAX_BARS)

        deep = True
        extra = getattr(request, "extra", None)
        if isinstance(extra, dict):
            val = extra.get("deep_history", extra.get("deep"))
            if val is not None:
                if isinstance(val, bool):
                    deep = val
                else:
                    deep = str(val).strip().lower() in {"1", "true", "yes", "on"}

        try:
            history = await fetch_longest_history(
                symbol=symbol,
                asset_class=asset_class,
                interval=interval,
                days=days,
                bars=bars,
                deep_history=deep,
            )
        except Exception:
            return await self._inner.fetch(request)

        if not history.rows:
            return await self._inner.fetch(request)
        return longest_history_rows_to_dataframe(history.rows)


def _days_from_request(request: Any) -> int:
    """Derive a ``days`` lookback from a ``DataRequest`` by inspecting
    ``start``, ``end``, and the ``extra`` dict in that priority order.
    Falls back to 365 when nothing useful is supplied.
    """
    start = getattr(request, "start", None)
    end = getattr(request, "end", None) or datetime.now(tz=timezone.utc)
    if start is not None:
        try:
            delta = end - start
            secs = delta.total_seconds()
            if secs > 0:
                return max(1, int(secs / 86_400))
        except Exception:
            pass
    extra = getattr(request, "extra", None) or {}
    for key in ("days", "lookback_days", "lookback"):
        value = extra.get(key) if isinstance(extra, dict) else None
        if value is None:
            continue
        try:
            return max(1, int(float(value)))
        except Exception:
            continue
    period = (extra.get("period") if isinstance(extra, dict) else None) or ""
    period = str(period).strip().lower()
    if period.endswith("y"):
        try:
            return max(1, int(float(period[:-1])) * 365)
        except Exception:
            pass
    if period.endswith("mo"):
        try:
            return max(1, int(float(period[:-2])) * 30)
        except Exception:
            pass
    if period.endswith("d"):
        try:
            return max(1, int(float(period[:-1])))
        except Exception:
            pass
    return 365


async def fetch_stooq_history(
    *,
    symbol: str,
    asset_class: str,
    interval: str,
    days: int,
    bars: int,
) -> DeepHistoryResult:
    """Fetch a Stooq EOD CSV — used purely as a deep-history candidate.

    Stooq's keyless CSV endpoint returns ALL available history when no date
    filter is supplied: AAPL goes back to 1980, ^SPX to 1957, BTCUSD to 2010.
    That makes Stooq the typical winner for stocks/indices in the longest-
    history race.
    """
    normalized = normalize_history_interval(interval)
    stooq_interval = STOOQ_INTERVALS.get(normalized)
    if stooq_interval is None:
        raise RuntimeError(f"stooq does not support interval {interval}")
    provider_symbol = _stooq_symbol(symbol, asset_class)
    if not provider_symbol:
        raise RuntimeError(f"stooq has no symbol mapping for {symbol}")
    api_key = os.environ.get(STOOQ_API_KEY_ENV, "")
    if not api_key:
        raise RuntimeError(
            f"{STOOQ_API_KEY_ENV} not set; stooq CSV requires an API key"
        )

    params: dict[str, Any] = {
        "s": provider_symbol,
        "i": stooq_interval,
        "apikey": api_key,
    }
    async with httpx.AsyncClient(
        timeout=15,
        headers={
            "User-Agent": "Mozilla/5.0 showMe-chart/1.0",
            "Accept": "text/csv,text/plain,*/*",
        },
        follow_redirects=True,
    ) as client:
        response = await client.get(
            "https://stooq.com/q/d/l/",
            params=params,
        )
        response.raise_for_status()
        text = response.text or ""
    head = text.lower()[:200]
    if not text or "apikey" in head or "no data" in head or len(text) < 30:
        raise RuntimeError(f"stooq returned no data for {provider_symbol}")

    rows = _rows_from_stooq_csv(text)
    rows = _dedupe_sort_trim(rows, bars)
    if not rows:
        raise RuntimeError(f"stooq returned no parseable rows for {provider_symbol}")
    return DeepHistoryResult(
        rows=rows,
        source="stooq",
        warnings=[],
        metadata={
            "provider_symbol": provider_symbol,
            "interval": interval,
            "provider_interval": stooq_interval,
            "days": days,
            "bars_requested": bars,
            "bars_returned": len(rows),
            "deep_history": True,
        },
    )


async def fetch_yahoo_history(
    *,
    symbol: str,
    asset_class: str,
    interval: str,
    days: int,
    bars: int,
) -> DeepHistoryResult:
    provider_symbol = _yahoo_symbol(symbol, asset_class)
    provider_interval = YAHOO_INTERVALS.get(normalize_history_interval(interval), "1d")
    clamped_days, clamp_warning = _clamp_yahoo_days(interval, days)
    end = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=clamped_days)
    params = {
        "period1": int(start.timestamp()),
        "period2": int(end.timestamp()),
        "interval": provider_interval,
        "includePrePost": "false",
        "events": "div,splits",
    }
    warnings = [clamp_warning] if clamp_warning else []
    async with httpx.AsyncClient(
        base_url="https://query1.finance.yahoo.com",
        timeout=12,
        headers={"User-Agent": "showMe-chart/1.0", "Accept": "application/json"},
    ) as client:
        response = await client.get(f"/v8/finance/chart/{provider_symbol}", params=params)
        response.raise_for_status()
        rows = _rows_from_yahoo_chart(response.json())
    rows = _dedupe_sort_trim(rows, bars)
    if not rows:
        raise RuntimeError(f"no Yahoo chart history for {provider_symbol}")
    return DeepHistoryResult(
        rows=rows,
        source="yahoo_chart",
        warnings=warnings,
        metadata={
            "provider_symbol": provider_symbol,
            "interval": interval,
            "provider_interval": provider_interval,
            "days": clamped_days,
            "bars_requested": bars,
            "bars_returned": len(rows),
            "deep_history": True,
        },
    )


def _binance_symbol(symbol: str) -> str:
    clean = str(symbol or "").upper().replace("/", "").replace("-", "").strip()
    base, quote = split_crypto_symbol(clean)
    return f"{base}{quote}"


def _stooq_symbol(symbol: str, asset_class: str) -> str:
    """Map a ShowMe symbol to its Stooq slug. ``asset_class`` is a hint —
    when it's unknown or wrong the fallback ``{lower}.us`` still resolves
    for most US equities Stooq tracks.
    """
    clean = str(symbol or "").strip().upper().replace("/", "").replace("-", "")
    if not clean:
        return ""
    asset = str(asset_class or "").upper()
    if asset == "CRYPTO":
        base, quote = split_crypto_symbol(clean)
        stooq_quote = "usd" if quote in {"USDT", "USDC", "USD"} else quote.lower()
        return f"{base.lower()}{stooq_quote}"
    if asset == "FX":
        clean = clean.removesuffix("=X")
        return clean.lower()
    if asset in {"INDEX", "INDICES"}:
        if not clean.startswith("^"):
            clean = "^" + clean
        return clean.lower()
    if asset == "COMMODITY":
        clean = clean.replace("=F", ".f")
        if "." not in clean.lower():
            clean = f"{clean}.f"
        return clean.lower()
    # equity / etf / fund / bond / fallback
    if "." in clean.lower():
        return clean.lower()
    if clean.startswith("^"):
        return clean.lower()
    return f"{clean.lower()}.us"


def _yahoo_symbol(symbol: str, asset_class: str) -> str:
    clean = str(symbol or "").strip().upper()
    if asset_class == "FX" and "=" not in clean:
        return f"{clean}=X"
    if asset_class == "CRYPTO":
        base, quote = split_crypto_symbol(clean)
        yahoo_quote = "USD" if quote in {"USDT", "USDC"} else quote
        return f"{base}-{yahoo_quote}"
    return clean


def _clamp_yahoo_days(interval: str, days: int) -> tuple[int, str | None]:
    normalized = normalize_history_interval(interval)
    limits = {
        "1m": 7,
        "2m": 60,
        "5m": 60,
        "15m": 60,
        "30m": 60,
        "1h": 730,
        "4h": 730,
    }
    max_days = limits.get(normalized)
    if max_days and days > max_days:
        return max_days, f"Yahoo limits {normalized} history to {max_days} days"
    return days, None


def _rows_from_stooq_csv(text: str) -> list[dict[str, Any]]:
    """Parse Stooq's standard CSV: ``Date,Open,High,Low,Close,Volume``.

    Stooq sometimes returns dates ending in ``-XX-XX`` for missing values
    or appends an empty trailing newline — we just skip unparseable lines.
    """
    rows: list[dict[str, Any]] = []
    buffer = StringIO(text)
    header_line = buffer.readline().strip()
    if not header_line:
        return rows
    header = [c.strip().lower() for c in header_line.split(",")]
    try:
        di = header.index("date")
        oi = header.index("open")
        hi = header.index("high")
        li = header.index("low")
        ci = header.index("close")
    except ValueError:
        return rows
    vi = header.index("volume") if "volume" in header else None
    for raw in buffer:
        line = raw.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) <= ci:
            continue
        date_str = parts[di]
        try:
            parsed = datetime.strptime(date_str, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
        except Exception:
            continue
        close = _num(parts[ci])
        if close is None:
            continue
        volume = (
            _num(parts[vi])
            if vi is not None and len(parts) > vi
            else None
        )
        rows.append(
            {
                "date": parsed.isoformat(),
                "time": int(parsed.timestamp()),
                "open": _num(parts[oi]),
                "high": _num(parts[hi]),
                "low": _num(parts[li]),
                "close": close,
                "volume": volume,
            }
        )
    return rows


def _rows_from_binance_klines(page: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in page:
        try:
            open_ms = int(item[0])
            rows.append({
                "date": datetime.fromtimestamp(open_ms / 1000, tz=timezone.utc).isoformat(),
                "time": open_ms // 1000,
                "open": _num(item[1]),
                "high": _num(item[2]),
                "low": _num(item[3]),
                "close": _num(item[4]),
                "volume": _num(item[5]),
            })
        except Exception:
            continue
    return [row for row in rows if row["close"] is not None]


def _rows_from_yahoo_chart(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = (((payload.get("chart") or {}).get("result") or [None])[0]) or {}
    timestamps = result.get("timestamp") or []
    quote = (((result.get("indicators") or {}).get("quote") or [None])[0]) or {}
    if not timestamps or not isinstance(quote, dict):
        return []
    rows: list[dict[str, Any]] = []
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    for idx, ts in enumerate(timestamps):
        close = _num(_at(closes, idx))
        if close is None:
            continue
        rows.append({
            "date": datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat(),
            "time": int(ts),
            "open": _num(_at(opens, idx)),
            "high": _num(_at(highs, idx)),
            "low": _num(_at(lows, idx)),
            "close": close,
            "volume": _num(_at(volumes, idx)),
        })
    return rows


def _dedupe_sort_trim(rows: list[dict[str, Any]], bars: int) -> list[dict[str, Any]]:
    by_time: dict[int, dict[str, Any]] = {}
    for row in rows:
        ts = _row_time_ms(row)
        if ts > 0:
            by_time[ts] = row
    ordered = [by_time[key] for key in sorted(by_time)]
    limit = max(1, min(MAX_BARS, int(bars)))
    return ordered[-limit:]


def _row_time_ms(row: dict[str, Any]) -> int:
    time_value = row.get("time")
    try:
        time_number = int(float(time_value))
        return time_number * 1000 if time_number < 10_000_000_000 else time_number
    except Exception:
        pass
    try:
        parsed = datetime.fromisoformat(str(row.get("date")).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1000)
    except Exception:
        return 0


def _at(values: list[Any], idx: int) -> Any:
    return values[idx] if idx < len(values) else None


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except Exception:
        return None
    return number if math.isfinite(number) else None
