"""BMTX regression: the offline matrix never carries invented metric values.

Before the fix, the default non-live call returned hard-coded Sharpe, return,
drawdown and equity numbers under the requested tickers with status
"reference" and source "local_backtest_model". The matrix now keeps the
requested symbols and strategies as a grid of explicit nulls with a
needs_input status until live backtests are requested.
"""

from __future__ import annotations

import asyncio

from showme.engine.functions.portfolio.bmtx import BMTXFunction

METRIC_KEYS = ("sharpe", "total_return", "max_drawdown", "final_equity")


def _run(coro):
    return asyncio.run(coro)


def test_offline_default_carries_no_metric_values() -> None:
    res = _run(BMTXFunction().execute(symbols=["AAPL", "MSFT"], strategies=["sma_crossover"]))

    assert res.data["status"] == "needs_input"
    assert res.data["symbols"] == ["AAPL", "MSFT"]
    assert res.data["reason"]
    assert res.data["next_actions"]
    assert "local_backtest_model" not in res.sources
    assert res.data["summary"]["best_sharpe"] is None
    assert res.data["best_per_symbol"] == {}
    for cell in res.data["cells"] + res.data["surface"] + res.data["top_10_by_sharpe"]:
        for key in METRIC_KEYS:
            if key in cell:
                assert cell[key] is None, f"{key} carries a value without live data"


def test_offline_grid_keeps_requested_labels_without_numbers() -> None:
    res = _run(BMTXFunction().execute(symbols=["ZZQXNOTREAL"], strategies=["sma_crossover"]))

    labels = {cell["symbol"] for cell in res.data["cells"]}
    assert labels == {"ZZQXNOTREAL"}
    assert all(cell["sharpe"] is None for cell in res.data["cells"])
