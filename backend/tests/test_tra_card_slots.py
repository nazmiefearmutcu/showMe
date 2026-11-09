"""TRA#4: every TRA card slot reads a scalar the served output declares.

Card slots read top-level keys (dpf.py). A slot that points at a missing key
or at a container renders nothing or a list. A "%" slot must hold a percent
value (132.99 means 132.99%), not a fraction.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio._more import TRAFunction
from showme.manifest import REGISTRY, load_seeds


@pytest.fixture(scope="module", autouse=True)
def _load_seeds_once() -> None:
    load_seeds()


class _Yf:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    async def fetch(self, request: Any) -> pd.DataFrame:  # noqa: ARG002
        return self._frame


def test_tra_card_slots_are_served_scalars() -> None:
    idx = pd.date_range("2024-01-02", periods=5, freq="B", tz="UTC")
    frame = pd.DataFrame(
        {"close": [100.0, 100.0, 100.0, 100.0, 100.0], "dividends": [0.0, 2.0, 0.0, 0.0, 0.0]},
        index=idx,
    )
    res = asyncio.run(TRAFunction(FunctionDeps(yfinance=_Yf(frame))).execute(
        instrument=Instrument(symbol="ABC", asset_class=AssetClass.EQUITY)))
    entry = REGISTRY.get("TRA")
    assert entry.card_schema is not None
    for slot in entry.card_schema.slots:
        assert slot.key in res.data, f"TRA card slot {slot.key!r} is not a served top-level key"
        assert not isinstance(res.data[slot.key], (list, dict)), (
            f"TRA card slot {slot.key!r} is a container, not a scalar"
        )


def test_tra_percent_slots_hold_percent_values() -> None:
    idx = pd.date_range("2024-01-02", periods=5, freq="B", tz="UTC")
    frame = pd.DataFrame(
        {"close": [100.0, 100.0, 100.0, 100.0, 100.0], "dividends": [0.0, 2.0, 0.0, 0.0, 0.0]},
        index=idx,
    )
    res = asyncio.run(TRAFunction(FunctionDeps(yfinance=_Yf(frame))).execute(
        instrument=Instrument(symbol="ABC", asset_class=AssetClass.EQUITY)))
    # TWR is 2% as a fraction; the card's percent value is 2.0.
    assert res.data["twr_total"] == pytest.approx(0.02)
    assert res.data["twr_total_pct"] == pytest.approx(2.0)
    entry = REGISTRY.get("TRA")
    for slot in entry.card_schema.slots:
        if slot.unit == "%":
            assert slot.key.endswith("_pct"), f"TRA percent slot {slot.key} must hold a percent value"
