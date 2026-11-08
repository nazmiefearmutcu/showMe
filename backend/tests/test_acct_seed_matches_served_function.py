"""ACCT#3: the ACCT manifest must describe the function that is actually served.

The served handler (``engine/functions/portfolio/acct.py``) is a multi-account
position roll-up. The manifest used to describe a broker ``account()``
snapshot (equity, cash, margin, buying power, credential_id) that the handler
never returns, so every must_have field was dead.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.quote import Quote, utcnow
from showme.engine.functions.portfolio import acct as acct_mod
from showme.manifest import REGISTRY, load_seeds


@pytest.fixture(scope="module", autouse=True)
def _load_seeds_once() -> None:
    load_seeds()


def test_manifest_name_matches_served_function() -> None:
    entry = REGISTRY.get("ACCT")
    assert entry.name == acct_mod.ACCTFunction.name == "Multi-Account Aggregation"


def test_manifest_has_no_broker_snapshot_inputs() -> None:
    entry = REGISTRY.get("ACCT")
    names = {i.name for i in entry.inputs}
    assert "credential_id" not in names
    assert "ccy" not in names


def test_manifest_must_have_fields_are_returned_by_the_handler() -> None:
    entry = REGISTRY.get("ACCT")

    class _Empty:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            self.positions: list[Any] = []

        def import_legacy_crypto(self, *_a: Any, **_k: Any) -> int:
            return 0

    res = None
    import pytest as _pt  # local alias keeps the monkeypatch below explicit
    mp = _pt.MonkeyPatch()
    try:
        mp.setattr(acct_mod, "PortfolioState", _Empty)
        res = asyncio.run(acct_mod.ACCTFunction(FunctionDeps()).execute(positions=[
            {"symbol": "TLT", "asset_class": "ETF", "quantity": 1, "avg_cost": 90.0, "last": 91.0,
             "account": "main"},
        ]))
    finally:
        mp.undo()
    assert res is not None
    missing = [key for key in entry.output_contract.must_have if key not in res.data]
    assert not missing, f"ACCT must_have fields not returned by the handler: {missing}"


def _empty_book() -> type:
    class _Empty:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            self.positions: list[Any] = []

        def import_legacy_crypto(self, *_a: Any, **_k: Any) -> int:
            return 0

    return _Empty


@pytest.mark.parametrize(
    "params",
    [
        pytest.param({}, id="ready_no_positions"),
        pytest.param({"positions": "not-a-list"}, id="input_error"),
    ],
)
def test_empty_state_branches_return_every_must_have_field(
    params: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    # ACCT#3 residual: the empty-state returns (no positions, bad input) must
    # carry the same must_have contract as the supplied-positions branch.
    entry = REGISTRY.get("ACCT")
    monkeypatch.setattr(acct_mod, "PortfolioState", _empty_book())
    res = asyncio.run(acct_mod.ACCTFunction(FunctionDeps()).execute(**params))
    missing = [key for key in entry.output_contract.must_have if key not in res.data]
    assert not missing, f"ACCT must_have fields missing from empty-state return: {missing}"
