"""GLCO#1-RQ — a board that misses contracts must not be labelled ``ok``.

Quotes for some futures fail or miss the screen cutoff. The board must report
``status: partial`` with a ``missing`` list naming each contract and why it is
absent, and must never substitute another contract's price. Network is patched.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from showme.engine.core.base_function import FunctionDeps

FAILING = {"SB=F", "KC=F", "CT=F"}


class _PartialQuotes:
    """yfinance-shaped provider: three softs fail, the rest quote."""

    def __init__(self, failing: set[str]) -> None:
        self.failing = failing

    async def fetch(self, request: Any) -> Any:
        symbol = str(getattr(getattr(request, "instrument", None), "symbol", "") or "")
        if symbol in self.failing:
            raise RuntimeError("simulated quote timeout")
        return SimpleNamespace(
            last=100.0,
            close_prev=99.0,
            high_24h=101.0,
            low_24h=98.0,
            open_24h=99.0,
            volume_24h=1.0,
            source="yfinance",
            timestamp=datetime.now(timezone.utc),
        )


async def _no_history(symbol: str, timeout: float, *, range_: str = "3mo"):
    return []


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_glco_missing_contracts_make_board_partial_and_are_named(monkeypatch) -> None:
    from showme.engine.functions.commodity import _funcs as mod

    monkeypatch.setattr(mod, "_yahoo_chart_ohlcv", _no_history)
    fn = mod.GLCOFunction(deps=FunctionDeps(yfinance=_PartialQuotes(FAILING)))
    result = _run(fn.execute())
    data = result.data
    assert data["status"] == "partial", data["status"]
    assert len(data["rows"]) == 14 - len(FAILING)
    served = {row["symbol"] for row in data["rows"]}
    assert served.isdisjoint(FAILING)
    missing = {entry["symbol"] for entry in data["missing"]}
    assert missing == FAILING
    for entry in data["missing"]:
        assert entry["reason"], entry
        assert "TimeoutError" in entry["reason"] or "simulated" in entry["reason"], entry
    assert data["served_count"] == 11 and data["requested_count"] == 14
    assert "3 of 14" in data["reason"]
    assert result.warnings


def test_glco_complete_board_stays_ok_with_no_missing(monkeypatch) -> None:
    from showme.engine.functions.commodity import _funcs as mod

    monkeypatch.setattr(mod, "_yahoo_chart_ohlcv", _no_history)
    fn = mod.GLCOFunction(deps=FunctionDeps(yfinance=_PartialQuotes(set())))
    data = _run(fn.execute()).data
    assert data["status"] == "ok"
    assert data["missing"] == []
    assert len(data["rows"]) == 14


class _EmptyMessageTimeouts(_PartialQuotes):
    async def fetch(self, request: Any) -> Any:
        symbol = str(getattr(getattr(request, "instrument", None), "symbol", "") or "")
        if symbol in self.failing:
            raise asyncio.TimeoutError()  # empty message, as a real timeout has
        return await super().fetch(request)


def test_glco_empty_message_timeout_names_the_exception_type(monkeypatch) -> None:
    """f'{exc or type(exc).__name__}' never fell back (an exception is always
    truthy), so a bare timeout left an empty reason; it must name the type."""
    from showme.engine.functions.commodity import _funcs as mod

    monkeypatch.setattr(mod, "_yahoo_chart_ohlcv", _no_history)
    fn = mod.GLCOFunction(deps=FunctionDeps(yfinance=_EmptyMessageTimeouts(FAILING)))
    data = _run(fn.execute()).data
    for entry in data["missing"]:
        assert "TimeoutError" in entry["reason"], entry
