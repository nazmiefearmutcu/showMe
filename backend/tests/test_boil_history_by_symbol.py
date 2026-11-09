"""BOIL#1 — each oil leg carries its own history.

BOIL served ONE history series for the whole payload, taken from the first
leg with history (CL=F), while both rows and the pane's sparklines used it.
The Brent card then showed WTI's trend. BOIL now returns
``history_by_symbol`` keyed by symbol; every point is that symbol's own close.

No live network: the yfinance provider is a stub keyed by symbol.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pandas as pd

from showme.engine.core.base_data_source import DataKind
from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.commodity._funcs import BOILFunction

CLOSES = {
    "CL=F": [90.1, 90.9, 91.2, 91.48],
    "BZ=F": [94.0, 95.5, 96.1, 96.28],
}
DATES = ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"]


class _Provider:
    async def fetch(self, request: Any) -> Any:
        symbol = request.instrument.symbol
        if request.kind == DataKind.OHLCV:
            closes = CLOSES[symbol]
            return pd.DataFrame(
                {
                    "open": closes,
                    "high": [c + 0.5 for c in closes],
                    "low": [c - 0.5 for c in closes],
                    "close": closes,
                    "volume": [1000, 1100, 1200, 1300],
                },
                index=pd.DatetimeIndex(pd.to_datetime(DATES)),
            )
        last = CLOSES[symbol][-1]
        return SimpleNamespace(
            last=last,
            close_prev=CLOSES[symbol][-2],
            high_24h=None,
            low_24h=None,
            open_24h=None,
            volume_24h=None,
            source="yfinance",
            timestamp=datetime.now(UTC),
        )


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_each_leg_has_its_own_history_series() -> None:
    fn = BOILFunction(deps=FunctionDeps(yfinance=_Provider()))
    inst = Instrument(symbol="BZ=F", asset_class=AssetClass.COMMODITY)
    data = _run(fn.execute(instrument=inst)).data

    by_symbol = data["history_by_symbol"]
    assert set(by_symbol) == {"CL=F", "BZ=F"}
    for symbol, closes in CLOSES.items():
        points = by_symbol[symbol]
        assert [p["close"] for p in points] == closes, symbol
        assert {p["symbol"] for p in points} == {symbol}, symbol


def test_brent_series_is_not_the_wti_series() -> None:
    fn = BOILFunction(deps=FunctionDeps(yfinance=_Provider()))
    data = _run(fn.execute()).data
    brent = [p["close"] for p in data["history_by_symbol"]["BZ=F"]]
    wti = [p["close"] for p in data["history_by_symbol"]["CL=F"]]
    assert brent != wti
    assert brent[-1] == 96.28
    assert wti[-1] == 91.48


def test_legacy_history_key_still_present_and_labelled() -> None:
    fn = BOILFunction(deps=FunctionDeps(yfinance=_Provider()))
    data = _run(fn.execute()).data
    assert data["history"], "primary-leg history stays available"
    assert {p["symbol"] for p in data["history"]} == {"CL=F"}


def test_history_by_symbol_is_empty_without_history() -> None:
    class _QuoteOnly(_Provider):
        async def fetch(self, request: Any) -> Any:
            if request.kind == DataKind.OHLCV:
                raise RuntimeError("no history")
            return await super().fetch(request)

    fn = BOILFunction(deps=FunctionDeps(yfinance=_QuoteOnly()))
    data = _run(fn.execute()).data
    assert data["status"] == "ok"
    assert data["history_by_symbol"] == {"CL=F": [], "BZ=F": []}
