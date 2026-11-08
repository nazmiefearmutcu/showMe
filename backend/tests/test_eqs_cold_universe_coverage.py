"""A cold, large EQS universe must disclose its REFDATA gap (EQS#2 / EQS#3 follow-up).

The per-scan REFDATA slice can finish only a handful of calls inside its wall
clock (shared Yahoo bucket), so on a cold 300-symbol universe beta, P/S and
industry stay empty for most rows after one scan. The screener must not invent
those values: it must leave them null, report the gap in enrichment_coverage,
and say so in warnings. No network: the REFDATA provider never answers in time.
"""

from __future__ import annotations

import asyncio

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.equity import eqs as eqs_mod

_N = 300
_SYMBOLS = [f"C{i:03d}" for i in range(_N)]


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


class _BatchOnlyColdYF:
    async def fetch_refdata_batch(self, symbols, **_kwargs):
        return {str(s).upper(): {"marketCap": 1.0e9, "trailingPE": 12.0,
                                 "priceToBook": 1.5, "dividendYield": 1.0}
                for s in symbols}

    async def fetch(self, request):
        await asyncio.sleep(60)  # never answers inside the slice: cancelled
        raise RuntimeError("unreachable")


def _cold_scan():
    fn = eqs_mod.EQSFunction(deps=FunctionDeps(yfinance=_BatchOnlyColdYF()))
    return asyncio.run(fn.execute(
        instrument=None,
        query="marketCap > 0",
        live_screen=True,
        universe=list(_SYMBOLS),
        refdata_screen_timeout=1.0,
    ))


def test_cold_universe_industry_gap_is_reported_not_invented() -> None:
    result = _cold_scan()
    assert result.metadata["matched"] == _N
    coverage = result.metadata["enrichment_coverage"]
    assert coverage["industry"] == {"populated": 0, "of": _N}
    assert coverage["beta"] == {"populated": 0, "of": _N}
    assert any(w.startswith("industry is empty for") for w in result.warnings)
    for row in result.data.to_dict(orient="records"):
        assert row.get("industry") is None
        assert row.get("beta") is None
