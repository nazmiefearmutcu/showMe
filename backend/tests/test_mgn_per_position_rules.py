"""MGN margins each position under its own asset-class rule (MGN#2, MGN#3).

Before the fix one CRYPTO line flipped the whole account to crypto_futures (10%
initial on equities too), and auto-created accounts were reg_t, so spot BTC was
margined at 50% instead of the module's own crypto_spot rule (100%).
"""
from __future__ import annotations

import asyncio

import pytest

import showme.engine.services.margin_engine as me
from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio.mgn import MGNFunction
from showme.engine.portfolio.state import PortfolioPosition


def _run(coro):
    return asyncio.run(coro)


def _positions_by_symbol(account):
    return {p["symbol"]: p for p in account["positions"]}


def test_crypto_line_does_not_reprice_equity_in_same_account():
    """MGN#2: AAPL must stay at reg_t 50% when the book also holds BTC."""
    positions = [
        {"symbol": "AAPL", "asset_class": "EQUITY", "quantity": 50, "avg_cost": 180, "last": 180},
        {"symbol": "BTC-USD", "asset_class": "CRYPTO", "quantity": 0.5, "avg_cost": 95000, "last": 95000},
    ]
    res = _run(MGNFunction(FunctionDeps()).execute(positions=positions))
    account = res.data["accounts"][0]
    assert account["margin_type"] != "crypto_futures"
    aapl = _positions_by_symbol(account)["AAPL"]
    # 50 * 180 = 9,000 notional; reg_t initial long is 50% -> 4,500 (was 900 at 10%).
    assert aapl["initial_margin"] == pytest.approx(4500.0)


def test_spot_btc_is_margined_at_crypto_spot_rate_in_default_account(monkeypatch):
    """MGN#3: an auto-created account holding only spot BTC uses crypto_spot 100%."""
    book = [
        PortfolioPosition(instrument=Instrument(symbol="BTC-USD", asset_class=AssetClass.CRYPTO),
                          quantity=0.5, avg_cost=95000),
    ]

    class _State:
        def __init__(self, *a, **k):
            self.positions = book
            self.cash = {}

        def import_legacy_crypto(self):
            pass

    monkeypatch.setattr(me, "PortfolioState", _State)
    monkeypatch.setattr(me, "_save_config", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(me, "_load_config", lambda: {})
    result = me.calc_all_accounts(prices={"BTC-USD": 95000.0})
    account = result["accounts"][0]
    # notional 47,500; crypto_spot initial 100% -> 47,500 (reg_t gave 23,750).
    assert account["initial_margin"] == pytest.approx(47500.0)


def test_spot_btc_in_reg_t_supplied_account_is_not_half_margined():
    """MGN#3 on the supplied-positions path with an explicit reg_t account type."""
    positions = [{"symbol": "BTC-USD", "asset_class": "CRYPTO", "quantity": 0.5,
                  "avg_cost": 95000, "last": 95000}]
    res = _run(MGNFunction(FunctionDeps()).execute(positions=positions, margin_type="reg_t"))
    account = res.data["accounts"][0]
    assert account["initial_margin"] == pytest.approx(47500.0)


def test_buying_power_for_pure_spot_crypto_uses_crypto_spot_rate():
    """Buying power divides excess equity by the rate that actually applies (100%, not 50%)."""
    positions = [{"symbol": "BTC-USD", "asset_class": "CRYPTO", "quantity": 0.5,
                  "avg_cost": 95000, "last": 95000}]
    res = _run(MGNFunction(FunctionDeps()).execute(positions=positions, cash=10000))
    account = res.data["accounts"][0]
    # equity 57,500, IM 47,500 -> excess 10,000 at 100% -> buying power 10,000.
    assert account["buying_power"] == pytest.approx(10000.0)
