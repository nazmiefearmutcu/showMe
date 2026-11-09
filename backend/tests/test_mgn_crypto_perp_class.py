"""MGN#2-RQ: a crypto perpetual held as an asset_class CRYPTO line keeps the 10% rule.

The real portfolio represents a perpetual the same way as spot crypto (asset_class
CRYPTO), so the derivative-only check in margin_engine never saw it: a BTC perp next
to spot BTC was margined at the 100% spot rate (10x overstatement). A perpetual is
recognised by its symbol suffix (-PERP / -SWAP / PERP / ccxt ':') whatever the class.
"""
from __future__ import annotations

import asyncio

import pytest

import showme.engine.services.margin_engine as me
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio.mgn import MGNFunction


def _run(coro):
    return asyncio.run(coro)


def _spot_btc():
    return {"symbol": "BTC-USD", "asset_class": "CRYPTO", "quantity": 0.5, "avg_cost": 95000, "last": 95000}


def _perp_as_crypto(symbol="BTCUSDT-PERP"):
    return {"symbol": symbol, "asset_class": "CRYPTO", "quantity": 0.1, "avg_cost": 95000, "last": 95000}


def test_crypto_class_perp_next_to_spot_keeps_crypto_futures_rate():
    res = _run(MGNFunction(FunctionDeps()).execute(positions=[_spot_btc(), _perp_as_crypto()]))
    account = res.data["accounts"][0]
    by_symbol = {p["symbol"]: p for p in account["positions"]}
    # Spot stays at the crypto_spot 100% rate; the perp (9,500 notional) keeps 10% -> 950.
    assert by_symbol["BTC-USD"]["initial_margin"] == pytest.approx(47500.0)
    assert by_symbol["BTCUSDT-PERP"]["initial_margin"] == pytest.approx(950.0)


def test_crypto_class_perp_only_book_is_crypto_futures_not_spot():
    res = _run(MGNFunction(FunctionDeps()).execute(positions=[_perp_as_crypto()]))
    account = res.data["accounts"][0]
    assert account["margin_type"] == "crypto_futures"
    assert account["initial_margin"] == pytest.approx(950.0)


def test_pure_spot_book_is_still_crypto_spot():
    assert me.infer_margin_type([_spot_btc()]) == "crypto_spot"


def test_infer_crypto_class_perp_with_spot_is_crypto_futures():
    assert me.infer_margin_type([_spot_btc(), _perp_as_crypto()]) == "crypto_futures"


def test_crypto_class_perp_in_default_account_uses_crypto_futures_rate(monkeypatch):
    from showme.engine.core.instrument import AssetClass, Instrument
    from showme.engine.portfolio.state import PortfolioPosition

    book = [
        PortfolioPosition(instrument=Instrument(symbol="BTC-USD", asset_class=AssetClass.CRYPTO),
                          quantity=0.5, avg_cost=95000),
        PortfolioPosition(instrument=Instrument(symbol="BTCUSDT-PERP", asset_class=AssetClass.CRYPTO),
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
    result = me.calc_all_accounts(prices={"BTC-USD": 95000.0, "BTCUSDT-PERP": 95000.0})
    by_symbol = {p["symbol"]: p for p in result["accounts"][0]["positions"]}
    assert by_symbol["BTC-USD"]["initial_margin"] == pytest.approx(47500.0)
    assert by_symbol["BTCUSDT-PERP"]["initial_margin"] == pytest.approx(950.0)
