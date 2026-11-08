"""P2A-G09 regression tests: SECT missing-price and model-period honesty, GC3D honesty."""

from __future__ import annotations

import asyncio


def _run(coro):
    return asyncio.run(coro)


class _GoodQuote:
    last = 101.0
    close_prev = 100.0
    high_24h = 102.0
    low_24h = 99.0


class _NoLastQuote:
    last = None
    close_prev = 100.0
    high_24h = None
    low_24h = None


class _MixedYf:
    """XLK has a real price; every other sector has a previous close but no last."""

    async def fetch(self, request, *a, **kw):
        return _GoodQuote() if request.instrument.symbol == "XLK" else _NoLastQuote()


def test_sect_missing_last_price_is_not_a_minus_100_live_move() -> None:
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.screen.sect import SECTFunction

    out = _run(SECTFunction(FunctionDeps(yfinance=_MixedYf())).execute(period="1D", live=True))
    assert out.data["status"] == "ok"
    rows = {r["etf"]: r for r in out.data["rows"]}
    assert rows["XLK"]["quote_type"] == "live"
    assert abs(rows["XLK"]["change_pct"] - 1.0) < 1e-6
    lf = rows["XLF"]
    assert lf["last"] is None
    assert lf["change_pct"] is None, lf
    assert lf["quote_type"] == "unavailable", lf
    assert lf["change_pct_period"] is None, lf


def test_sect_model_mtd_has_no_fabricated_period_change() -> None:
    """Model mode only models 1D. MTD/QTD/YTD must not be the 1D value times a constant."""
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.screen.sect import SECTFunction

    out = _run(SECTFunction(FunctionDeps()).execute(period="YTD"))
    assert out.data["status"] == "model"
    assert all(r["change_pct"] is None for r in out.data["rows"]), out.data["rows"][:2]
    one_day = _run(SECTFunction(FunctionDeps()).execute(period="1D"))
    assert all(r["change_pct"] is not None for r in one_day.data["rows"])
