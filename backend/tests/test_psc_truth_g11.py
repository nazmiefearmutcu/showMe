"""PSC truth checks (p2a-g11): honest blank-entry cause and leverage limits."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio import psc

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


class _YF:
    def __init__(self, last):
        self.last = last

    async def fetch(self, request):
        return SimpleNamespace(last=self.last)


def _fn(last=None):
    return psc.PSCFunction(SimpleNamespace(yfinance=_YF(last) if last is not None else None))


def _run(fn, **params):
    return asyncio.run(fn.execute(**params))


def test_blank_entry_without_symbol_names_the_missing_entry():
    # Router shape for a call with no symbol: default symbol injected, sentinel False.
    res = _run(_fn(last=75689.0), target=115, stop=110, account=10_000, symbol="BTCUSDT",
               __explicit_symbol=False)
    assert res.data["status"] == "input_error"
    assert "no symbol selected" in res.data["reason"]
    assert "target" not in res.data["reason"]


def test_live_price_entry_names_its_source_when_target_is_wrong():
    # An explicit symbol whose live price becomes the entry: the target error must
    # say the entry came from the live quote, not blame the user's target alone.
    res = _run(_fn(last=75689.0), symbol="BTCUSDT", __explicit_symbol=True,
               target=115, stop=70_000, account=10_000)
    assert res.data["status"] == "input_error"
    reason = res.data["reason"]
    assert "a LONG target must be above the entry" in reason
    assert "live last price" in reason and "BTCUSDT" in reason


def test_notional_above_equity_is_flagged_as_margin():
    res = _run(_fn(), instrument=AAPL, account=10_000, entry=100, stop=99.9)
    assert res.data["leverage_implied"] == pytest.approx(10.0)
    assert any("exceeds account equity" in w for w in res.warnings)


def test_max_leverage_caps_shares_and_says_so():
    res = _run(_fn(), instrument=AAPL, account=10_000, entry=100, stop=99.9, max_leverage=2)
    assert res.data["shares"] == pytest.approx(200)
    assert res.data["uncapped_shares"] == pytest.approx(1000)
    assert res.data["cap_binding"] == "max_leverage"
    assert res.data["leverage_implied"] == pytest.approx(2.0)
    assert any("capped by max_leverage" in w for w in res.warnings)


def test_invalid_max_leverage_is_an_input_error():
    res = _run(_fn(), instrument=AAPL, account=10_000, entry=100, stop=99.9, max_leverage=0)
    assert res.data["status"] == "input_error"
    assert "max_leverage" in res.data["reason"]
