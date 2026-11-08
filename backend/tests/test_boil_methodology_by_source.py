"""BOIL#5 — the methodology describes the data actually served.

The success envelope carried one static methodology that claimed daily OHLCV
history from Yahoo chart data, even when the reference model returned no
history at all (live=false) or a leg had no history.

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
from showme.engine.functions.commodity._funcs import BOILFunction


class _Quotes:
    """Quote-only provider; history is configurable per symbol."""

    def __init__(self, history_symbols: set[str]) -> None:
        self.history_symbols = history_symbols

    async def fetch(self, request: Any) -> Any:
        symbol = request.instrument.symbol
        if request.kind == DataKind.OHLCV:
            if symbol not in self.history_symbols:
                raise RuntimeError("no history")
            closes = [90.0, 91.0, 92.0]
            return pd.DataFrame(
                {
                    "open": closes,
                    "high": closes,
                    "low": closes,
                    "close": closes,
                    "volume": [1, 2, 3],
                },
                index=pd.DatetimeIndex(pd.to_datetime(["2026-09-01", "2026-09-02", "2026-09-03"])),
            )
        last, prev = {"CL=F": (78.0, 77.5), "BZ=F": (82.0, 81.0)}[symbol]
        return SimpleNamespace(
            last=last,
            close_prev=prev,
            high_24h=None,
            low_24h=None,
            open_24h=None,
            volume_24h=None,
            source="yfinance",
            timestamp=datetime.now(UTC),
        )


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_reference_model_does_not_claim_yahoo_history() -> None:
    fn = BOILFunction(deps=FunctionDeps(yfinance=_Quotes({"CL=F", "BZ=F"})))
    data = _run(fn.execute(live=False)).data
    assert data["source_mode"] == "model"
    assert data["history"] == []
    text = data["methodology"]
    assert "Yahoo" not in text, text
    assert "reference" in text.lower(), text


def test_live_with_no_history_says_so() -> None:
    fn = BOILFunction(deps=FunctionDeps(yfinance=_Quotes(set())))
    data = _run(fn.execute()).data
    assert data["source_mode"] == "live_yfinance"
    assert data["history"] == []
    text = data["methodology"]
    assert "no daily history" in text.lower(), text


def test_live_with_history_describes_yahoo_chart_per_leg() -> None:
    fn = BOILFunction(deps=FunctionDeps(yfinance=_Quotes({"CL=F", "BZ=F"})))
    data = _run(fn.execute()).data
    text = data["methodology"]
    assert "Yahoo chart" in text, text
    assert "history_by_symbol" in text, text
