"""Binance public market-data REST + WS adapter.

No authentication is required for the endpoints exposed here. The adapter
builds WebSocket URLs but does NOT open them — a separate stream consumer
should subscribe using :meth:`BinanceAdapter.ws_url`. Keeping the socket
open is out of scope for the per-request adapter contract.

Symbol convention: Binance uses no-slash uppercase tickers (``"BTCUSDT"``).
This adapter does NOT translate or normalise symbols — callers are
responsible for passing a Binance-shaped symbol. See each method docstring.
"""
from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlencode

from .base import AdapterError, DataMode, ProviderAdapter
from ._http import get_client

__all__ = ["BinanceAdapter"]

_REST_BASE = "https://api.binance.com"
_WS_BASE_SINGLE = "wss://stream.binance.com:9443/ws"
_WS_BASE_COMBINED = "wss://stream.binance.com:9443/stream"


class BinanceAdapter(ProviderAdapter):
    """Binance Spot market-data adapter (public endpoints only).

    Capabilities:
      * ``klines`` — historical OHLCV candles via ``/api/v3/klines``
      * ``ticker_24h`` — 24-hour rolling window stats via ``/api/v3/ticker/24hr``
      * ``exchange_info`` — full exchange + symbol metadata
      * ``ws_stream_url`` — builds ``wss://`` URLs for a stream consumer
    """

    name = "binance"
    nominal_mode = DataMode.LIVE_EXCHANGE

    def capabilities(self) -> set[str]:
        return {"klines", "ticker_24h", "exchange_info", "ws_stream_url"}

    # ---- REST ---------------------------------------------------------

    async def klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
    ) -> list[list[Any]]:
        """Fetch historical OHLCV candles.

        Args:
            symbol: Binance ticker, no slash, uppercase (e.g. ``"BTCUSDT"``).
                Callers must pre-normalise; the adapter does not translate.
            interval: Binance kline interval string
                (``"1m"``, ``"3m"``, ``"5m"``, ``"15m"``, ``"30m"``, ``"1h"``,
                ``"2h"``, ``"4h"``, ``"6h"``, ``"8h"``, ``"12h"``, ``"1d"``,
                ``"3d"``, ``"1w"``, ``"1M"``).
            limit: Max number of candles (Binance ceiling is 1000).

        Returns:
            Raw Binance kline matrix — each row is a 12-element list:
            ``[open_time, open, high, low, close, volume, close_time,
            quote_asset_volume, n_trades, taker_buy_base, taker_buy_quote,
            ignore]``.

        Raises:
            AdapterError: on HTTP failure / non-JSON / non-list response.
        """
        params = {"symbol": symbol, "interval": interval, "limit": int(limit)}
        url = f"{_REST_BASE}/api/v3/klines"
        client = await get_client()
        t0 = time.perf_counter()
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            self._record_failure(exc)
            raise AdapterError(f"binance klines failed: {exc}") from exc
        if not isinstance(payload, list):
            err = AdapterError(f"binance klines returned non-list: {type(payload).__name__}")
            self._record_failure(err)
            raise err
        self._record_success(int((time.perf_counter() - t0) * 1000))
        return payload

    async def ticker_24h(self, symbol: str) -> dict[str, Any]:
        """Fetch 24h rolling-window ticker stats.

        Args:
            symbol: Binance ticker, no slash, uppercase (e.g. ``"BTCUSDT"``).
        """
        params = {"symbol": symbol}
        url = f"{_REST_BASE}/api/v3/ticker/24hr"
        client = await get_client()
        t0 = time.perf_counter()
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            self._record_failure(exc)
            raise AdapterError(f"binance ticker_24h failed: {exc}") from exc
        if not isinstance(payload, dict):
            err = AdapterError(
                f"binance ticker_24h returned non-dict: {type(payload).__name__}"
            )
            self._record_failure(err)
            raise err
        self._record_success(int((time.perf_counter() - t0) * 1000))
        return payload

    async def exchange_info(self) -> dict[str, Any]:
        """Fetch the full exchange + symbols metadata document.

        This payload is large; cache aggressively at the caller layer.
        """
        url = f"{_REST_BASE}/api/v3/exchangeInfo"
        client = await get_client()
        t0 = time.perf_counter()
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            self._record_failure(exc)
            raise AdapterError(f"binance exchange_info failed: {exc}") from exc
        if not isinstance(payload, dict):
            err = AdapterError(
                f"binance exchange_info returned non-dict: {type(payload).__name__}"
            )
            self._record_failure(err)
            raise err
        self._record_success(int((time.perf_counter() - t0) * 1000))
        return payload

    # ---- WS URL builder ----------------------------------------------

    def ws_url(self, streams: list[str]) -> str:
        """Build a Binance WebSocket URL.

        Single-stream form (one entry) uses ``wss://stream.binance.com:9443/ws/<stream>``;
        combined form (>=2 entries) uses
        ``wss://stream.binance.com:9443/stream?streams=a/b/c`` per Binance docs.

        Args:
            streams: Stream names, e.g.
                ``["btcusdt@kline_1m", "ethusdt@trade"]``.

        Returns:
            A ready-to-open ``wss://`` URL.

        Raises:
            ValueError: if ``streams`` is empty.
        """
        if not streams:
            raise ValueError("ws_url requires at least one stream name")
        if len(streams) == 1:
            return f"{_WS_BASE_SINGLE}/{streams[0]}"
        query = urlencode({"streams": "/".join(streams)}, safe="/@")
        return f"{_WS_BASE_COMBINED}?{query}"
