"""EQS REFDATA refresh must respect the shared Yahoo token bucket (EQS#2 follow-up).

The refdata slice now runs on every live batch scan. It used to bypass the
shared rate limiter, so each scan could add up to ``refdata_budget`` public
Yahoo calls outside the bucket that protects the adapter. The slice must go
through the bucket, and its wall-clock wait stays capped by the slice timeout.
No network: the provider is a fake that records each request.
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
    yield
    eqs_mod._EQS_BATCH_CACHE.clear()
    eqs_mod._EQS_REFDATA_CACHE.clear()


class _RecordingYF:
    def __init__(self) -> None:
        self.refdata_extras: list[dict] = []

    async def fetch_refdata_batch(self, symbols, **_kwargs):
        return {str(s).upper(): {"marketCap": 1.0e9, "trailingPE": 10.0,
                                 "priceToBook": 1.0, "dividendYield": 0.0}
                for s in symbols}

    async def fetch(self, request):
        self.refdata_extras.append(dict(request.extra or {}))
        raw = {"sector": "Tech", "industry": "Software", "country": "US",
               "beta": 1.0, "priceToSalesTrailing12Months": 2.0}
        return SimpleNamespace(sector="Tech", industry="Software", market_cap=None,
                               country="US", extras={"raw": raw})


def test_refdata_refresh_does_not_bypass_the_shared_rate_limit() -> None:
    provider = _RecordingYF()
    fn = eqs_mod.EQSFunction(deps=FunctionDeps(yfinance=provider))
    asyncio.run(fn.execute(
        instrument=None,
        query="marketCap > 0",
        live_screen=True,
        universe=["AAPL", "MSFT", "NVDA"],
    ))
    assert provider.refdata_extras, "the refdata slice should still run on a live scan"
    assert all(not extra.get("bypass_rate_limit") for extra in provider.refdata_extras)
