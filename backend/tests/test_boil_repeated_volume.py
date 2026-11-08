"""BOIL#6 — a volume that repeats the previous session is withheld, not served.

Upstream daily bars for CL=F, BZ=F and NG=F repeat the previous session's
volume exactly on consecutive days (2026-11-05 and 2026-11-06 both show
335754 for CL=F) while prices differ, so the repeated volume is a copy, not a
print. BOIL nulls that bar's volume, flags it, and keeps the prices.

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


def test_repeated_session_volume_is_withheld_and_flagged() -> None:
    fn = BOILFunction(deps=FunctionDeps(yfinance=_Provider()))
    inst = Instrument(symbol="CL=F", asset_class=AssetClass.COMMODITY)
    data = _run(fn.execute(instrument=inst)).data
    wti = data["history_by_symbol"]["CL=F"]
    assert [p["volume"] for p in wti] == [400000, 454113, 335754, None]
    assert wti[3].get("volume_flag") == "repeats_previous_session"
    assert "volume_flag" not in wti[2]


def test_prices_are_kept_on_flagged_bars() -> None:
    fn = BOILFunction(deps=FunctionDeps(yfinance=_Provider()))
    data = _run(fn.execute()).data
    for symbol, closes in CLOSES.items():
        assert [p["close"] for p in data["history_by_symbol"][symbol]] == closes


def test_fallback_row_volume_does_not_repeat_a_copied_bar() -> None:
    # Quote unavailable: the row is built from the last history bar, which is
    # the repeated one for CL=F, so its volume must be withheld too.
    fn = BOILFunction(deps=FunctionDeps(yfinance=_Provider(quote_ok=False)))
    data = _run(fn.execute()).data
    wti_row = next(row for row in data["rows"] if row["symbol"] == "CL=F")
    assert wti_row["source"] == "yfinance_chart"
    assert wti_row["volume"] is None
