"""HDS#5-RQ: no undated, unsourced AAPL holder numbers in the static reference table.

The 13F-style holder figures that used to sit in ``_common.REFERENCE_PROFILES``
had no reporting date and no provider behind them. Nothing may serve them as
holder rows, so the static profile must not carry a ``holders`` table at all.
Network is patched: no provider is called.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity import _common, hds

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


def test_reference_profiles_carry_no_static_holder_table():
    # RED before fix: AAPL held Vanguard/BlackRock/Berkshire constants under "holders".
    for symbol, profile in _common.REFERENCE_PROFILES.items():
        assert "holders" not in profile, (symbol, profile.get("holders"))


def test_aapl_with_all_providers_empty_returns_no_reference_holder_rows():
    class _EmptyYahoo:
        async def fetch(self, request):
            return {"major": None, "institutional": None, "mutualfund": None}

    class _EmptySec13F:
        async def query_holdings_by_security(self, **_kwargs):
            import pandas as pd

            return pd.DataFrame()

    class _Edgar:
        async def cik_for(self, ticker):
            return "0000320193"

        async def submissions(self, cik):
            return {"name": "Apple Inc."}

    fn = hds.HDSFunction(SimpleNamespace(yfinance=_EmptyYahoo(), sec_13f=_EmptySec13F(), sec_edgar=_Edgar()))
    res = asyncio.run(fn.execute(instrument=AAPL, live=True))
    assert res.data["rows"] == [], res.data
    assert res.data["status"] != "ok", res.data
    assert "reference_13f_public" not in str(res.data)
    assert "latest public 13F reference" not in str(res.data)
