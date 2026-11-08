"""DES#4: an ETF is shown as an ETF and an S&P index exchange code gets a readable label.

The router builds the instrument with a heuristic that has no ETF branch, so SPY arrives
as EQUITY even though the symbol registry knows it is an ETF. Yahoo's index exchange code
SNP was shown raw because the legend had no entry for it.
"""
from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.core.refdata import ReferenceData
from showme.engine.functions.equity.des import DESFunction


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class _SeenYF:
    """Mimics the yfinance refdata adapter: the asset_class it returns is the request's."""

    def __init__(self, exchange: str | None) -> None:
        self.exchange = exchange
        self.seen_classes: list[str] = []

    async def fetch(self, request: Any) -> Any:
        self.seen_classes.append(request.instrument.asset_class.value)
        return ReferenceData(
            symbol=request.instrument.symbol,
            name="Test Name",
            asset_class=request.instrument.asset_class.value,
            exchange=self.exchange,
            currency="USD",
            source="yfinance",
            extras={"raw": {}},
        )


def test_spy_routed_as_equity_is_described_as_an_etf():
    yf = _SeenYF(exchange="PCX")
    inst = Instrument(symbol="SPY", asset_class=AssetClass.EQUITY, exchange="NYSE", currency="USD")
    res = _run(DESFunction(FunctionDeps(yfinance=yf)).execute(instrument=inst))
    assert yf.seen_classes == ["ETF"]
    assert res.data["asset_class"] == "ETF"
    assert res.metadata["asset_class"] == "ETF"


def test_ordinary_equity_stays_equity():
    yf = _SeenYF(exchange="NMS")
    inst = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY, exchange="NMS", currency="USD")
    res = _run(DESFunction(FunctionDeps(yfinance=yf)).execute(instrument=inst))
    assert yf.seen_classes == ["EQUITY"]
    assert res.data["asset_class"] == "EQUITY"


def test_snp_index_exchange_code_gets_a_readable_name():
    yf = _SeenYF(exchange="SNP")
    inst = Instrument(symbol="^GSPC", asset_class=AssetClass.INDEX, currency="USD")
    res = _run(DESFunction(FunctionDeps(yfinance=yf)).execute(instrument=inst))
    assert res.data["exchange_name"] == "S&P Indices"
    assert res.data["exchange"] == "SNP"


def test_unknown_exchange_code_still_shows_the_raw_code():
    yf = _SeenYF(exchange="ZZZ")
    inst = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY, currency="USD")
    res = _run(DESFunction(FunctionDeps(yfinance=yf)).execute(instrument=inst))
    assert res.data["exchange_name"] == "ZZZ"
