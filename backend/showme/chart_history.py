"""Deep OHLCV history helpers for terminal-grade chart panes.

The normal ShowMe data-source adapters optimize for broad function execution,
not chart UX. In practice that meant crypto charts often stopped around one
page of candles. This module gives GP/HP/WATCH a direct, pageable history path:
Binance klines for crypto and Yahoo chart history for listed assets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import math
from typing import Any

import httpx

from showme.crypto_aliases import split_crypto_symbol


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

DEFAULT_BARS = 1_500
MAX_BARS = 20_000
BINANCE_PAGE_LIMIT = 1_000


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
    """Fetch chart history from a direct pageable provider."""
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
