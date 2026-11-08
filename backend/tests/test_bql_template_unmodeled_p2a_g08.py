"""BQL must not fabricate unmodeled fields (p2a-g08, FLDS#1; reconciled with BQL#6).

Originally written for the offline computed_model template, which copied the
close series into any unmodeled field. That offline template is removed (BQL
returns provider data only), so the guard now runs on the live yfinance path:
a field yfinance does not provide is never filled with another series' value
(it is absent or null) and is named in a warning.

Network-free: the yfinance provider is a fake that returns an OHLCV frame.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.api.bql import BQLFunction

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


class _FakeYf:
    async def fetch(self, request: Any) -> pd.DataFrame:
        idx = pd.DatetimeIndex(
            [pd.Timestamp("2026-11-05", tz="UTC"), pd.Timestamp("2026-11-06", tz="UTC")]
        )
        return pd.DataFrame(
            {
                "Open": [340.0, 341.0],
                "High": [343.0, 344.0],
                "Low": [339.0, 340.5],
                "Close": [342.0, 342.37],
                "Volume": [50_000_000, 48_000_000],
            },
            index=idx,
        )


def _run(query: str):
    fn = BQLFunction(FunctionDeps(yfinance=_FakeYf()))
    return asyncio.run(fn.execute(instrument=AAPL, query=query, live=True)).data


def test_unmodeled_fundamental_field_is_null_not_the_close_value():
    data = _run("get(close, pe) for(['AAPL'])")
    rows = data["rows"]
    assert rows, data
    for row in rows:
        assert row.get("pe") is None, row
        assert row.get("pe") != row["close"], row


def test_unmodeled_field_is_reported_as_a_warning():
    data = _run("get(close, pe) for(['AAPL'])")
    assert any("pe" in str(w) for w in data["warnings"]), data["warnings"]


def test_modeled_ohlcv_fields_are_still_returned_as_numbers():
    data = _run("get(close, volume) for(['AAPL'])")
    for row in data["rows"]:
        assert isinstance(row["close"], float), row
        assert isinstance(row["volume"], (int, float)), row
    assert data["warnings"] == []
