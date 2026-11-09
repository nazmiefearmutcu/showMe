"""LOTS — open / sell must work when the generic route has moved the symbol.

Finding LOTS#1: server.py pops ``symbol`` out of the params and turns it into
the instrument before the handler runs. LOTS open and sell read
``params["symbol"]`` and raised KeyError, so no tax lot could be opened or sold
through /api/fn. The handler must take the symbol from the instrument, and a
truly missing symbol or quantity must return input_error, not raise.

Offline: the tax-lot ledger is a temporary SQLite file.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest  # noqa: E402

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.core.instrument import AssetClass, Instrument  # noqa: E402
from showme.engine.functions.portfolio.lots import LOTSFunction  # noqa: E402
from showme.engine.services import tax_lots  # noqa: E402

SYM = Instrument(symbol="AUDTEST", asset_class=AssetClass.EQUITY)


@pytest.fixture(autouse=True)
def _ledger(monkeypatch, tmp_path):
    monkeypatch.setattr(tax_lots, "_db_file", lambda: tmp_path / "tax_lots.sqlite")


def _run(**kwargs):
    fn = LOTSFunction(FunctionDeps())
    return asyncio.run(fn.execute(**kwargs))


def test_open_takes_symbol_from_the_routed_instrument() -> None:
    # This is the call shape the route produces: no "symbol" in params.
    # Before the fix: KeyError 'symbol'.
    result = _run(instrument=SYM, action="open", quantity=10, price=100)
    assert result.data.get("status") in (None, "ok")
    assert result.data["action"] == "open"
    lots = tax_lots.list_open_lots(symbol="AUDTEST")
    assert len(lots) == 1
    assert lots[0]["quantity"] == pytest.approx(10.0)


def test_sell_takes_symbol_from_the_routed_instrument() -> None:
    _run(instrument=SYM, action="open", quantity=10, price=100)
    result = _run(instrument=SYM, action="sell", quantity=4, price=120, method="FIFO")
    assert result.data["symbol"] == "AUDTEST"
    assert result.data["qty_filled"] == pytest.approx(4.0)


def test_list_filters_by_routed_symbol() -> None:
    _run(instrument=SYM, action="open", quantity=10, price=100)
    _run(instrument=Instrument(symbol="OTHER", asset_class=AssetClass.EQUITY),
         action="open", quantity=5, price=50)
    result = _run(instrument=SYM, action="list")
    symbols = {row["symbol"] for row in result.data["lots"]}
    # Before the fix the symbol was dropped and every open lot came back.
    assert symbols == {"AUDTEST"}


def test_open_without_any_symbol_is_input_error_not_a_crash() -> None:
    result = _run(instrument=None, action="open", quantity=10, price=100)
    assert result.data.get("status") == "input_error"
    assert "symbol" in result.data.get("missing", [])
    assert tax_lots.list_open_lots() == []


def test_open_with_bad_quantity_is_input_error_and_writes_nothing() -> None:
    result = _run(instrument=SYM, action="open", quantity="ten", price=100)
    assert result.data.get("status") == "input_error"
    assert "quantity" in result.data.get("missing", [])
    assert tax_lots.list_open_lots() == []


def test_open_with_zero_or_negative_quantity_is_input_error_and_writes_nothing() -> None:
    # A zero or negative lot is accepted by open_lot but never listed, so it
    # would be a silent invisible row. It must be rejected before any write.
    for quantity in (0, -5):
        result = _run(instrument=SYM, action="open", quantity=quantity, price=100)
        assert result.data.get("status") == "input_error", quantity
        assert "quantity" in result.data.get("missing", [])
    assert tax_lots.list_open_lots() == []


def test_open_with_negative_price_is_input_error_and_writes_nothing() -> None:
    result = _run(instrument=SYM, action="open", quantity=10, price=-1)
    assert result.data.get("status") == "input_error"
    assert "price" in result.data.get("missing", [])
    assert tax_lots.list_open_lots() == []


def test_sell_with_non_positive_quantity_is_input_error_and_keeps_the_lot() -> None:
    _run(instrument=SYM, action="open", quantity=10, price=100)
    for quantity in (0, -3):
        result = _run(instrument=SYM, action="sell", quantity=quantity, price=120, method="FIFO")
        assert result.data.get("status") == "input_error", quantity
        assert "quantity" in result.data.get("missing", [])
    lots = tax_lots.list_open_lots(symbol="AUDTEST")
    assert len(lots) == 1
    assert lots[0]["quantity"] == pytest.approx(10.0)


# Review of LOTS#1 (P0 wave): the list must not narrow to a symbol the user
# never chose. The router injects a default symbol with __explicit_symbol=False.
def test_router_default_symbol_does_not_filter_the_list(monkeypatch, tmp_path):

    tax_lots.open_lot(symbol="AAPL", quantity=10, price=150.0)
    tax_lots.open_lot(symbol="MSFT", quantity=5, price=300.0)
    btc = Instrument(symbol="BTCUSDT", asset_class=AssetClass.CRYPTO)
    res = asyncio.run(LOTSFunction(FunctionDeps()).execute(instrument=btc, __explicit_symbol=False))
    assert sorted(r["symbol"] for r in res.data["rows"]) == ["AAPL", "MSFT"]


def test_explicit_symbol_still_filters_the_list(monkeypatch, tmp_path):

    tax_lots.open_lot(symbol="AAPL", quantity=10, price=150.0)
    tax_lots.open_lot(symbol="MSFT", quantity=5, price=300.0)
    aapl = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    res = asyncio.run(LOTSFunction(FunctionDeps()).execute(instrument=aapl))
    assert [r["symbol"] for r in res.data["rows"]] == ["AAPL"]


def test_router_default_symbol_never_writes_a_lot(monkeypatch, tmp_path):

    btc = Instrument(symbol="BTCUSDT", asset_class=AssetClass.CRYPTO)
    res = asyncio.run(LOTSFunction(FunctionDeps()).execute(
        instrument=btc, action="open", quantity=1, price=100.0, __explicit_symbol=False))
    assert res.data["status"] == "input_error"
    assert tax_lots.list_open_lots() == []
