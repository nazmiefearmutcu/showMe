"""PORT audit group p2a-g01: honest totals, quote provenance, declared inputs.

Network is never touched: the yfinance adapter is replaced by an in-memory
fake that answers from a fixed table (or raises for unknown symbols).
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
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
    """Yahoo-like fake: ``table[symbol] = (last, close_prev)``; unknown symbols raise."""

    def __init__(self, table: dict[str, tuple[float, float | None]]) -> None:
        self.table = table
        self.requested: list[str] = []

    async def fetch(self, request):  # noqa: ANN001 - DataRequest is loose
        sym = request.instrument.symbol
        self.requested.append(sym)
        if sym not in self.table:
            raise RuntimeError(f"no quote for {sym}")
        last, prev = self.table[sym]
        return Quote(symbol=sym, timestamp=utcnow(), last=last, close_prev=prev, source="yfinance")


def _book(tmp_path: Path, *positions: PortfolioPosition, cash: dict[str, float] | None = None) -> PortfolioState:
    book = PortfolioState(tmp_path / "portfolio.json")
    book.positions = []
    for p in positions:
        book.add_position(p)
    if cash is not None:
        book.cash = dict(cash)
    return book


def _eq(symbol: str, qty: float, avg: float, *, currency: str = "USD", account: str = "main",
        metadata: dict | None = None) -> PortfolioPosition:
    return PortfolioPosition(
        instrument=Instrument(symbol=symbol, asset_class=AssetClass.EQUITY, exchange="NASDAQ",
                              currency=currency, metadata=dict(metadata or {})),
        quantity=qty, avg_cost=avg, currency=currency, account=account,
    )


def _run(fn: PORTFunction, **kwargs):
    return asyncio.run(fn.execute(**kwargs))


# --- PORT#5 -----------------------------------------------------------------

def test_port_declares_description_and_rows_carry_currency(tmp_path: Path) -> None:
    assert PORTFunction.description.strip(), "PORT must have a function-index description"

    book = _book(tmp_path, _eq("SAP", 3, 100.0, currency="EUR"))
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({"SAP": (120.0, 118.0)})))
    result = _run(fn, _portfolio_override=book)

    row = result.data["positions"][0]
    assert row["currency"] == "EUR"


# --- PORT#3 / PORT#6 --------------------------------------------------------

def test_failed_quote_without_recorded_price_is_not_marked_at_cost(tmp_path: Path) -> None:
    book = _book(tmp_path, _eq("XYZ", 10, 50.0))
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({})))  # every quote raises

    result = _run(fn, _portfolio_override=book)

    row = result.data["positions"][0]
    assert row["last"] is None
    assert row["market_value"] is None
    assert row["unrealized_pnl"] is None
    assert row["quote_missing"] is True
    assert row["price_source"] == "missing"
    assert result.data["totals"]["n_unpriced"] == 1
    assert any("XYZ" in w for w in result.warnings)
    assert "yfinance" not in result.sources


def test_failed_quote_uses_labelled_legacy_snapshot_price(tmp_path: Path) -> None:
    book = _book(tmp_path, _eq("ABC", 2, 10.0, metadata={"current_price": 12.5,
                                                         "legacy_source": "state.json"}))
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({})))

    result = _run(fn, _portfolio_override=book)

    row = result.data["positions"][0]
    assert row["last"] == 12.5
    assert row["price_source"] == "legacy_snapshot"
    assert row["quote_missing"] is False
    assert result.metadata["price_state"] != "live"
    assert any("ABC" in w and "legacy" in w for w in result.warnings)


def test_live_quotes_report_live_price_state(tmp_path: Path) -> None:
    book = _book(tmp_path, _eq("AAPL", 1, 100.0))
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({"AAPL": (150.0, 149.0)})))

    result = _run(fn, _portfolio_override=book)

    assert result.data["positions"][0]["price_source"] == "yfinance"
    assert result.metadata["price_state"] == "live"
    assert result.metadata["price_sources"] == {"yfinance": 1, "legacy_snapshot": 0, "missing": 0}
    assert result.sources == ["portfolio_state", "yfinance"]


# --- PORT#2 -----------------------------------------------------------------

def test_totals_expose_total_equity_and_day_pnl(tmp_path: Path) -> None:
    book = _book(tmp_path, _eq("AAPL", 2, 100.0), cash={"USD": 1000.0})
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({"AAPL": (110.0, 105.0)})))

    result = _run(fn, _portfolio_override=book)
    totals = result.data["totals"]

    assert totals["market_value"] == 220.0
    assert totals["cash"] == 1000.0
    assert totals["total_equity"] == 1220.0  # cash + sum of market values
    assert totals["day_pnl"] == 10.0  # 2 * (110 - 105), previous close based
    row = result.data["positions"][0]
    assert row["day_change"] == 10.0
    assert row["day_change_pct"] == (110.0 / 105.0 - 1) * 100


def test_day_pnl_is_none_without_previous_close(tmp_path: Path) -> None:
    book = _book(tmp_path, _eq("AAPL", 2, 100.0), cash={"USD": 1000.0})
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({"AAPL": (110.0, None)})))

    result = _run(fn, _portfolio_override=book)

    assert result.data["totals"]["day_pnl"] is None
    assert any("day P&L" in w and "AAPL" in w for w in result.warnings)


def test_total_equity_is_none_when_cash_is_not_tracked(tmp_path: Path) -> None:
    book = _book(tmp_path, _eq("AAPL", 2, 100.0))
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({"AAPL": (110.0, 105.0)})))

    totals = _run(fn, _portfolio_override=book).data["totals"]

    assert "cash" not in totals
    assert totals["total_equity"] is None


def test_realized_pnl_ytd_sums_closes_dated_this_year(tmp_path: Path) -> None:
    book = _book(tmp_path, _eq("AAPL", 1, 100.0), cash={"USD": 0.0})
    now = datetime.now(timezone.utc)
    book.closed_positions = [
        {"symbol": "OLD", "realized_pnl": 999.0, "closed_at": f"{now.year - 1}-06-01T00:00:00+00:00"},
        {"symbol": "NEW", "realized_pnl": 40.0, "closed_at": now.isoformat()},
        {"symbol": "NEW2", "realized_pnl": -15.0, "closed_at": now.isoformat()},
    ]
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({"AAPL": (110.0, 105.0)})))

    totals = _run(fn, _portfolio_override=book).data["totals"]

    assert totals["realized_pnl_ytd"] == 25.0


def test_realized_pnl_ytd_is_zero_when_nothing_closed(tmp_path: Path) -> None:
    book = _book(tmp_path, _eq("AAPL", 1, 100.0), cash={"USD": 0.0})
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({"AAPL": (110.0, 105.0)})))

    totals = _run(fn, _portfolio_override=book).data["totals"]

    assert totals["realized_pnl_ytd"] == 0.0
