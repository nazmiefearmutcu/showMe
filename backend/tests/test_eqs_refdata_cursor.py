"""EQS REFDATA slice must not skip symbols whose call was cancelled (EQS#2 follow-up).

The slice window is larger than the calls that can finish inside the slice
wall clock. A call that is cancelled at the slice timeout was never attempted,
so it must be first in line on the next scan, not skipped until an index wrap.
No network: the provider is a fake; hanging calls stand in for slow Yahoo calls.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.equity import eqs as eqs_mod


@pytest.fixture(autouse=True)
def _isolate_module_state(monkeypatch):
    eqs_mod._EQS_BATCH_CACHE.clear()
    eqs_mod._EQS_REFDATA_CACHE.clear()
    eqs_mod._SECURITY_MASTER_INDEX = None
    monkeypatch.setattr(eqs_mod, "_EQS_REFDATA_CURSOR", 0)
    monkeypatch.setattr(eqs_mod, "_EQS_REFDATA_ATTEMPTED", {}, raising=False)
    yield
    eqs_mod._EQS_BATCH_CACHE.clear()
    eqs_mod._EQS_REFDATA_CACHE.clear()


_UNIVERSE = [f"S{i:02d}" for i in range(30)]
_SLOW = {"S03"}


class _SlowSomeYF:
    def __init__(self) -> None:
        self.refdata_calls: list[list[str]] = []
        self._scan: list[str] = []
        self.hang_once = False
        self._hung: set[str] = set()

    async def fetch_refdata_batch(self, symbols, **_kwargs):
        return {str(s).upper(): {"marketCap": 1.0e9, "trailingPE": 10.0,
                                 "priceToBook": 1.0, "dividendYield": 0.0}
                for s in symbols}

    async def fetch(self, request):
        symbol = request.instrument.symbol.upper()
        self._scan.append(symbol)
        if symbol in _SLOW and (not self.hang_once or symbol not in self._hung):
            self._hung.add(symbol)
            await asyncio.sleep(60)  # cancelled by the slice timeout
        raw = {"sector": "Tech", "industry": "Software", "country": "US",
               "beta": 1.0, "priceToSalesTrailing12Months": 2.0}
        return SimpleNamespace(sector="Tech", industry="Software", market_cap=None,
                               country="US", extras={"raw": raw})

    def start_scan(self) -> None:
        self._scan = []

    def end_scan(self) -> None:
        self.refdata_calls.append(list(self._scan))


def _scan(provider: _SlowSomeYF):
    provider.start_scan()
    fn = eqs_mod.EQSFunction(deps=FunctionDeps(yfinance=provider))
    result = asyncio.run(fn.execute(
        instrument=None,
        query="marketCap > 0",
        live_screen=True,
        universe=list(_UNIVERSE),
        refdata_screen_timeout=1.0,
    ))
    provider.end_scan()
    return result


def test_cancelled_refdata_call_is_retried_on_the_next_scan() -> None:
    provider = _SlowSomeYF()
    _scan(provider)
    assert "S03" in provider.refdata_calls[0], "the slow symbol is in the first window"
    assert "S03" not in getattr(eqs_mod, "_EQS_REFDATA_ATTEMPTED", {}), (
        "a cancelled call is not an attempt"
    )
    _scan(provider)
    assert "S03" in provider.refdata_calls[1], (
        "the cancelled symbol must be retried first on the next scan, not skipped"
    )


def test_symbols_that_finished_are_not_refetched_while_others_remain() -> None:
    provider = _SlowSomeYF()
    _scan(provider)
    _scan(provider)
    finished = set(_UNIVERSE[:24]) - _SLOW
    second_scan_calls = set(provider.refdata_calls[1])
    assert not (finished & second_scan_calls), "cached symbols must not be fetched again"


def test_industry_reaches_every_row_once_the_slow_call_recovers() -> None:
    """Regression guard on a 30-symbol universe: a symbol that is slow once must
    not leave industry empty forever. This is NOT a scale test and it passes on
    the base snapshot too; the cold 300-symbol ceiling (industry, beta and P/S
    empty for most rows) is disclosed by test_eqs_cold_universe_coverage.py."""
    provider = _SlowSomeYF()
    provider.hang_once = True
    _scan(provider)
    _scan(provider)
    result = _scan(provider)
    coverage = result.metadata["enrichment_coverage"]
    assert coverage["industry"] == {"populated": len(_UNIVERSE), "of": len(_UNIVERSE)}
