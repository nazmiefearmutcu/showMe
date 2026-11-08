"""PORT audit group p2a-g01: honest totals, quote provenance, declared inputs.

Network is never touched: the yfinance adapter is replaced by an in-memory
fake that answers from a fixed table (or raises for unknown symbols).
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
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


# --- PORT#1 -----------------------------------------------------------------

def test_show_zero_default_drops_zero_quantity_rows(tmp_path: Path) -> None:
    book = _book(tmp_path, _eq("AAPL", 1, 100.0), _eq("OLD", 0, 50.0))
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({"AAPL": (110.0, 105.0)})))

    default = _run(fn, _portfolio_override=book)
    assert [r["symbol"] for r in default.data["positions"]] == ["AAPL"]

    with_zero = _run(fn, _portfolio_override=book, show_zero="true")
    assert [r["symbol"] for r in with_zero.data["positions"]] == ["AAPL", "OLD"]


def test_accounts_filter_limits_the_book(tmp_path: Path) -> None:
    book = _book(tmp_path, _eq("AAPL", 1, 100.0, account="broker_a"),
                 _eq("MSFT", 1, 100.0, account="broker_b"))
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({"AAPL": (110.0, 105.0),
                                                          "MSFT": (110.0, 105.0)})))

    only_a = _run(fn, _portfolio_override=book, accounts=["broker_a"])
    assert [r["symbol"] for r in only_a.data["positions"]] == ["AAPL"]
    assert only_a.data["totals"]["n_positions"] == 1

    everything = _run(fn, _portfolio_override=book, accounts=["ALL"])
    assert len(everything.data["positions"]) == 2


def test_group_by_account_returns_grouped_totals(tmp_path: Path) -> None:
    book = _book(tmp_path, _eq("AAPL", 1, 100.0, account="broker_a"),
                 _eq("MSFT", 2, 100.0, account="broker_b"))
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({"AAPL": (100.0, 99.0),
                                                          "MSFT": (100.0, 99.0)})))

    result = _run(fn, _portfolio_override=book, group_by="account")
    groups = {g["key"]: g for g in result.data["groups"]}

    assert groups["broker_a"]["market_value"] == 100.0
    assert groups["broker_b"]["market_value"] == 200.0
    assert groups["broker_b"]["weight_pct"] == 200.0 / 300.0 * 100


def test_group_by_none_returns_no_groups(tmp_path: Path) -> None:
    book = _book(tmp_path, _eq("AAPL", 1, 100.0))
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({"AAPL": (100.0, 99.0)})))

    assert _run(fn, _portfolio_override=book, group_by="none").data["groups"] == []


def test_group_by_sector_without_sector_data_is_flagged(tmp_path: Path) -> None:
    book = _book(tmp_path, _eq("AAPL", 1, 100.0))
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({"AAPL": (100.0, 99.0)})))

    result = _run(fn, _portfolio_override=book, group_by="sector")

    assert [g["key"] for g in result.data["groups"]] == ["unclassified"]
    assert any("sector" in w for w in result.warnings)


def test_ccy_converts_non_base_positions_with_fx_rate(tmp_path: Path) -> None:
    book = _book(tmp_path, _eq("SAP", 10, 100.0, currency="EUR"))
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({"SAP": (120.0, 118.0),
                                                          "EURUSD": (1.10, None)})))

    result = _run(fn, _portfolio_override=book, ccy="USD")
    row = result.data["positions"][0]

    assert row["last"] == 120.0  # native price is kept
    assert row["fx_rate"] == 1.10
    assert row["market_value"] == pytest.approx(10 * 120.0 * 1.10)
    assert result.data["totals"]["market_value"] == pytest.approx(1320.0)
    assert result.data["ccy"] == "USD"
    assert result.data["fx_rates"]["EUR"] == 1.10
    assert "yfinance" in result.sources


def test_ccy_without_fx_rate_excludes_position_and_warns(tmp_path: Path) -> None:
    book = _book(tmp_path, _eq("SAP", 10, 100.0, currency="EUR"))
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({"SAP": (120.0, 118.0)})))

    result = _run(fn, _portfolio_override=book, ccy="USD")
    row = result.data["positions"][0]

    assert row["fx_rate"] is None
    assert row["market_value"] is None
    assert result.data["totals"]["market_value"] == 0.0
    assert result.data["totals"]["n_unpriced"] == 1
    assert result.data["fx_rates"] == {"EUR": None}
    assert any("EURUSD" in w for w in result.warnings)


def test_historical_as_of_is_reported_not_silently_live(tmp_path: Path) -> None:
    book = _book(tmp_path, _eq("AAPL", 1, 100.0))
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({"AAPL": (110.0, 105.0)})))

    result = _run(fn, _portfolio_override=book, as_of="2020-01-02")

    assert result.data["status"] == "provider_unavailable"
    assert result.data["positions"] == []
    assert "totals" not in result.data
    assert result.data["next_actions"]


def test_today_as_of_is_the_live_book(tmp_path: Path) -> None:
    book = _book(tmp_path, _eq("AAPL", 1, 100.0))
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({"AAPL": (110.0, 105.0)})))
    today = datetime.now(timezone.utc).date().isoformat()

    result = _run(fn, _portfolio_override=book, as_of=today)

    assert "status" not in result.data
    assert result.data["totals"]["market_value"] == 110.0


def test_invalid_ccy_is_an_input_error(tmp_path: Path) -> None:
    book = _book(tmp_path, _eq("AAPL", 1, 100.0))
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({"AAPL": (110.0, 105.0)})))

    result = _run(fn, _portfolio_override=book, ccy="US")

    assert result.data["status"] == "input_error"
    assert result.data["positions"] == []


# --- PORT#1 supplied-rows path (empty book + params.positions) ---------------

def _empty_book(tmp_path: Path) -> PortfolioState:
    return _book(tmp_path)


def test_supplied_rows_are_converted_to_base_ccy_and_account_filtered(tmp_path: Path) -> None:
    rows = [
        {"symbol": "SAP", "asset_class": "equity", "quantity": 10, "avg_cost": 100.0,
         "last": 120.0, "currency": "EUR", "account": "broker_a"},
        {"symbol": "MSFT", "asset_class": "equity", "quantity": 1, "avg_cost": 100.0,
         "last": 110.0, "currency": "USD", "account": "broker_b"},
    ]
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({"EURUSD": (1.10, None)})))

    result = _run(fn, _portfolio_override=_empty_book(tmp_path), positions=rows,
                  ccy="USD", accounts=["broker_a"])

    assert [r["symbol"] for r in result.data["positions"]] == ["SAP"]
    row = result.data["positions"][0]
    assert row["fx_rate"] == 1.10
    assert row["market_value"] == pytest.approx(10 * 120.0 * 1.10)
    assert result.data["totals"]["market_value"] == pytest.approx(1320.0)
    assert result.data["totals"]["n_positions"] == 1
    assert result.data["ccy"] == "USD"


def test_supplied_rows_without_fx_rate_are_unpriced_not_relabelled(tmp_path: Path) -> None:
    rows = [{"symbol": "SAP", "asset_class": "equity", "quantity": 10, "avg_cost": 100.0,
             "last": 120.0, "currency": "EUR"}]
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({})))

    result = _run(fn, _portfolio_override=_empty_book(tmp_path), positions=rows, ccy="USD")

    row = result.data["positions"][0]
    assert row["market_value"] is None
    assert result.data["totals"]["market_value"] == 0.0
    assert result.data["totals"]["n_unpriced"] == 1
    assert any("EURUSD" in w for w in result.warnings)


def test_supplied_row_without_last_is_not_marked_at_cost(tmp_path: Path) -> None:
    rows = [{"symbol": "XYZ", "asset_class": "equity", "quantity": 10, "avg_cost": 50.0,
             "currency": "USD"}]
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({})))

    result = _run(fn, _portfolio_override=_empty_book(tmp_path), positions=rows, ccy="USD")

    row = result.data["positions"][0]
    assert row["last"] is None
    assert row["market_value"] is None
    assert result.data["totals"]["market_value"] == 0.0


# --- PORT#2 day P&L is withheld while any position is unpriced ----------------

def test_day_pnl_is_withheld_when_a_position_is_unpriced(tmp_path: Path) -> None:
    book = _book(tmp_path, _eq("AAPL", 2, 100.0), _eq("XYZ", 1, 50.0), cash={"USD": 1000.0})
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({"AAPL": (110.0, 105.0)})))

    result = _run(fn, _portfolio_override=book)
    totals = result.data["totals"]

    assert totals["n_unpriced"] == 1
    assert totals["total_equity"] is None  # same rule as day P&L: partial sums are withheld
    assert totals["day_pnl"] is None
    assert any("day P&L" in w and "unpriced" in w for w in result.warnings)


# --- PORT#6 data_state derived from the quote sources --------------------------

def test_data_state_is_live_only_when_every_quote_is_live(tmp_path: Path) -> None:
    book = _book(tmp_path, _eq("AAPL", 1, 100.0))
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({"AAPL": (150.0, 149.0)})))
    assert _run(fn, _portfolio_override=book).metadata["data_state"] == "live"


def test_data_state_is_reference_for_recorded_snapshot_prices(tmp_path: Path) -> None:
    book = _book(tmp_path, _eq("ABC", 2, 10.0, metadata={"current_price": 12.5}))
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({})))
    assert _run(fn, _portfolio_override=book).metadata["data_state"] == "reference"


def test_data_state_is_unavailable_when_nothing_prices(tmp_path: Path) -> None:
    book = _book(tmp_path, _eq("XYZ", 10, 50.0))
    fn = PORTFunction(deps=FunctionDeps(yfinance=_Quotes({})))
    assert _run(fn, _portfolio_override=book).metadata["data_state"] == "unavailable"


# --- PORT#2 manifest must not promise an equity curve that is not produced -----

def test_port_manifest_does_not_promise_equity_curve() -> None:
    from showme.manifest import REGISTRY, load_seeds

    load_seeds()
    entry = REGISTRY.get("PORT")
    assert not [k for k in entry.field_dict if k.startswith("equity_curve")]
    assert "reconstructed from snapshot" not in entry.methodology.lower()
    assert not [t for t in entry.semantic_tests if "equity_curve" in t.name]
