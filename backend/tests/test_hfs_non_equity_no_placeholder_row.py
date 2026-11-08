"""HFS non-equity path returns an explicit not_applicable state with no rows.

The non-equity branch used to emit a placeholder row (filer='not_applicable',
shares=0, market_value=0) inside ``rows``. That row is not a holder and must
not appear as data. The contract now is: status='not_applicable', rows=[],
and a reason explaining why holder search does not apply.
"""

from __future__ import annotations

import asyncio

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.hfs import HFSFunction


def _run(coro):
    return asyncio.run(coro)


def test_non_equity_instrument_returns_not_applicable_without_placeholder_row():
    inst = Instrument(symbol="US10Y", asset_class=AssetClass.BOND)
    result = _run(HFSFunction(FunctionDeps()).execute(instrument=inst))
    data = result.data

    assert data["status"] == "not_applicable"
    assert data["rows"] == []
    assert data.get("reason")
    assert all(row.get("filer") != "not_applicable" for row in data["rows"])
