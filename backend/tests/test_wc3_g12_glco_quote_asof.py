"""GLCO#2 — a board row's as_of is the price's exchange time, never the fetch time.

A futures quote carries its exchange timestamp (Friday's settlement read on a
Sunday must still say Friday). A quote price with no exchange time is not
served as current: the contract goes to ``missing`` with the reason. Network is
replaced by in-memory fakes.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from showme.engine.core.base_function import FunctionDeps

FRIDAY_SETTLE = datetime(2026, 11, 6, 21, 59, 58, tzinfo=timezone.utc)


class _Quotes:
    """yfinance-shaped provider; ``stamp`` maps a symbol to its quote timestamp."""

    def __init__(self, stamp: dict[str, Any]) -> None:
        self._stamp = stamp

    async def fetch(self, request: Any) -> Any:
        symbol = str(getattr(getattr(request, "instrument", None), "symbol", "") or "")
        return SimpleNamespace(
            last=100.0,
            close_prev=99.0,
            high_24h=101.0,
            low_24h=98.0,
            open_24h=99.0,
            volume_24h=1.0,
            source="yfinance",
            timestamp=self._stamp.get(symbol, FRIDAY_SETTLE),
        )


async def _no_history(symbol: str, timeout: float, *, range_: str = "3mo"):
    return []


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_row_as_of_is_the_exchange_time_not_the_fetch_time(monkeypatch) -> None:
    from showme.engine.functions.commodity import _funcs as mod

    monkeypatch.setattr(mod, "_yahoo_chart_ohlcv", _no_history)
    fn = mod.GLCOFunction(deps=FunctionDeps(yfinance=_Quotes({})))
    data = _run(fn.execute()).data
    assert data["status"] == "ok"
    for row in data["rows"]:
        assert row["as_of"] == FRIDAY_SETTLE.isoformat(), row
        assert row["as_of_source"] == "quote_exchange_time", row


def test_quote_without_exchange_time_is_missing_not_served_as_current(monkeypatch) -> None:
    from showme.engine.functions.commodity import _funcs as mod

    monkeypatch.setattr(mod, "_yahoo_chart_ohlcv", _no_history)
    fn = mod.GLCOFunction(deps=FunctionDeps(yfinance=_Quotes({"CL=F": None})))
    data = _run(fn.execute()).data
    assert data["status"] == "partial"
    assert "CL=F" not in {row["symbol"] for row in data["rows"]}
    entry = next(item for item in data["missing"] if item["symbol"] == "CL=F")
    assert "no exchange time" in entry["reason"], entry
    # Other contracts keep their exchange time.
    assert all(row["as_of"] == FRIDAY_SETTLE.isoformat() for row in data["rows"])


def test_shared_contract_snapshot_output_is_unchanged_for_other_callers(monkeypatch) -> None:
    """GLCO owns its exchange-time rule; the shared helper BOIL/BGAS/CPF use keeps its base output."""
    from showme.engine.functions.commodity import _funcs as mod

    monkeypatch.setattr(mod, "_yahoo_chart_ohlcv", _no_history)
    row, _history, errors = _run(mod._contract_snapshot(
        _Quotes({"CL=F": None}), "CL=F", days=30, timeout=2.0, include_history=False,
    ))
    assert row is not None
    assert "as_of_source" not in row, sorted(row)
    assert errors == []
