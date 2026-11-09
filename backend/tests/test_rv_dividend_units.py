"""RV#1 — dividend yield is delivered as a decimal fraction (p1a-g05).

yfinance ``info['dividendYield']`` is in percent units (AAPL 0.32 means 0.32%).
RV must hand the pane a fraction (0.0032) so the pane never has to guess units.
The network is replaced by an in-memory yfinance fake.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.rv import RVFunction


class _FakeYF:
    def __init__(self, raw_by_symbol):
        self._raw = raw_by_symbol

    async def fetch(self, request):
        raw = self._raw[request.instrument.symbol]
        return SimpleNamespace(market_cap=None, extras={"raw": raw})


class _Deps:
    finnhub = None

    def __init__(self, raw_by_symbol):
        self.yfinance = _FakeYF(raw_by_symbol)


def _run_rv(raw_by_symbol, symbol="AAPL", peers=("MSFT",)):
    fn = RVFunction(_Deps(raw_by_symbol))
    inst = Instrument(symbol=symbol, asset_class=AssetClass.EQUITY)
    return asyncio.run(fn.execute(instrument=inst, peers=list(peers)))


def _row(res, symbol):
    return next(r for r in res.data["rows"] if r["symbol"] == symbol)


def test_rv1_dividend_yield_is_returned_as_fraction():
    res = _run_rv({
        "AAPL": {"dividendYield": 0.32, "dividendRate": 1.08, "currentPrice": 342.37, "trailingPE": 30.0},
        "MSFT": {"dividendYield": 0.74, "dividendRate": 3.00, "currentPrice": 405.0, "trailingPE": 25.0},
    })
    # yfinance 0.32 is percent -> 0.0032 as a fraction (0.32%), settled by dividendRate/price.
    assert _row(res, "AAPL")["div_yield"] == pytest.approx(0.0032)
    assert _row(res, "MSFT")["div_yield"] == pytest.approx(0.0074)


def test_rv1_missing_dividend_yield_stays_none():
    res = _run_rv({
        "AAPL": {"trailingPE": 30.0},
        "MSFT": {"dividendYield": None, "trailingPE": 25.0},
    })
    assert _row(res, "AAPL")["div_yield"] is None
    assert _row(res, "MSFT")["div_yield"] is None


def test_rv1_decimal_form_is_recognised_by_the_rate_and_price_cross_check():
    # A yfinance release that ships a decimal yield (0.0032 = 0.32%) must not be
    # divided by 100 again. dividendRate / price = 1.08 / 342.37 = 0.315%.
    res = _run_rv({
        "AAPL": {"dividendYield": 0.0032, "dividendRate": 1.08, "currentPrice": 342.37},
        "MSFT": {"dividendYield": 0.0074, "dividendRate": 3.00, "currentPrice": 405.0},
    })
    assert _row(res, "AAPL")["div_yield"] == pytest.approx(0.0032)
    assert _row(res, "MSFT")["div_yield"] == pytest.approx(0.0074, rel=1e-3)


def test_rv1_percent_form_is_recognised_by_the_rate_and_price_cross_check():
    res = _run_rv({
        "AAPL": {"dividendYield": 0.32, "dividendRate": 1.08, "regularMarketPrice": 342.37},
        "MSFT": {"dividendYield": 0.74, "dividendRate": 3.00, "previousClose": 405.0},
    })
    assert _row(res, "AAPL")["div_yield"] == pytest.approx(0.0032, rel=1e-3)
    assert _row(res, "MSFT")["div_yield"] == pytest.approx(0.0074, rel=1e-3)


def test_rv1_without_cross_check_the_unit_is_unresolved_not_guessed():
    # No dividendRate or price: 0.32 could be 0.32% or 32%, and 0.0074 could be
    # either too. RV must not divide by 100 on a magnitude guess; it returns an
    # explicit unit_unresolved state and keeps the raw reading.
    res = _run_rv({
        "AAPL": {"dividendYield": 0.32},
        "MSFT": {"dividendYield": 0.0074},
    })
    for sym in ("AAPL", "MSFT"):
        row = _row(res, sym)
        assert row["div_yield"] is None, row
        assert row["div_yield_status"] == "unit_unresolved", row


def test_rv1_a_large_unverifiable_reading_is_not_guessed_as_percent():
    # 0.15 with no cross-check is exactly the case the old magnitude rule got wrong.
    res = _run_rv({"AAPL": {"dividendYield": 0.15}, "MSFT": {"dividendYield": 0.15}})
    assert _row(res, "AAPL")["div_yield"] is None
    assert _row(res, "AAPL")["div_yield_status"] == "unit_unresolved"


def test_rv1_zero_yield_is_unit_free_and_resolved():
    res = _run_rv({"AAPL": {"dividendYield": 0}, "MSFT": {"dividendYield": 0.74}})
    assert _row(res, "AAPL")["div_yield"] == pytest.approx(0.0)
    assert _row(res, "AAPL")["div_yield_status"] == "ok"


def test_rv1_reading_inconsistent_with_rate_and_price_is_unresolved():
    # rate/price = 0.01% (0.0001). Percent reading 0.005 is 50x off, decimal 0.5 is 5000x off.
    res = _run_rv({
        "AAPL": {"dividendYield": 0.5, "dividendRate": 0.01, "currentPrice": 100.0},
        "MSFT": {"dividendYield": 0.74, "dividendRate": 3.00, "currentPrice": 405.0},
    })
    assert _row(res, "AAPL")["div_yield"] is None
    assert _row(res, "AAPL")["div_yield_status"] == "unit_unresolved"
    assert _row(res, "MSFT")["div_yield_status"] == "ok"


def test_rv1_resolved_rows_report_status_ok():
    res = _run_rv({
        "AAPL": {"dividendYield": 0.32, "dividendRate": 1.08, "currentPrice": 342.37},
        "MSFT": {"trailingPE": 25.0},
    })
    assert _row(res, "AAPL")["div_yield_status"] == "ok"
    assert _row(res, "MSFT")["div_yield"] is None
    assert _row(res, "MSFT")["div_yield_status"] == "missing"


def test_rv1_negative_dividend_yield_is_missing():
    res = _run_rv({"AAPL": {"dividendYield": -0.5}, "MSFT": {"dividendYield": 0.74}})
    assert _row(res, "AAPL")["div_yield"] is None
