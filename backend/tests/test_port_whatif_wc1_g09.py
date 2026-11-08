"""PORT_WHATIF (wc1-g09): cash debit, lot merge/sell, quote reuse, manifest honesty.

Findings covered:
* PORT_WHATIF#2 - a what-if buy never debited cash, so equity rose by the notional.
* PORT_WHATIF#4 - a held symbol was appended as a duplicate lot and a sell was
  booked as a negative lot (a short), not as a reduction of the holding.
* PORT_WHATIF#5 - the manifest promised scenario actions, cash floor and risk
  features the handler never computes.
* PORT_WHATIF#6 - PORT ran twice, so every quote was fetched twice.
* PORT_WHATIF#7 - the function description was empty.

Offline: the portfolio state, the PORT analytics and the quote adapter are fakes.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest  # noqa: E402

from showme.engine.core.base_data_source import DataKind, DataRequest  # noqa: E402
from showme.engine.core.base_function import FunctionDeps, FunctionResult  # noqa: E402
from showme.engine.core.instrument import AssetClass, Instrument  # noqa: E402
from showme.engine.functions.portfolio import _more as more_mod  # noqa: E402
from showme.engine.functions.portfolio import port as port_mod  # noqa: E402
from showme.engine.portfolio.state import PortfolioPosition  # noqa: E402
from showme.manifest import REGISTRY, load_seeds  # noqa: E402

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
NVDA = Instrument(symbol="NVDA", asset_class=AssetClass.EQUITY)

# The book every fake state starts from, and the last price each fake PORT marks at.
_SEED: dict[str, Any] = {"positions": [], "cash": {}, "prices": {}}
# Positions each fake PORT run analysed, in call order (baseline first, scenario second).
_SEEN: list[list[PortfolioPosition]] = []
# Cash dict each fake PORT run analysed, in the same call order.
_CASH_SEEN: list[dict[str, float]] = []


class _FakeState:
    def __init__(self, path=None):
        self.positions = list(_SEED["positions"])
        self.cash = dict(_SEED["cash"])

    def import_legacy_crypto(self):
        return 0


class _FakePort:
    """PORT stand-in: marks each position at the seeded price and fetches its quote."""

    def __init__(self, deps=None):
        self.deps = deps

    async def execute(self, _portfolio_override=None, **_params):
        positions = list(getattr(_portfolio_override, "positions", []))
        cash = dict(getattr(_portfolio_override, "cash", {}) or {})
        _SEEN.append(positions)
        _CASH_SEEN.append(cash)
        if self.deps is not None and self.deps.yfinance is not None:
            for pos in positions:
                await self.deps.yfinance.fetch(DataRequest(kind=DataKind.QUOTE, instrument=pos.instrument))
        market_value = 0.0
        unrealized = 0.0
        for pos in positions:
            last = _SEED["prices"][pos.instrument.symbol]
            market_value += float(pos.quantity) * last
            unrealized += (last - float(pos.avg_cost)) * float(pos.quantity)
        usd_cash = float(cash["USD"]) if "USD" in cash else None
        totals = {
            "market_value": market_value,
            "unrealized_pnl": unrealized,
            "n_positions": len(positions),
            "cash": usd_cash,
            # Mirrors PORT: total equity is withheld when the book tracks no cash.
            "total_equity": (market_value + usd_cash) if usd_cash is not None else None,
        }
        return FunctionResult(code="PORT", instrument=None, data={"totals": totals},
                              sources=["fake_portfolio"])


class _CountingQuotes:
    """Quote adapter that counts fetches per symbol."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def fetch(self, request: DataRequest) -> Any:
        self.calls.append(request.instrument.symbol)
        price = _SEED["prices"][request.instrument.symbol]
        return type("Quote", (), {"last": price, "close_prev": None})()


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    _SEED.update({"positions": [], "cash": {}, "prices": {"AAPL": 120.0, "NVDA": 150.0}})
    _SEEN.clear()
    _CASH_SEEN.clear()
    monkeypatch.setattr(more_mod, "PortfolioState", _FakeState)
    monkeypatch.setattr(port_mod, "PORTFunction", _FakePort)
    load_seeds()


def _lot(instrument: Instrument, quantity: float, avg_cost: float) -> PortfolioPosition:
    return PortfolioPosition(instrument=instrument, quantity=quantity, avg_cost=avg_cost)


def _run(params: dict[str, Any], instrument: Instrument = AAPL, deps: FunctionDeps | None = None):
    fn = more_mod.PORTWhatIfFunction(deps or FunctionDeps())
    return asyncio.run(fn.execute(instrument=instrument, **params))


# ── PORT_WHATIF#2: cash is debited ───────────────────────────────────────────


def test_buy_debits_cash_so_equity_moves_only_by_the_price_gain() -> None:
    _SEED["cash"] = {"USD": 25000.0}
    result = _run({"quantity": 100, "cost": 100})
    summary = result.data["summary"]
    # Cash pays 100 x 100 = 10,000; the position is marked at 120, so equity gains 2,000.
    assert summary["cash_delta"] == pytest.approx(-10000.0)
    assert summary["total_equity_delta"] == pytest.approx(2000.0)
    assert result.data["delta"]["total_equity"] == pytest.approx(2000.0)
    assert result.data["delta"]["market_value"] == pytest.approx(12000.0)


def test_buy_debits_the_existing_cash_key_even_when_stored_in_lowercase() -> None:
    # PORT's cash totals upper-case keys. A book stored as 'usd' must be debited
    # under that same key, not under a second 'USD' key that would replace its balance.
    _SEED["cash"] = {"usd": 25000.0}
    _run({"quantity": 100, "cost": 100})
    assert _CASH_SEEN[1] == {"usd": pytest.approx(15000.0)}


def test_book_without_cash_withholds_equity_change_with_a_warning() -> None:
    _SEED["cash"] = {}
    result = _run({"quantity": 100, "cost": 100})
    assert result.data["summary"].get("total_equity_delta") is None
    assert any("cash" in warning.lower() for warning in result.warnings)


def test_overdrawn_cash_is_reported() -> None:
    _SEED["cash"] = {"USD": 5000.0}
    result = _run({"quantity": 100, "cost": 100})
    assert result.data["summary"]["cash_delta"] == pytest.approx(-10000.0)
    assert any("cash would be -5,000.00" in warning for warning in result.warnings)


# ── PORT_WHATIF#4: lots merge and sells reduce the holding ───────────────────


def test_buy_into_held_symbol_merges_into_the_lot_at_weighted_cost() -> None:
    _SEED["positions"] = [_lot(NVDA, 40, 135.0)]
    _SEED["cash"] = {"USD": 10000.0}
    result = _run({"quantity": 10, "cost": 150}, instrument=NVDA)
    after = _SEEN[-1]
    assert len(after) == 1
    assert after[0].quantity == pytest.approx(50.0)
    assert after[0].avg_cost == pytest.approx((40 * 135.0 + 10 * 150.0) / 50)
    assert result.data["delta"]["n_positions"] == 0


def test_sell_reduces_the_held_lot_and_realizes_pnl() -> None:
    _SEED["positions"] = [_lot(NVDA, 40, 135.0)]
    _SEED["cash"] = {"USD": 10000.0}
    result = _run({"quantity": -10, "cost": 150}, instrument=NVDA)
    after = _SEEN[-1]
    assert len(after) == 1
    assert after[0].quantity == pytest.approx(30.0)
    assert after[0].avg_cost == pytest.approx(135.0)
    assert result.data["summary"]["realized_pnl_of_trade"] == pytest.approx(150.0)
    assert result.data["summary"]["cash_delta"] == pytest.approx(1500.0)
    assert result.data["delta"]["n_positions"] == 0


def test_sell_closing_a_lot_removes_the_position() -> None:
    _SEED["positions"] = [_lot(NVDA, 40, 135.0)]
    _SEED["cash"] = {"USD": 10000.0}
    result = _run({"quantity": -40, "cost": 150}, instrument=NVDA)
    assert _SEEN[-1] == []
    assert result.data["delta"]["n_positions"] == -1


def test_sell_more_than_held_is_refused_not_booked_as_a_short() -> None:
    _SEED["positions"] = [_lot(NVDA, 40, 135.0)]
    _SEED["cash"] = {"USD": 10000.0}
    result = _run({"quantity": -50, "cost": 150}, instrument=NVDA)
    assert result.data.get("status") == "input_error"
    assert "summary" not in result.data


def test_sell_with_nothing_held_is_refused() -> None:
    _SEED["cash"] = {"USD": 10000.0}
    result = _run({"quantity": -5, "cost": 120})
    assert result.data.get("status") == "input_error"
    assert "summary" not in result.data


# ── PORT_WHATIF#6: quotes are fetched once for both PORT runs ────────────────


def test_quotes_are_fetched_once_per_symbol_across_both_port_runs() -> None:
    _SEED["positions"] = [_lot(AAPL, 10, 100.0), _lot(NVDA, 5, 130.0)]
    _SEED["cash"] = {"USD": 50000.0}
    quotes = _CountingQuotes()
    result = _run({"quantity": 10, "cost": 120}, deps=FunctionDeps(yfinance=quotes))
    assert result.data["summary"]["quantity"] == pytest.approx(10.0)
    assert sorted(quotes.calls) == ["AAPL", "NVDA"]


# ── PORT_WHATIF#7: the function describes itself ─────────────────────────────


def test_function_declares_a_description() -> None:
    assert more_mod.PORTWhatIfFunction.description.strip()


# ── PORT_WHATIF#5: the manifest lists only what the handler ships ────────────


def test_manifest_inputs_match_the_shipped_trade_fields() -> None:
    entry = REGISTRY.get("PORT_WHATIF")
    names = {spec.name for spec in entry.inputs}
    assert {"quantity", "cost"} <= names
    assert names <= {"quantity", "cost", "paper_mode"}
    assert set(entry.defaults) <= {"paper_mode"}


def test_manifest_output_claims_match_the_handler_output() -> None:
    entry = REGISTRY.get("PORT_WHATIF")
    shipped = {"hypothetical_added", "before", "after", "delta", "summary", "rows", "methodology"}
    assert set(entry.output_contract.must_have) <= shipped
    card_keys = {slot.key for slot in entry.card_schema.slots}
    assert card_keys <= {"market_value_delta", "unrealized_pnl_delta", "total_equity_delta",
                         "cash_delta", "paper_mode"}
