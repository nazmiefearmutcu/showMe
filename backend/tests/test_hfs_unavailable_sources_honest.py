"""HFS — an unavailable or not-applicable envelope must not list sec_13f as a source.

``sources`` names the providers that contributed rows. When the local 13F store
is unwired, fails, or holds nothing for the issuer, it contributed no rows, so
the envelope must not present ``sec_13f`` as a data source.
"""

from __future__ import annotations

import asyncio

import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.hfs import HFSFunction


def _run(coro):
    return asyncio.run(coro)


class _EmptySec13F:
    async def query_holdings_by_security(self, **_kwargs):
        return pd.DataFrame()


class _BoomSec13F:
    async def query_holdings_by_security(self, **_kwargs):
        raise RuntimeError("duckdb locked")


def test_unwired_store_lists_no_contributing_source():
    result = _run(HFSFunction(FunctionDeps()).execute(issuer="AAPL"))
    assert result.data["status"] == "provider_unavailable"
    assert result.sources == []


def test_store_error_lists_no_contributing_source():
    deps = FunctionDeps()
    deps.sec_13f = _BoomSec13F()
    result = _run(HFSFunction(deps).execute(issuer="AAPL"))
    assert result.data["status"] == "provider_unavailable"
    assert result.sources == []


def test_empty_store_lists_no_contributing_source():
    deps = FunctionDeps()
    deps.sec_13f = _EmptySec13F()
    result = _run(HFSFunction(deps).execute(issuer="ZZZZ"))
    assert result.data["status"] == "provider_unavailable"
    assert result.sources == []


def test_not_applicable_lists_no_contributing_source():
    inst = Instrument(symbol="US10Y", asset_class=AssetClass.BOND)
    result = _run(HFSFunction(FunctionDeps()).execute(instrument=inst))
    assert result.data["status"] == "not_applicable"
    assert result.sources == []
