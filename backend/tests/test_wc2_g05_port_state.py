"""WC2-G05 / PORT#6-RQ: data_state describes the valued book, not the quote sources.

A live quote whose row cannot be valued (no FX rate) must not label the book
live. Network is never touched: yfinance is an in-memory fake.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.core.instrument import AssetClass, Instrument  # noqa: E402
from showme.engine.core.quote import Quote, utcnow  # noqa: E402
from showme.engine.functions.portfolio.port import PORTFunction  # noqa: E402
from showme.engine.portfolio.state import PortfolioPosition, PortfolioState  # noqa: E402


class _Quotes:
    """``table[symbol] = (last, close_prev)``; unknown symbols raise (no FX rate)."""

    def __init__(self, table: dict[str, tuple[float, float | None]]) -> None:
        self.table = table

    async def fetch(self, request):  # noqa: ANN001
        sym = request.instrument.symbol
        if sym not in self.table:
            raise RuntimeError(f"no quote for {sym}")
        last, prev = self.table[sym]
        return Quote(symbol=sym, timestamp=utcnow(), last=last, close_prev=prev, source="yfinance")


def _book(tmp_path: Path, *positions: PortfolioPosition) -> PortfolioState:
    book = PortfolioState(tmp_path / "portfolio.json")
    book.positions = []
    for p in positions:
        book.add_position(p)
    return book


def _eq(symbol: str, qty: float, avg: float, *, currency: str = "USD") -> PortfolioPosition:
    return PortfolioPosition(
        instrument=Instrument(symbol=symbol, asset_class=AssetClass.EQUITY, exchange="NASDAQ",
                              currency=currency, metadata={}),
        quantity=qty, avg_cost=avg, currency=currency, account="main",
    )


def _run(fn: PORTFunction, **kwargs):
    return asyncio.run(fn.execute(**kwargs))


def test_live_quote_without_fx_rate_is_not_a_live_book(tmp_path: Path) -> None:
    """One EUR position, live SAP quote, no EURUSD rate: the row is unvalued."""
    book = _book(tmp_path, _eq("SAP", 1, 100.0, currency="EUR"))
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({"SAP": (120.0, 119.0)})))
    out = _run(fn, _portfolio_override=book)
    assert out.data["totals"]["n_unpriced"] == 1
    assert out.data["totals"]["n_positions"] == 1
    assert out.metadata["price_state"] == "unavailable"
    assert out.metadata["data_state"] == "unavailable"


def test_partially_valued_book_with_live_quotes_is_partial(tmp_path: Path) -> None:
    book = _book(tmp_path, _eq("AAPL", 1, 100.0), _eq("SAP", 1, 100.0, currency="EUR"))
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({
        "AAPL": (150.0, 149.0),
        "SAP": (120.0, 119.0),
    })))
    out = _run(fn, _portfolio_override=book)
    assert out.data["totals"]["n_unpriced"] == 1
    assert out.metadata["data_state"] == "partial"
    assert out.metadata["price_state"] == "partial"


def test_fully_valued_live_book_stays_live(tmp_path: Path) -> None:
    book = _book(tmp_path, _eq("AAPL", 1, 100.0))
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({"AAPL": (150.0, 149.0)})))
    out = _run(fn, _portfolio_override=book)
    assert out.data["totals"]["n_unpriced"] == 0
    assert out.metadata["data_state"] == "live"
