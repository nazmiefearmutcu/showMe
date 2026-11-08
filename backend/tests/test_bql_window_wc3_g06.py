"""BQL#2-RQ: a with(start, end) window returns rows inside that window (wc3-g06).

The finding: live mode sent the default period and yfinance answered with the
last month, labelled as the requested window. This test uses the real
YFinanceAdapter with only its HTTP transport replaced by a fake that honours
period1/period2 the way Yahoo does (and ignores range). Nothing touches the network.
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.data_sources.equity.yfinance_adapter import YFinanceAdapter
from showme.engine.functions.api import bql as bql_mod

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)

# Daily bars: January 2024 (inside the requested window) and a November 2026 bar
# (the last month, which the bug returned instead).
_BAR_DATES = [
    pd.Timestamp("2024-01-02", tz="UTC"),
    pd.Timestamp("2024-01-15", tz="UTC"),
    pd.Timestamp("2024-01-30", tz="UTC"),
    pd.Timestamp("2026-11-05", tz="UTC"),
]


class _WindowHonouringChart:
    """Yahoo-like chart fake: returns only bars inside period1..period2, or the range."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def get(self, url: str, params: dict[str, Any] | None = None, **_: Any) -> httpx.Response:
        p = dict(params or {})
        self.calls.append({"url": url, "params": p})
        if "period1" in p and "period2" in p:
            lo = int(p["period1"])
            hi = int(p["period2"])
            stamps = [int(d.timestamp()) for d in _BAR_DATES if lo <= int(d.timestamp()) <= hi]
        else:
            # A range request would answer with the last month only (here: the 2026 bar).
            stamps = [int(_BAR_DATES[-1].timestamp())]
        n = len(stamps)
        body = {
            "chart": {
                "result": [
                    {
                        "timestamp": stamps,
                        "indicators": {
                            "quote": [
                                {
                                    "open": [10.0] * n,
                                    "high": [11.0] * n,
                                    "low": [9.0] * n,
                                    "close": [10.5] * n,
                                    "volume": [1_000] * n,
                                }
                            ]
                        },
                    }
                ]
            }
        }
        return httpx.Response(200, json=body, request=httpx.Request("GET", f"https://yahoo.test{url}"))


def _adapter(monkeypatch: pytest.MonkeyPatch) -> tuple[YFinanceAdapter, _WindowHonouringChart]:
    adapter = YFinanceAdapter()
    chart = _WindowHonouringChart()

    async def _client_():
        return chart

    monkeypatch.setattr(adapter, "_chart_client_", _client_)
    return adapter, chart


def test_start_end_window_returns_rows_only_inside_the_window(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, chart = _adapter(monkeypatch)
    fn = bql_mod.BQLFunction(FunctionDeps(yfinance=adapter))
    res = asyncio.run(fn.execute(
        instrument=AAPL,
        query="get(close) for(['AAPL']) with(start='2024-01-01', end='2024-01-31') by(date)",
        live=True,
    ))
    sent = chart.calls[0]["params"]
    assert "range" not in sent and "period" not in sent
    rows = res.data.get("rows") or []
    assert rows, res.data
    dates = [pd.Timestamp(r["date"]) for r in rows]
    assert all(pd.Timestamp("2024-01-01", tz="UTC") <= d <= pd.Timestamp("2024-01-31 23:59:59", tz="UTC") for d in dates), dates
    assert not any(d.year == 2026 for d in dates), dates


def test_window_rows_are_not_substituted_by_the_last_month(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression for BQL#2: the 2026 bar that a range request returns must not appear."""
    adapter, _chart = _adapter(monkeypatch)
    fn = bql_mod.BQLFunction(FunctionDeps(yfinance=adapter))
    res = asyncio.run(fn.execute(
        instrument=AAPL,
        query="get(close) for(['AAPL']) with(start='2024-01-01', end='2024-01-31') by(date)",
        live=True,
    ))
    assert res.data.get("status") in (None, "ok", "partial"), res.data
    assert len(res.data.get("rows") or []) == 3, res.data.get("rows")
