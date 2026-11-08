"""PORT audit group p2a-g01, review round: rows-path grouping and honest total_equity.

Network is never touched: the yfinance adapter is replaced by an in-memory fake
that answers from a fixed table (or raises for unknown symbols).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

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

    async def fetch(self, request):  # noqa: ANN001 - DataRequest is loose
        sym = request.instrument.symbol
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


def _eq(symbol: str, qty: float, avg: float, *, currency: str = "USD", account: str = "main") -> PortfolioPosition:
    return PortfolioPosition(
        instrument=Instrument(symbol=symbol, asset_class=AssetClass.EQUITY, exchange="NASDAQ",
                              currency=currency, metadata={}),
        quantity=qty, avg_cost=avg, currency=currency, account=account,
    )


def _run(fn: PORTFunction, **kwargs):
    return asyncio.run(fn.execute(**kwargs))


def _row(symbol: str, qty: float, avg: float, last: float | None, *, asset_class: str = "equity",
         account: str = "main", currency: str = "USD") -> dict:
    row = {"symbol": symbol, "asset_class": asset_class, "quantity": qty, "avg_cost": avg,
           "currency": currency, "account": account}
    if last is not None:
        row["last"] = last
    return row


# --- PORT#1: declared group_by must take effect on the supplied-rows path ----

def test_supplied_rows_group_by_account_returns_grouped_totals(tmp_path: Path) -> None:
    rows = [_row("AAPL", 1, 100.0, 100.0, account="broker_a"),
            _row("MSFT", 2, 100.0, 100.0, account="broker_b")]
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({})))

    result = _run(fn, _portfolio_override=PortfolioState(tmp_path / "empty.json"),
                  positions=rows, ccy="USD", group_by="account")

    assert result.data["group_by"] == "account"
    groups = {g["key"]: g for g in result.data["groups"]}
    assert set(groups) == {"broker_a", "broker_b"}
    assert groups["broker_a"]["market_value"] == 100.0
    assert groups["broker_b"]["market_value"] == 200.0
    assert groups["broker_b"]["weight_pct"] == pytest.approx(200.0 / 300.0 * 100)


def test_supplied_rows_default_group_is_asset_class_and_fills_by_asset_class(tmp_path: Path) -> None:
    rows = [_row("AAPL", 1, 100.0, 100.0, asset_class="equity"),
            _row("BTC", 2, 100.0, 100.0, asset_class="crypto")]
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({})))

    result = _run(fn, _portfolio_override=PortfolioState(tmp_path / "empty.json"),
                  positions=rows, ccy="USD")

    assert result.data["group_by"] == "asset_class"
    assert {g["key"] for g in result.data["groups"]} == {"equity", "crypto"}
    assert result.data["by_asset_class"] == {"equity": 100.0, "crypto": 200.0}


def test_supplied_rows_group_by_none_returns_no_groups(tmp_path: Path) -> None:
    rows = [_row("AAPL", 1, 100.0, 100.0)]
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({})))

    result = _run(fn, _portfolio_override=PortfolioState(tmp_path / "empty.json"),
                  positions=rows, ccy="USD", group_by="none")

    assert result.data["groups"] == []


def test_supplied_rows_group_by_sector_without_sector_is_flagged(tmp_path: Path) -> None:
    rows = [_row("AAPL", 1, 100.0, 100.0)]
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({})))

    result = _run(fn, _portfolio_override=PortfolioState(tmp_path / "empty.json"),
                  positions=rows, ccy="USD", group_by="sector")

    assert [g["key"] for g in result.data["groups"]] == ["unclassified"]
    assert any("sector" in w for w in result.warnings)


def test_supplied_rows_unpriced_group_reports_no_value(tmp_path: Path) -> None:
    rows = [_row("XYZ", 10, 50.0, None, account="broker_a")]
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({})))

    result = _run(fn, _portfolio_override=PortfolioState(tmp_path / "empty.json"),
                  positions=rows, ccy="USD", group_by="account")

    group = result.data["groups"][0]
    assert group["key"] == "broker_a"
    assert group["market_value"] is None
    assert group["weight_pct"] is None


# --- PORT#2: total_equity must not silently omit non-stable cash ------------

def test_foreign_cash_is_converted_into_total_equity(tmp_path: Path) -> None:
    book = _book(tmp_path, _eq("AAPL", 2, 100.0), cash={"USD": 0.0, "TRY": 5000.0})
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({"AAPL": (110.0, 105.0),
                                                          "TRYUSD": (0.03, None)})))

    totals = _run(fn, _portfolio_override=book).data["totals"]

    assert totals["cash_by_currency"] == {"USD": 0.0, "TRY": 5000.0}
    assert totals["cash_total_base"] == pytest.approx(150.0)
    assert totals["total_equity"] == pytest.approx(220.0 + 150.0)


def test_total_equity_is_withheld_with_warning_when_foreign_cash_has_no_rate(tmp_path: Path) -> None:
    book = _book(tmp_path, _eq("AAPL", 2, 100.0), cash={"USD": 0.0, "TRY": 5000.0})
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({"AAPL": (110.0, 105.0)})))

    result = _run(fn, _portfolio_override=book)
    totals = result.data["totals"]

    assert totals["total_equity"] is None
    assert totals["cash_total_base"] is None
    assert totals["cash_by_currency"]["TRY"] == 5000.0
    assert any("TRY" in w and "FX" in w for w in result.warnings)


def test_usd_only_cash_keeps_cash_total_equal_to_stable_cash(tmp_path: Path) -> None:
    book = _book(tmp_path, _eq("AAPL", 2, 100.0), cash={"USD": 1000.0})
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({"AAPL": (110.0, 105.0)})))

    totals = _run(fn, _portfolio_override=book).data["totals"]

    assert totals["cash_total_base"] == 1000.0
    assert totals["total_equity"] == 1220.0


def test_supplied_rows_path_includes_foreign_cash_in_total_equity(tmp_path: Path) -> None:
    book = _book(tmp_path, cash={"TRY": 5000.0})
    rows = [_row("MSFT", 1, 100.0, 110.0)]
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({"TRYUSD": (0.03, None)})))

    totals = _run(fn, _portfolio_override=book, positions=rows, ccy="USD").data["totals"]

    assert totals["cash_total_base"] == pytest.approx(150.0)
    assert totals["total_equity"] == pytest.approx(110.0 + 150.0)


# --- PORT#2: manifest must not promise a series that is not produced -------

def test_port_manifest_promises_no_equity_series() -> None:
    from showme.manifest import REGISTRY, load_seeds

    load_seeds()
    entry = REGISTRY.get("PORT")
    assert entry.chart_grammar is None
    assert "equity_drawdown_pct" not in entry.alerting.conditions
    assert entry.output_contract.series is False
