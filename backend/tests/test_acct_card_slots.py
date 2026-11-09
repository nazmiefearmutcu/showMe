"""ACCT#3: every ACCT card slot reads a scalar the served output declares.

Card slots read top-level keys (dpf.py). ``accounts`` is a list, so a kpi slot
pointing at it renders a list; the card must read a count instead.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio import acct as acct_mod
from showme.manifest import REGISTRY, load_seeds


@pytest.fixture(scope="module", autouse=True)
def _load_seeds_once() -> None:
    load_seeds()


def _assert_slots_served(data: dict[str, Any]) -> None:
    entry = REGISTRY.get("ACCT")
    assert entry.card_schema is not None
    for slot in entry.card_schema.slots:
        assert slot.key in data, f"ACCT card slot {slot.key!r} is not a served top-level key"
        assert not isinstance(data[slot.key], (list, dict)), (
            f"ACCT card slot {slot.key!r} is a container, not a scalar"
        )


class _Empty:
    def __init__(self, *_a: Any, **_k: Any) -> None:
        self.positions: list[Any] = []

    def import_legacy_crypto(self, *_a: Any, **_k: Any) -> int:
        return 0


def test_acct_card_slots_for_supplied_positions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(acct_mod, "PortfolioState", _Empty)
    res = asyncio.run(acct_mod.ACCTFunction(FunctionDeps()).execute(positions=[
        {"symbol": "TLT", "asset_class": "ETF", "quantity": 2, "avg_cost": 90.0, "last": 91.0,
         "account": "main"},
        {"symbol": "GLD", "asset_class": "ETF", "quantity": 1, "avg_cost": 180.0,
         "account": "paper"},
    ]))
    _assert_slots_served(res.data)
    assert res.data["total_market_value"] == pytest.approx(182.0)
    assert res.data["accounts_count"] == 2
    assert res.data["positions"] == 2
    assert res.data["unpriced_positions"] == 1


def test_acct_card_slots_for_empty_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(acct_mod, "PortfolioState", _Empty)
    res = asyncio.run(acct_mod.ACCTFunction(FunctionDeps()).execute())
    _assert_slots_served(res.data)
    assert res.data["total_market_value"] is None
    assert res.data["accounts_count"] == 0
