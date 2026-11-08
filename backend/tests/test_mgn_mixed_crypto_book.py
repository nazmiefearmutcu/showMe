"""MGN#2/MGN#3 residual: spot BTC held alongside a BTC perpetual (DERIVATIVE).

The account-level type inferred for a CRYPTO + DERIVATIVE book is crypto_futures,
but the spot BTC line must still be margined at the module's crypto_spot rule
(100% initial), not at the 10% perp rate. Only an account the user explicitly set to
crypto_futures keeps its crypto rule for CRYPTO lines.
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


def _book():
    return [
        {"symbol": "BTC-USD", "asset_class": "CRYPTO", "quantity": 0.5, "avg_cost": 95000, "last": 95000},
        {"symbol": "BTC-PERP", "asset_class": "DERIVATIVE", "quantity": 0.1, "avg_cost": 95000, "last": 95000},
    ]


def test_spot_btc_with_btc_perp_is_margined_at_crypto_spot_rate_supplied_path():
    res = _run(MGNFunction(FunctionDeps()).execute(positions=_book()))
    account = res.data["accounts"][0]
    by_symbol = {p["symbol"]: p for p in account["positions"]}
    # Spot BTC notional 47,500 at crypto_spot 100% -> 47,500 (not 4,750 at 10%).
    assert by_symbol["BTC-USD"]["initial_margin"] == pytest.approx(47500.0)
    # Perp notional 9,500 keeps the crypto_futures 10% rate -> 950.
    assert by_symbol["BTC-PERP"]["initial_margin"] == pytest.approx(950.0)


def test_spot_btc_with_btc_perp_is_margined_at_crypto_spot_rate_default_account(monkeypatch):
    book = [
        PortfolioPosition(instrument=Instrument(symbol="BTC-USD", asset_class=AssetClass.CRYPTO),
                          quantity=0.5, avg_cost=95000),
        PortfolioPosition(instrument=Instrument(symbol="BTC-PERP", asset_class=AssetClass.DERIVATIVE),
                          quantity=0.1, avg_cost=95000),
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
    result = me.calc_all_accounts(prices={"BTC-USD": 95000.0, "BTC-PERP": 95000.0})
    by_symbol = {p["symbol"]: p for p in result["accounts"][0]["positions"]}
    assert by_symbol["BTC-USD"]["initial_margin"] == pytest.approx(47500.0)
    assert by_symbol["BTC-PERP"]["initial_margin"] == pytest.approx(950.0)


def test_explicit_crypto_futures_account_keeps_crypto_rule_for_crypto_lines():
    """The user-chosen crypto_futures account keeps its 10% rule for CRYPTO lines."""
    spot = [{"symbol": "BTC-USD", "asset_class": "CRYPTO", "quantity": 0.5,
             "avg_cost": 95000, "last": 95000}]
    res = _run(MGNFunction(FunctionDeps()).execute(positions=spot, margin_type="crypto_futures"))
    account = res.data["accounts"][0]
    assert account["initial_margin"] == pytest.approx(4750.0)


def test_inferred_margin_type_is_refreshed_when_book_changes(monkeypatch):
    """An auto-created account follows the current book, not its first inferred type."""
    import copy

    stored: dict = {}

    def _load():
        return copy.deepcopy(stored)

    def _save(cfg):
        stored.clear()
        stored.update(copy.deepcopy(cfg))

    book = [
        PortfolioPosition(instrument=Instrument(symbol="BTC-USD", asset_class=AssetClass.CRYPTO),
                          quantity=0.5, avg_cost=95000),
        PortfolioPosition(instrument=Instrument(symbol="BTC-PERP", asset_class=AssetClass.DERIVATIVE),
                          quantity=0.1, avg_cost=95000),
    ]

    class _State:
        def __init__(self, *a, **k):
            self.positions = book
            self.cash = {}

        def import_legacy_crypto(self):
            pass

    monkeypatch.setattr(me, "PortfolioState", _State)
    monkeypatch.setattr(me, "_save_config", _save)
    monkeypatch.setattr(me, "_load_config", _load)
    # MGN#6: a calculation is read-only, so the inferred type is read from the returned result.
    res = me.calc_all_accounts(prices={"BTC-USD": 95000.0, "BTC-PERP": 95000.0})
    assert res["accounts"][0]["margin_type"] == "crypto_futures"
    # The perp is closed: the book is now spot BTC only.
    book.pop()
    res = me.calc_all_accounts(prices={"BTC-USD": 95000.0})
    assert res["accounts"][0]["margin_type"] == "crypto_spot"
    assert stored == {}
