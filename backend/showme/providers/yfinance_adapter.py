"""Yahoo Finance (``yfinance`` package) adapter.

yfinance scrapes Yahoo's free-tier endpoints; the data is delayed by
~15 minutes for US equities and provider-dependent for everything else,
so the nominal mode is :pyattr:`DataMode.DELAYED_REFERENCE`.

The ``yfinance`` library is synchronous and blocks the event loop on
network I/O. Every method here wraps the call in :func:`asyncio.to_thread`
so the FastAPI worker stays responsive.

Symbol convention: ``yfinance`` uses dot-suffix tickers for non-US
listings (``"BMW.DE"``, ``"7203.T"``, ``"VOD.L"``) and crypto pairs use
``-USD`` (``"BTC-USD"``). This adapter does NOT translate symbols —
callers must pre-normalise.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import pandas as pd

from .base import AdapterError, DataMode, ProviderAdapter

__all__ = ["YfinanceAdapter"]


class YfinanceAdapter(ProviderAdapter):
    """Adapter around the ``yfinance`` Python package.

    Capabilities:
      * ``history`` — OHLCV history as a pandas DataFrame
      * ``info`` — fundamental + descriptive fields (slow, large dict)
      * ``fast_info`` — cheap mostly-cached subset of ``info``
      * ``earnings_dates`` — upcoming + recent earnings calendar
      * ``get_news`` — Yahoo-curated news links for the symbol
    """

    name = "yfinance"
    nominal_mode = DataMode.DELAYED_REFERENCE

    def capabilities(self) -> set[str]:
        return {"history", "info", "fast_info", "earnings_dates", "get_news"}

    # ---- thread-offloaded helpers ------------------------------------

    @staticmethod
    def _ticker(symbol: str) -> Any:
        """Construct a ``yfinance.Ticker``. Imported lazily so module
        import does not require ``yfinance`` to be installed.
        """
        import yfinance as yf  # local import keeps import-time light
        return yf.Ticker(symbol)

    async def _run(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Run a blocking callable on the default thread pool and record
        success / failure on the adapter contract.
        """
        t0 = time.perf_counter()
        try:
            result = await asyncio.to_thread(fn, *args, **kwargs)
        except Exception as exc:
            self._record_failure(exc)
            raise AdapterError(f"yfinance call failed: {exc}") from exc
        self._record_success(int((time.perf_counter() - t0) * 1000))
        return result

    # ---- public API ---------------------------------------------------

    async def history(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Return OHLCV history as a pandas DataFrame.

        Args:
            symbol: Yahoo-shaped ticker (``"AAPL"``, ``"BMW.DE"``,
                ``"BTC-USD"``). Caller normalises; the adapter does not
                translate.
            period: ``yfinance`` period string (``"1d"``, ``"5d"``,
                ``"1mo"``, ``"3mo"``, ``"6mo"``, ``"1y"``, ``"2y"``,
                ``"5y"``, ``"10y"``, ``"ytd"``, ``"max"``).
            interval: bar size (``"1m"``..``"1h"``, ``"1d"``, ``"1wk"``,
                ``"1mo"``, ``"3mo"``).
        """
        def _call() -> pd.DataFrame:
            return self._ticker(symbol).history(period=period, interval=interval)
        return await self._run(_call)

    async def info(self, symbol: str) -> dict[str, Any]:
        """Return the (slow, ~150-key) ``yfinance.Ticker.info`` dict."""
        def _call() -> dict[str, Any]:
            payload = self._ticker(symbol).info
            return dict(payload) if payload else {}
        return await self._run(_call)

    async def fast_info(self, symbol: str) -> dict[str, Any]:
        """Return the cheap ``fast_info`` mapping.

        ``fast_info`` is a special object in yfinance — we coerce it to a
        regular ``dict`` so it serialises cleanly through FastAPI.
        """
        def _call() -> dict[str, Any]:
            fi = self._ticker(symbol).fast_info
            if fi is None:
                return {}
            # yfinance.FastInfo supports dict-like iteration. Be defensive:
            # some keys raise on access (e.g. when the symbol is invalid).
            out: dict[str, Any] = {}
            try:
                keys = list(fi.keys())  # type: ignore[union-attr]
            except Exception:
                # fall back to the documented attribute set
                keys = [
                    "currency", "last_price", "previous_close", "open",
                    "day_high", "day_low", "year_high", "year_low",
                    "fifty_day_average", "two_hundred_day_average",
                    "shares", "market_cap", "ten_day_average_volume",
                    "three_month_average_volume", "regular_market_previous_close",
                ]
            for key in keys:
                try:
                    out[key] = fi[key]  # type: ignore[index]
                except Exception:
                    continue
            return out
        return await self._run(_call)

    async def earnings_dates(self, symbol: str) -> pd.DataFrame | None:
        """Return earnings calendar DataFrame or ``None`` when unavailable."""
        def _call() -> pd.DataFrame | None:
            ed = self._ticker(symbol).earnings_dates
            return ed
        return await self._run(_call)

    async def get_news(self, symbol: str) -> list[dict[str, Any]]:
        """Return the Yahoo-curated news feed for the symbol.

        Each entry follows yfinance's native schema (``uuid``, ``title``,
        ``publisher``, ``link``, ``providerPublishTime`` epoch s, ...).
        Always returns a list — empty when yfinance returns ``None``.
        """
        def _call() -> list[dict[str, Any]]:
            news = self._ticker(symbol).get_news()
            if not news:
                return []
            # Each entry is already a plain dict in modern yfinance versions.
            return [dict(item) for item in news]
        return await self._run(_call)
