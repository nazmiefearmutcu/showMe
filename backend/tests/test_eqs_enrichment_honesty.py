"""EQS enrichment honesty (EQS#2, EQS#3).

beta, ps and industry are not in the batched Yahoo quote (verified: the v7
quote carries marketCap/trailingPE/priceToBook/dividendYield only). They come
from the per-symbol REFDATA cache, which used to refresh only when the query
text named one of those fields, so the same universe gave different columns
depending on the query that ran before. The refresh now runs on every live
batch scan, and the coverage of each enrichment field is reported.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pandas as pd
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


class _EnrichYF:
    """Batch quote (no beta/ps/industry, as Yahoo v7 really returns) plus REFDATA."""

    def __init__(self, batch: dict[str, dict], refdata: dict[str, dict]) -> None:
        self.batch = batch
        self.refdata = refdata

    async def fetch_refdata_batch(self, symbols, **_kwargs):
        return {str(s).upper(): self.batch[str(s).upper()]
                for s in symbols if str(s).upper() in self.batch}

    async def fetch(self, request):
        sym = request.instrument.symbol.upper()
        raw = self.refdata.get(sym)
        if raw is None:
            raise RuntimeError(f"no REFDATA for {sym}")
        return SimpleNamespace(
            sector=raw.get("sector"),
            industry=raw.get("industry"),
            market_cap=None,
            country=raw.get("country"),
            extras={"raw": raw},
        )


_BATCH = {
    "AAPL": {"marketCap": 3.0e12, "trailingPE": 28.0, "priceToBook": 41.0, "dividendYield": 0.5},
    "MSFT": {"marketCap": 3.2e12, "trailingPE": 34.0, "priceToBook": 11.8, "dividendYield": 0.8},
}
_REFDATA = {
    "AAPL": {"sector": "Information Technology", "industry": "Consumer Electronics",
             "country": "US", "beta": 1.1, "priceToSalesTrailing12Months": 7.2},
    "MSFT": {"sector": "Information Technology", "industry": "Software",
             "country": "US", "beta": 0.9, "priceToSalesTrailing12Months": 12.1},
}


def _screen(provider, query: str):
    fn = eqs_mod.EQSFunction(deps=FunctionDeps(yfinance=provider))
    return asyncio.run(fn.execute(
        instrument=None,
        query=query,
        live_screen=True,
        universe=["AAPL", "MSFT"],
    ))


def test_eqs_beta_and_ps_do_not_depend_on_the_query_text() -> None:
    result = _screen(_EnrichYF(_BATCH, _REFDATA), "marketCap > 0")
    df = result.data.set_index("symbol")
    assert df.loc["AAPL", "beta"] == pytest.approx(1.1)
    assert df.loc["MSFT", "beta"] == pytest.approx(0.9)
    assert df.loc["AAPL", "ps"] == pytest.approx(7.2)


def test_eqs_industry_fills_for_a_query_with_no_enrichment_field() -> None:
    result = _screen(_EnrichYF(_BATCH, _REFDATA), "dividend_yield > 0")
    df = result.data.set_index("symbol")
    assert df.loc["MSFT", "industry"] == "Software"
    assert df.loc["AAPL", "industry"] == "Consumer Electronics"


def test_eqs_reports_enrichment_coverage_when_a_symbol_has_no_refdata() -> None:
    result = _screen(_EnrichYF(_BATCH, {"AAPL": _REFDATA["AAPL"]}), "marketCap > 0")
    coverage = result.metadata["enrichment_coverage"]
    assert coverage["beta"] == {"populated": 1, "of": 2}
    assert coverage["industry"] == {"populated": 1, "of": 2}
    assert any("beta" in w for w in result.warnings)

