"""REBA model-path regressions (wb1-g21 follow-up, REBA#5).

Model mode has no current holdings, so it must not invent current weights,
quotes or capital. Without supplied capital it returns ``needs_input``; with
``max_notional`` it reports target allocations only and sizes no orders.

No network: the model path never reaches a provider.
"""

from __future__ import annotations

import asyncio

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio.reba import REBAFunction


def _run(coro):
    return asyncio.run(coro)


def test_model_path_without_capital_invents_no_weights_or_orders():
    res = _run(REBAFunction(FunctionDeps()).execute(targets={"SPY": 0.6, "QQQ": 0.4}))
    assert res.data["status"] == "needs_input"
    assert res.data["orders"] == []
    assert res.data["liquidations"] == []
    # No default capital and no assumed current holdings.
    assert "total_value" not in res.data
    assert "current_weights_pct" not in res.data
    assert res.data["reason"]
    assert res.data["next_actions"]
    assert res.metadata.get("live") is False


def test_model_path_with_capital_reports_targets_not_orders():
    res = _run(REBAFunction(FunctionDeps()).execute(
        targets={"SPY": 0.6, "QQQ": 0.4}, max_notional=250_000,
    ))
    assert res.data["total_value"] == pytest.approx(250_000.0)
    assert res.data["target_notional"]["SPY"] == pytest.approx(150_000.0)
    assert res.data["target_notional"]["QQQ"] == pytest.approx(100_000.0)
    # Current holdings are unknown in model mode, so no drift, no orders,
    # and no invented per-symbol price.
    assert res.data["orders"] == []
    assert res.data["rows"] == []
    assert "current_weights_pct" not in res.data
    assert res.data["status"] == "needs_input"
    assert res.metadata.get("live") is False
