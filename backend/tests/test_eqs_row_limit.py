"""EQS row limit is honoured (EQS#1).

The pane sends ``limit`` (25/50/100/250/500) and renders ``rows · N/limit``.
The handler used to ignore it, so a 58-row match came back against limit 50.
The returned rows are capped at ``limit``; ``matched`` keeps the full count.
No network: the provider is a fake batch quote.
"""

from __future__ import annotations

import asyncio

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.equity import eqs as eqs_mod


@pytest.fixture(autouse=True)
def _isolate_module_state(monkeypatch):
    eqs_mod._EQS_BATCH_CACHE.clear()
    eqs_mod._EQS_REFDATA_CACHE.clear()
    eqs_mod._SECURITY_MASTER_INDEX = None
    monkeypatch.setattr(eqs_mod, "_EQS_REFDATA_CURSOR", 0)
    yield
    eqs_mod._EQS_BATCH_CACHE.clear()
    eqs_mod._EQS_REFDATA_CACHE.clear()


class _BatchOnlyYF:
    def __init__(self, symbols: list[str]) -> None:
        self._symbols = symbols

    async def fetch_refdata_batch(self, symbols, **_kwargs):
        return {
            str(s).upper(): {"marketCap": 1.0e9 + i, "trailingPE": 10.0,
                             "priceToBook": 1.0, "dividendYield": 1.0}
            for i, s in enumerate(symbols)
            if str(s).upper() in self._symbols
        }

    async def fetch(self, request):
        raise RuntimeError("no per-symbol REFDATA in this test")


_SYMBOLS = ["AAA", "BBB", "CCC", "DDD", "EEE"]


def _screen(limit, query: str = "marketCap > 0"):
    fn = eqs_mod.EQSFunction(deps=FunctionDeps(yfinance=_BatchOnlyYF(_SYMBOLS)))
    params = {"query": query, "live_screen": True, "universe": list(_SYMBOLS)}
    if limit is not None:
        params["limit"] = limit
    return asyncio.run(fn.execute(instrument=None, **params))


def test_limit_caps_returned_rows_and_matched_keeps_full_count() -> None:
    result = _screen(limit=2)
    assert len(result.data) == 2
    assert result.metadata["matched"] == 5
    assert result.metadata["returned"] == 2
    assert result.metadata["limit"] == 2


def test_limit_accepts_numeric_string_from_the_pane() -> None:
    result = _screen(limit="3")
    assert len(result.data) == 3
    assert result.metadata["matched"] == 5


def test_limit_larger_than_matches_returns_all_matches() -> None:
    result = _screen(limit=50)
    assert len(result.data) == 5
    assert result.metadata["returned"] == 5


def test_missing_limit_does_not_cap_rows() -> None:
    result = _screen(limit=None)
    assert len(result.data) == 5
