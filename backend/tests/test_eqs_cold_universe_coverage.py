"""A cold, large EQS universe reports its REFDATA gap and closes it across scans (EQS#2 / EQS#3).

The per-scan REFDATA slice finishes only about 11 calls inside its default wall
clock (shared Yahoo bucket), so on a cold 300-symbol universe industry (and
beta / P/S when the batch record lacks them) is empty for most rows after one
scan. Two contracts are pinned here:

1. A silent REFDATA provider never fills a value: the gap stays null and is
   reported in enrichment_coverage and warnings (no invented values).
2. A responsive REFDATA provider does not leave the gap locked in: each scan
   fills at most the slice budget, the rotation covers every symbol, and
   coverage reaches the full universe after ceil(N / budget) scans.

No network: both providers are in-test fakes.
"""

from __future__ import annotations

import asyncio
import math
from types import SimpleNamespace

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.equity import eqs as eqs_mod

_N = 300
_SYMBOLS = [f"C{i:03d}" for i in range(_N)]
_BUDGET = 24  # the default refdata_budget


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
    """Batch record without beta, P/S or industry; REFDATA never answers in time."""

    async def fetch_refdata_batch(self, symbols, **_kwargs):
        return {str(s).upper(): {"marketCap": 1.0e9, "trailingPE": 12.0,
                                 "priceToBook": 1.5, "dividendYield": 1.0}
                for s in symbols}

    async def fetch(self, request):
        await asyncio.sleep(60)  # never answers inside the slice: cancelled
        raise RuntimeError("unreachable")


class _BatchOnlyInstantYF:
    """Same batch record; REFDATA answers at once with beta, P/S and industry."""

    async def fetch_refdata_batch(self, symbols, **_kwargs):
        return {str(s).upper(): {"marketCap": 1.0e9, "trailingPE": 12.0,
                                 "priceToBook": 1.5, "dividendYield": 1.0}
                for s in symbols}

    async def fetch(self, request):
        raw = {"sector": "Tech", "industry": "Software", "country": "US",
               "beta": 1.0, "priceToSalesTrailing12Months": 2.0}
        return SimpleNamespace(sector="Tech", industry="Software", market_cap=None,
                               country="US", extras={"raw": raw})


def _scan(provider, universe=None):
    fn = eqs_mod.EQSFunction(deps=FunctionDeps(yfinance=provider))
    return asyncio.run(fn.execute(
        instrument=None,
        query="marketCap > 0",
        live_screen=True,
        universe=list(universe if universe is not None else _SYMBOLS),
        refdata_screen_timeout=1.0,
    ))


def test_silent_refdata_leaves_the_gap_null_and_reported() -> None:
    """Disclosure contract: with no REFDATA answer nothing is filled from it."""
    result = _scan(_BatchOnlyColdYF())
    assert result.metadata["matched"] == _N
    coverage = result.metadata["enrichment_coverage"]
    assert coverage["industry"]["populated"] == 0
    assert coverage["industry"]["of"] == _N
    assert coverage["beta"]["populated"] == 0
    assert any(w.startswith("industry is empty for") for w in result.warnings)
    for row in result.data.to_dict(orient="records"):
        assert row.get("industry") is None
        assert row.get("beta") is None


def test_cold_universe_gap_closes_over_scans_and_is_reported_until_then() -> None:
    """The gap is not locked in: each scan fills one budget of rows, and coverage
    reaches every row after ceil(N / budget) scans."""
    provider = _BatchOnlyInstantYF()
    scans_needed = math.ceil(_N / _BUDGET)
    first = _scan(provider)
    first_cov = first.metadata["enrichment_coverage"]["industry"]
    assert first_cov == {"populated": _BUDGET, "of": _N}
    assert any(w.startswith("industry is empty for") for w in first.warnings)

    result = first
    for _ in range(scans_needed - 1):
        result = _scan(provider)
    for field in ("industry", "beta", "ps"):
        assert result.metadata["enrichment_coverage"][field] == {"populated": _N, "of": _N}
    assert not any("is empty for" in w for w in result.warnings)
