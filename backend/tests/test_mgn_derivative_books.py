"""MGN#2/MGN#3 residual: non-crypto derivatives must keep the futures rule.

The first MGN#2 fix made every book whose classes are a subset of {CRYPTO, DERIVATIVE}
crypto_futures, so a pure ES book fell to the 10%-of-notional crypto rule (24x too low).
A DERIVATIVE is non-crypto futures/options (instrument.py), so it keeps the futures
per-contract rule unless it is a crypto perpetual inside a crypto_futures account.
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


def _es_line():
    return {"symbol": "ES", "asset_class": "DERIVATIVE", "quantity": 2, "avg_cost": 5000, "last": 5000}


def _btc_line():
    return {"symbol": "BTC-USD", "asset_class": "CRYPTO", "quantity": 0.5, "avg_cost": 95000, "last": 95000}


def test_infer_pure_derivative_book_is_futures_not_crypto_futures():
    assert me.infer_margin_type([{"asset_class": "DERIVATIVE"}]) == "futures"


def test_infer_crypto_and_derivative_book_is_crypto_futures():
    assert me.infer_margin_type([{"asset_class": "CRYPTO"}, {"asset_class": "DERIVATIVE"}]) == "crypto_futures"


def test_infer_pure_spot_crypto_is_crypto_spot():
    assert me.infer_margin_type([{"asset_class": "CRYPTO"}]) == "crypto_spot"


def test_pure_es_book_supplied_path_uses_futures_fixed_per_contract():
    """ES only: 2 contracts x 12,000 fixed initial = 24,000 (was 1,000 at 10% of notional)."""
    res = _run(MGNFunction(FunctionDeps()).execute(positions=[_es_line()]))
    account = res.data["accounts"][0]
    assert account["margin_type"] == "futures"
    assert account["initial_margin"] == pytest.approx(24000.0)


def test_pure_es_book_default_account_uses_futures_fixed_per_contract(monkeypatch):
    book = [PortfolioPosition(instrument=Instrument(symbol="ES", asset_class=AssetClass.DERIVATIVE),
                              quantity=2, avg_cost=5000)]

    class _State:
        def __init__(self, *a, **k):
            self.positions = book
            self.cash = {}

        def import_legacy_crypto(self):
            pass

    monkeypatch.setattr(me, "PortfolioState", _State)
    monkeypatch.setattr(me, "_save_config", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(me, "_load_config", lambda: {})
    result = me.calc_all_accounts(prices={"ES": 5000.0})
    account = result["accounts"][0]
    assert account["margin_type"] == "futures"
    assert account["initial_margin"] == pytest.approx(24000.0)


def test_es_in_mixed_crypto_book_keeps_futures_rate_and_spot_btc_stays_at_crypto_spot():
    """Mixed CRYPTO + ES book: BTC spot 47,500 at 100%; ES 24,000 at the futures rule."""
    res = _run(MGNFunction(FunctionDeps()).execute(positions=[_btc_line(), _es_line()]))
    account = res.data["accounts"][0]
    by_symbol = {p["symbol"]: p for p in account["positions"]}
    assert by_symbol["BTC-USD"]["initial_margin"] == pytest.approx(47500.0)
    assert by_symbol["ES"]["initial_margin"] == pytest.approx(24000.0)
    assert account["initial_margin"] == pytest.approx(71500.0)


def test_btc_perp_in_crypto_book_keeps_crypto_futures_rate():
    """A crypto perpetual (suffix -PERP/-SWAP) keeps the 10% crypto_futures rule."""
    perp = {"symbol": "BTC-PERP", "asset_class": "DERIVATIVE", "quantity": 0.1, "avg_cost": 95000, "last": 95000}
    res = _run(MGNFunction(FunctionDeps()).execute(positions=[_btc_line(), perp]))
    by_symbol = {p["symbol"]: p for p in res.data["accounts"][0]["positions"]}
    assert by_symbol["BTC-PERP"]["initial_margin"] == pytest.approx(950.0)


def test_explicit_crypto_futures_account_keeps_crypto_rule_for_derivative_lines():
    """A user-chosen crypto_futures account keeps its account rule (explicit choice)."""
    res = _run(MGNFunction(FunctionDeps()).execute(positions=[_es_line()], margin_type="crypto_futures"))
    assert res.data["accounts"][0]["initial_margin"] == pytest.approx(1000.0)
