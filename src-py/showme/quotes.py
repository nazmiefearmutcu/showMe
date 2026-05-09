"""Fast quote snapshots for WATCH and quote streams.

This module deliberately avoids ShowMe function execution. WATCH needs a small,
reliable last-price service; routing it through DES couples it to slower
company-description paths and leaves equities blank when DES does not expose
quote fields.
"""
from __future__ import annotations

import asyncio
import csv
import os
from datetime import datetime, timezone
from io import StringIO
from typing import Any

import requests

from showme.crypto_aliases import (
    is_crypto_symbol as _is_crypto_symbol,
    resolve_crypto_symbol_alias,
    split_crypto_symbol,
)
COINGECKO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "SOL": "solana",
    "ADA": "cardano",
    "XRP": "ripple",
    "DOGE": "dogecoin",
    "MATIC": "polygon-pos",
    "DOT": "polkadot",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
    "TRX": "tron",
    "LTC": "litecoin",
    "BCH": "bitcoin-cash",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "FLOCK": "flock-2",
}


class QuoteFetchError(RuntimeError):
    """Raised when every quote provider fails for a symbol."""


async def fetch_quote_snapshot(symbol: str) -> dict[str, Any]:
    """Return a normalized last-price snapshot for crypto or equities."""
    target = clean_symbol(symbol)
    if not target:
        raise QuoteFetchError("empty symbol")
    if os.environ.get("SHOWME_LIVE_QUOTES") == "0":
        raise QuoteFetchError("live quotes disabled by SHOWME_LIVE_QUOTES=0")
    if is_crypto_symbol(target):
        return await asyncio.to_thread(fetch_crypto_quote_sync, target)
    return await asyncio.to_thread(fetch_equity_quote_sync, target)


def fallback_quote_snapshot(symbol: str, reason: str | None = None) -> dict[str, Any]:
    target = clean_symbol(symbol) or "AAPL"
    crypto = is_crypto_symbol(target)
    last = 78000.0 if crypto else 100.0
    previous = last * 0.99
    base, quote = split_crypto_symbol(target) if crypto else (target, "USD")
    return normalized_snapshot(
        symbol=target,
        asset_class="CRYPTO" if crypto else "EQUITY",
        last=last,
        previous_close=previous,
        change_pct=percent_change(last, previous),
        volume=1250000.0 if crypto else 1000000.0,
        bid=last * 0.999,
        ask=last * 1.001,
        source="showme_quote_template",
        provider_symbol=f"{base}{quote}" if crypto else target,
        currency=quote if crypto else "USD",
        raw={"provider_error": reason} if reason else {},
    )


def clean_symbol(symbol: str) -> str:
    return resolve_crypto_symbol_alias(symbol, allow_network=False) or str(symbol or "").strip().upper()


def is_crypto_symbol(symbol: str) -> bool:
    return _is_crypto_symbol(clean_symbol(symbol))


def fetch_crypto_quote_sync(symbol: str) -> dict[str, Any]:
    attempts: list[str] = []
    for provider in (
        _fetch_binance_quote,
        _fetch_binance_futures_quote,
        _fetch_cryptocompare_quote,
        _fetch_coingecko_quote,
    ):
        try:
            snapshot = provider(symbol)
            if snapshot.get("last") is not None:
                return snapshot
        except Exception as exc:  # noqa: BLE001
            attempts.append(f"{provider.__name__}: {exc}")
    raise QuoteFetchError("; ".join(attempts) or f"no crypto quote for {symbol}")


def fetch_equity_quote_sync(symbol: str) -> dict[str, Any]:
    attempts: list[str] = []
    for provider in (_fetch_yahoo_chart_quote, _fetch_stooq_quote, _fetch_yfinance_quote):
        try:
            snapshot = provider(symbol)
            if snapshot.get("last") is not None:
                return snapshot
        except Exception as exc:  # noqa: BLE001
            attempts.append(f"{provider.__name__}: {exc}")
    raise QuoteFetchError("; ".join(attempts) or f"no equity quote for {symbol}")


def _fetch_binance_quote(symbol: str) -> dict[str, Any]:
    response = requests.get(
        "https://api.binance.com/api/v3/ticker/24hr",
        params={"symbol": clean_symbol(symbol)},
        headers={"User-Agent": "showMe/1.0"},
        timeout=2.5,
    )
    response.raise_for_status()
    payload = response.json() or {}
    last = number(payload.get("lastPrice"))
    prev = number(payload.get("openPrice"))
    return normalized_snapshot(
        symbol=symbol,
        asset_class="CRYPTO",
        last=last,
        previous_close=prev,
        change_pct=number(payload.get("priceChangePercent")),
        volume=number(payload.get("volume")),
        bid=number(payload.get("bidPrice")),
        ask=number(payload.get("askPrice")),
        source="binance",
        provider_symbol=str(payload.get("symbol") or symbol).upper(),
        currency=split_crypto_symbol(symbol)[1],
        raw={
            "high": number(payload.get("highPrice")),
            "low": number(payload.get("lowPrice")),
            "quote_volume": number(payload.get("quoteVolume")),
        },
    )


def _fetch_binance_futures_quote(symbol: str) -> dict[str, Any]:
    response = requests.get(
        "https://fapi.binance.com/fapi/v1/ticker/24hr",
        params={"symbol": clean_symbol(symbol)},
        headers={"User-Agent": "showMe/1.0"},
        timeout=2.5,
    )
    response.raise_for_status()
    payload = response.json() or {}
    last = number(payload.get("lastPrice"))
    prev = number(payload.get("openPrice"))
    return normalized_snapshot(
        symbol=symbol,
        asset_class="CRYPTO",
        last=last,
        previous_close=prev,
        change_pct=number(payload.get("priceChangePercent")),
        volume=number(payload.get("volume")),
        bid=None,
        ask=None,
        source="binance_futures",
        provider_symbol=str(payload.get("symbol") or symbol).upper(),
        currency=split_crypto_symbol(symbol)[1],
        raw={
            "high": number(payload.get("highPrice")),
            "low": number(payload.get("lowPrice")),
            "quote_volume": number(payload.get("quoteVolume")),
            "venue": "usdm_futures",
        },
    )


def _fetch_cryptocompare_quote(symbol: str) -> dict[str, Any]:
    base, quote = split_crypto_symbol(symbol)
    quote_cc = "USD" if quote == "USDT" else quote
    response = requests.get(
        "https://min-api.cryptocompare.com/data/pricemultifull",
        params={"fsyms": base, "tsyms": quote_cc},
        headers={"User-Agent": "showMe/1.0"},
        timeout=2.5,
    )
    response.raise_for_status()
    payload = response.json() or {}
    raw = (((payload.get("RAW") or {}).get(base) or {}).get(quote_cc) or {})
    if not raw:
        raise QuoteFetchError(f"CryptoCompare returned no RAW quote for {symbol}")
    last = number(raw.get("PRICE"))
    prev = number(raw.get("OPEN24HOUR"))
    return normalized_snapshot(
        symbol=symbol,
        asset_class="CRYPTO",
        last=last,
        previous_close=prev,
        change_pct=percent_change(last, prev),
        volume=number(raw.get("VOLUME24HOUR")),
        bid=None,
        ask=None,
        source="cryptocompare",
        provider_symbol=f"{base}{quote_cc}",
        currency=quote_cc,
        raw={
            "high": number(raw.get("HIGH24HOUR")),
            "low": number(raw.get("LOW24HOUR")),
            "market_cap": number(raw.get("MKTCAP")),
        },
    )


def _fetch_coingecko_quote(symbol: str) -> dict[str, Any]:
    base, quote = split_crypto_symbol(symbol)
    coin_id = COINGECKO_IDS.get(base, base.lower())
    vs = "usd" if quote == "USDT" else quote.lower()
    response = requests.get(
        "https://api.coingecko.com/api/v3/simple/price",
        params={
            "ids": coin_id,
            "vs_currencies": vs,
            "include_24hr_change": "true",
            "include_24hr_vol": "true",
            "include_market_cap": "true",
        },
        headers={"User-Agent": "showMe/1.0", "Accept": "application/json"},
        timeout=2.5,
    )
    response.raise_for_status()
    payload = (response.json() or {}).get(coin_id) or {}
    last = number(payload.get(vs))
    return normalized_snapshot(
        symbol=symbol,
        asset_class="CRYPTO",
        last=last,
        previous_close=None,
        change_pct=number(payload.get(f"{vs}_24h_change")),
        volume=number(payload.get(f"{vs}_24h_vol")),
        bid=None,
        ask=None,
        source="coingecko",
        provider_symbol=coin_id,
        currency=vs.upper(),
        raw={"market_cap": number(payload.get(f"{vs}_market_cap"))},
    )


def _fetch_yahoo_chart_quote(symbol: str) -> dict[str, Any]:
    provider_symbol = yahoo_symbol(symbol)
    response = requests.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{provider_symbol}",
        params={"range": "5d", "interval": "1d", "includePrePost": "false"},
        headers={"User-Agent": "showMe/1.0", "Accept": "application/json"},
        timeout=2.5,
    )
    response.raise_for_status()
    payload = response.json() or {}
    result = (((payload.get("chart") or {}).get("result") or [None])[0]) or {}
    meta = result.get("meta") or {}
    quote = (((result.get("indicators") or {}).get("quote") or [None])[0]) or {}
    closes = [number(v) for v in quote.get("close") or []]
    volumes = [number(v) for v in quote.get("volume") or []]
    last_close = last_non_null(closes)
    last = number(meta.get("regularMarketPrice")) or last_close
    prev = (
        number(meta.get("previousClose"))
        or number(meta.get("chartPreviousClose"))
        or previous_non_null(closes)
    )
    volume = number(meta.get("regularMarketVolume")) or last_non_null(volumes)
    return normalized_snapshot(
        symbol=symbol,
        asset_class="EQUITY",
        last=last,
        previous_close=prev,
        change_pct=percent_change(last, prev),
        volume=volume,
        bid=number(meta.get("bid")),
        ask=number(meta.get("ask")),
        source="yahoo_chart",
        provider_symbol=provider_symbol,
        currency=meta.get("currency"),
        raw={
            "exchange": meta.get("exchangeName") or meta.get("fullExchangeName"),
            "regular_market_time": meta.get("regularMarketTime"),
            "timezone": meta.get("timezone"),
        },
    )


def _fetch_stooq_quote(symbol: str) -> dict[str, Any]:
    provider_symbol = stooq_symbol(symbol)
    response = requests.get(
        "https://stooq.com/q/l/",
        params={"s": provider_symbol, "f": "sd2t2ohlcv", "h": "", "e": "csv"},
        headers={"User-Agent": "showMe/1.0"},
        timeout=2.5,
    )
    response.raise_for_status()
    rows = list(csv.DictReader(StringIO(response.text)))
    if not rows:
        raise QuoteFetchError(f"Stooq returned no row for {symbol}")
    row = rows[0]
    last = number(row.get("Close"))
    return normalized_snapshot(
        symbol=symbol,
        asset_class="EQUITY",
        last=last,
        previous_close=None,
        change_pct=None,
        volume=number(row.get("Volume")),
        bid=None,
        ask=None,
        source="stooq",
        provider_symbol=provider_symbol,
        currency=None,
        raw={"date": row.get("Date"), "time": row.get("Time")},
    )


def _fetch_yfinance_quote(symbol: str) -> dict[str, Any]:
    import yfinance as yf

    provider_symbol = yahoo_symbol(symbol)
    ticker = yf.Ticker(provider_symbol)
    info = getattr(ticker, "fast_info", {}) or {}
    get = info.get if hasattr(info, "get") else lambda _k, _default=None: None
    last = number(get("last_price"))
    prev = number(get("previous_close"))
    return normalized_snapshot(
        symbol=symbol,
        asset_class="EQUITY",
        last=last,
        previous_close=prev,
        change_pct=percent_change(last, prev),
        volume=number(get("last_volume")),
        bid=number(get("bid")),
        ask=number(get("ask")),
        source="yfinance_fast_info",
        provider_symbol=provider_symbol,
        currency=get("currency"),
        raw={},
    )


def yahoo_symbol(symbol: str) -> str:
    return clean_symbol(symbol).replace("/", "-")


def stooq_symbol(symbol: str) -> str:
    value = clean_symbol(symbol).replace("/", ".").lower()
    if "." not in value:
        return f"{value}.us"
    return value


def normalized_snapshot(
    *,
    symbol: str,
    asset_class: str,
    last: float | None,
    previous_close: float | None,
    change_pct: float | None,
    volume: float | None,
    bid: float | None,
    ask: float | None,
    source: str,
    provider_symbol: str,
    currency: Any,
    raw: dict[str, Any],
) -> dict[str, Any]:
    if last is None:
        raise QuoteFetchError(f"{source} returned no last price for {symbol}")
    if change_pct is None:
        change_pct = percent_change(last, previous_close)
    fetched_at = datetime.now(timezone.utc).isoformat()
    return {
        "symbol": clean_symbol(symbol),
        "asset_class": asset_class,
        "last": last,
        "price": last,
        "previous_close": previous_close,
        "previousClose": previous_close,
        "change_pct": change_pct,
        "regularMarketChangePercent": change_pct,
        "volume": volume,
        "bid": bid,
        "ask": ask,
        "source": source,
        "provider_symbol": provider_symbol,
        "currency": currency,
        "fetched_at": fetched_at,
        "raw": raw,
    }


def number(value: Any) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def last_non_null(values: list[float | None]) -> float | None:
    for value in reversed(values):
        if value is not None:
            return value
    return None


def previous_non_null(values: list[float | None]) -> float | None:
    seen_last = False
    for value in reversed(values):
        if value is None:
            continue
        if not seen_last:
            seen_last = True
            continue
        return value
    return None


def percent_change(last: float | None, previous: float | None) -> float | None:
    if last is None or previous in (None, 0):
        return None
    return (last / previous - 1.0) * 100.0


__all__ = [
    "QuoteFetchError",
    "clean_symbol",
    "fallback_quote_snapshot",
    "fetch_quote_snapshot",
    "is_crypto_symbol",
    "split_crypto_symbol",
]
