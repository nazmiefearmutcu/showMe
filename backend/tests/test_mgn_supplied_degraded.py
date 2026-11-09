"""MGN#1 follow-up: a supplied book with an at-cost position is flagged degraded, like the saved book.

The mgn_seed semantic test promises ``metadata.degraded == true`` for an unquoted supplied
position; the supplied branch must set the flag from the same at-cost rule as the saved branch.
"""
from __future__ import annotations

import asyncio

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio.mgn import MGNFunction


def _run(coro):
    return asyncio.run(coro)


def test_supplied_unquoted_position_is_marked_at_cost_and_degraded():
    res = _run(MGNFunction(FunctionDeps()).execute(positions=[
        {"symbol": "MSFT", "asset_class": "EQUITY", "quantity": 5, "avg_cost": 300},
    ]))
    assert res.metadata["marked_at_cost"] == ["MSFT"]
    assert res.metadata["degraded"] is True


def test_supplied_fully_priced_book_is_not_degraded():
    res = _run(MGNFunction(FunctionDeps()).execute(positions=[
        {"symbol": "MSFT", "asset_class": "EQUITY", "quantity": 5, "avg_cost": 300, "last": 310},
    ]))
    assert res.metadata["marked_at_cost"] == []
    assert res.metadata["degraded"] is False
