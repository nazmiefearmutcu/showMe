"""SECF quote enrichment must cover the returned page (wb1-g19 SECF#3).

Production wires the yfinance adapter: it has a batch quote endpoint, and its
per-symbol QUOTE path shares a 2 rps token bucket. The old SECF fan-out used
only the per-symbol path, so a 23-row page lost most quotes to the bucket and
the 3 s budget. These tests model that: a batch endpoint that covers every
symbol, and a serialized, slow per-symbol path. The page must come back live
via the batch, with no per-symbol fan-out needed.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.screen._funcs import SECFFunction, _security_reference_rows


class _BatchedBucketProvider:
    """Batch endpoint for every symbol; per-symbol path paced one call at a time."""

    def __init__(self, symbols: set[str]) -> None:
        self.symbols = symbols
        self.batch_calls = 0
        self.fetch_calls = 0
        self._lock: asyncio.Lock | None = None

    async def fetch_refdata_batch(self, symbols: list[str]) -> dict[str, Any]:
        self.batch_calls += 1
        return {
            symbol: {
                "regularMarketPrice": 100.0,
                "regularMarketPreviousClose": 99.0,
                "regularMarketChangePercent": 1.0,
                "regularMarketVolume": 1000.0,
            }
            for symbol in symbols
            if symbol in self.symbols
        }

    async def fetch(self, request: Any) -> Any:
        self.fetch_calls += 1
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            await asyncio.sleep(0.5)  # one shared bucket: symbols queue behind each other
        return SimpleNamespace(
            last=100.0,
            close_prev=99.0,
            high_24h=101.0,
            low_24h=98.0,
            volume_24h=1000.0,
        )


def _provider() -> _BatchedBucketProvider:
    return _BatchedBucketProvider({str(row["symbol"]) for row in _security_reference_rows()})


def test_dsl_page_quotes_cover_every_returned_row() -> None:
    provider = _provider()
    out = asyncio.run(
        SECFFunction(FunctionDeps(yfinance=provider)).execute(
            query="asset_class = EQUITY",
            limit=23,
            screen_timeout=1.0,
        )
    )
    rows = out.data["rows"]
    assert len(rows) == 23
    live = [row["symbol"] for row in rows if row.get("quote_state") == "live"]
    assert len(live) == 23, f"only {len(live)} of 23 rows got a live quote"
    assert provider.batch_calls >= 1
    assert provider.fetch_calls == 0, "batch covered the page; no per-symbol fan-out expected"
    assert "yfinance" in out.sources


def test_text_page_quotes_cover_every_returned_row() -> None:
    provider = _provider()
    out = asyncio.run(
        SECFFunction(FunctionDeps(yfinance=provider)).execute(
            query="technology",
            limit=23,
            screen_timeout=1.0,
        )
    )
    rows = out.data["rows"]
    assert len(rows) == 23
    live = [row["symbol"] for row in rows if row.get("quote_state") == "live"]
    assert len(live) == 23, f"only {len(live)} of 23 rows got a live quote"


def test_reference_mode_still_never_calls_provider() -> None:
    provider = _provider()
    out = asyncio.run(
        SECFFunction(FunctionDeps(yfinance=provider)).execute(
            query="asset_class = EQUITY",
            limit=23,
            reference=True,
        )
    )
    assert provider.batch_calls == 0
    assert provider.fetch_calls == 0
    assert all("quote_state" not in row or row["quote_state"] != "live" for row in out.data["rows"])
