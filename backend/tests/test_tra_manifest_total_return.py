"""TRA#4: the TRA manifest must describe the served Total Return Analysis.

The manifest registered under TRA used to be a per-fill broker ledger
("Transaction Analysis", credential_id, date_range, side_filter...) while the
executing class is Total Return Analysis with years and reference inputs.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio._more import TRAFunction
from showme.manifest import REGISTRY, load_seeds


def setup_module() -> None:
    load_seeds()


def test_manifest_name_matches_served_function() -> None:
    entry = REGISTRY.get("TRA")
    assert entry.name == TRAFunction.name == "Total Return Analysis"


def test_manifest_inputs_are_the_served_inputs() -> None:
    entry = REGISTRY.get("TRA")
    names = {i.name for i in entry.inputs}
    assert {"years", "reference"} <= names
    # The fill-ledger inputs belonged to a different, unserved function.
    assert "credential_id" not in names
    assert "side_filter" not in names


def test_manifest_intent_describes_total_return() -> None:
    entry = REGISTRY.get("TRA")
    assert "total return" in entry.intent.lower()
    assert "fill" not in entry.intent.lower()


def test_function_has_description_for_the_catalog() -> None:
    assert (TRAFunction.description or "").strip()


class _Yf:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    async def fetch(self, request: Any) -> pd.DataFrame:  # noqa: ARG002
        return self._frame


def test_manifest_must_have_fields_are_returned_by_the_handler() -> None:
    # TRA#4 residual: check the handler's actual output, not a hard-coded set.
    entry = REGISTRY.get("TRA")
    assert entry.output_contract.must_have, "TRA manifest declares no must_have fields"
    idx = pd.date_range("2024-01-02", periods=5, freq="B", tz="UTC")
    frame = pd.DataFrame(
        {"close": [100.0, 101.0, 102.0, 101.5, 103.0], "dividends": [0.0, 0.0, 0.5, 0.0, 0.0]},
        index=idx,
    )
    instrument = Instrument(symbol="ABC", asset_class=AssetClass.EQUITY)
    res = asyncio.run(
        TRAFunction(FunctionDeps(yfinance=_Yf(frame))).execute(instrument=instrument)
    )
    missing = [key for key in entry.output_contract.must_have if key not in res.data]
    assert not missing, f"TRA must_have fields not returned by the handler: {missing}"
