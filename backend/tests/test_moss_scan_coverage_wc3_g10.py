"""WC3-G10 MOSS#1: a scan that overruns its budget reports its coverage honestly.

A cold cache can leave part of the universe unscanned when the screen budget
expires. Those symbols already ride along as state=unavailable rows, but the
payload still said status "ok" and gave no coverage figure, so a 2-of-4 board
read as a complete ranking. The payload must now state partial coverage.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.misc._bonus import MOSSFunction


def _run(coro):
    return asyncio.run(coro)


def _frame() -> pd.DataFrame:
    index = pd.date_range("2026-08-01", periods=60, freq="D")
    closes = [100.0 + float((i % 5) - 2) for i in range(60)]
    return pd.DataFrame({"close": closes}, index=index)


class _SlowForSome:
    """Answers the fast symbols at once and never answers the slow ones in time."""

    def __init__(self, slow: set[str]) -> None:
        self.slow = {s.upper() for s in slow}

    async def fetch(self, request: Any) -> Any:
        symbol = str(request.instrument.symbol).upper()
        if symbol in self.slow:
            await asyncio.sleep(30)
        return _frame()


def test_overrun_budget_reports_partial_coverage() -> None:
    """Pre-fix: status stayed 'ok' and data had no scan_coverage block."""
    symbols = ["AAA", "BBB", "CCC", "DDD"]
    provider = _SlowForSome(slow={"CCC", "DDD"})
    result = _run(
        MOSSFunction(deps=FunctionDeps(yfinance=provider)).execute(
            universe=symbols, live=True, limit=10, screen_timeout=1.0, quote_concurrency=12,
        )
    )
    data = result.data
    assert data["status"] == "partial", data["status"]
    coverage = data["scan_coverage"]
    assert coverage["universe_size"] == 4
    assert coverage["resolved"] == 2
    assert coverage["unavailable"] == 2
    assert coverage["complete"] is False
    assert coverage["budget_seconds"] == 1.0
    assert "2 of 4" in data["reason"]
    # Unscanned symbols stay visible as explicit unavailable rows, never dropped.
    assert len(data["rows"]) == 4
    pending_rows = [r for r in data["rows"] if r.get("state") == "unavailable"]
    assert {r["symbol"] for r in pending_rows} == {"CCC", "DDD"}
    assert all(r["vol_pct"] is None for r in pending_rows)
    assert data["live"] is True


def test_complete_scan_reports_full_coverage() -> None:
    symbols = ["AAA", "BBB"]
    result = _run(
        MOSSFunction(deps=FunctionDeps(yfinance=_SlowForSome(slow=set()))).execute(
            universe=symbols, live=True, limit=10, screen_timeout=5.0,
        )
    )
    data = result.data
    assert data["status"] == "ok"
    assert data["scan_coverage"]["complete"] is True
    assert data["scan_coverage"]["resolved"] == 2
    assert data["scan_coverage"]["unavailable"] == 0
    assert "reason" not in data
