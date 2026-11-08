"""BOIL#6 — an equal volume on consecutive bars is flagged, not rewritten.

Upstream daily bars for CL=F, BZ=F and NG=F show the same volume on
consecutive sessions (2026-11-05 and 2026-11-06 both show 335754 for CL=F)
while prices differ. The upstream bars do not say which of the two is the
copy, so BOIL keeps every reported value and flags both bars of the pair.
Nothing is nulled and nothing is labelled as a copy.

No live network: the yfinance provider is a stub.
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

DATES = ["2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]
CLOSES = {"CL=F": [88.0, 96.8, 88.1, 90.8], "BZ=F": [104.4, 94.6, 98.3, 98.3]}
VOLUMES = {"CL=F": [400000, 454113, 335754, 335754], "BZ=F": [60000, 64348, 53411, 53411]}
FLAG = "equal_to_adjacent_bar"


class _Provider:
    def __init__(self, quote_ok: bool = True) -> None:
        self.quote_ok = quote_ok

    async def fetch(self, request: Any) -> Any:
        symbol = request.instrument.symbol
        if request.kind == DataKind.OHLCV:
            closes = CLOSES[symbol]
            return pd.DataFrame(
                {
                    "open": closes,
                    "high": [c + 1 for c in closes],
                    "low": [c - 1 for c in closes],
                    "close": closes,
                    "volume": VOLUMES[symbol],
                },
                index=pd.DatetimeIndex(pd.to_datetime(DATES)),
            )
        if not self.quote_ok:
            raise RuntimeError("quote unavailable")
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


def test_equal_adjacent_volume_is_kept_and_both_bars_flagged() -> None:
    fn = BOILFunction(deps=FunctionDeps(yfinance=_Provider()))
    inst = Instrument(symbol="CL=F", asset_class=AssetClass.COMMODITY)
    data = _run(fn.execute(instrument=inst)).data
    wti = data["history_by_symbol"]["CL=F"]
    assert [p["volume"] for p in wti] == [400000, 454113, 335754, 335754]
    assert "volume_flag" not in wti[0]
    assert "volume_flag" not in wti[1]
    assert wti[2].get("volume_flag") == FLAG
    assert wti[3].get("volume_flag") == FLAG


def test_prices_are_kept_on_flagged_bars() -> None:
    fn = BOILFunction(deps=FunctionDeps(yfinance=_Provider()))
    data = _run(fn.execute()).data
    for symbol, closes in CLOSES.items():
        assert [p["close"] for p in data["history_by_symbol"][symbol]] == closes


def test_fallback_row_keeps_volume_and_flag_of_its_bar() -> None:
    # Quote unavailable: the row is built from the last history bar, which
    # shares its volume with the bar before it, so the row carries the flag.
    fn = BOILFunction(deps=FunctionDeps(yfinance=_Provider(quote_ok=False)))
    data = _run(fn.execute()).data
    wti_row = next(row for row in data["rows"] if row["symbol"] == "CL=F")
    assert wti_row["source"] == "yfinance_chart"
    assert wti_row["volume"] == 335754
    assert wti_row.get("volume_flag") == FLAG
