"""MGN#2-RQ: a crypto perpetual is recognised by its product marker, not only by a symbol suffix.

The registry resolves a bare crypto pair (BTCUSDT, BTC) to a CRYPTO instrument. A bare pair
does not say whether it is spot or a perpetual, so the registry must not claim PERPETUAL. A
perpetual that the book does know about carries contract_type PERPETUAL on its position and is
priced at the crypto_futures rate next to spot BTC, under the real representation (no suffix).
"""
from __future__ import annotations

import asyncio

import pytest

import showme.engine.portfolio.state as state_mod
import showme.engine.services.margin_engine as me
from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio.mgn import MGNFunction
from showme.engine.portfolio.state import PortfolioPosition
from showme.engine.reference.symbol_registry import SymbolRegistry


def _run(coro):
    return asyncio.run(coro)


def _spot_btc():
    return {"symbol": "BTC-USD", "asset_class": "CRYPTO", "quantity": 0.5, "avg_cost": 95000, "last": 95000}


def _marked_perp(symbol="BTCUSDT"):
    return {"symbol": symbol, "asset_class": "CRYPTO", "contract_type": "PERPETUAL",
            "quantity": 0.1, "avg_cost": 95000, "last": 95000}


def test_registry_does_not_claim_perpetual_for_a_bare_crypto_pair(tmp_path):
    reg = SymbolRegistry(cache_path=tmp_path / "symbols.sqlite")
    for key in ("BTCUSDT", "BTC"):
        inst = reg.resolve_sync(key)
        assert inst is not None and inst.asset_class is AssetClass.CRYPTO
        assert "contract_type" not in inst.metadata, inst.metadata


def test_supplied_perpetual_marker_next_to_spot_keeps_crypto_futures_rate():
    res = _run(MGNFunction(FunctionDeps()).execute(positions=[_spot_btc(), _marked_perp()]))
    by_symbol = {p["symbol"]: p for p in res.data["accounts"][0]["positions"]}
    assert by_symbol["BTC-USD"]["initial_margin"] == pytest.approx(47500.0)
    assert by_symbol["BTCUSDT"]["initial_margin"] == pytest.approx(950.0)


def test_supplied_perpetual_marker_makes_book_crypto_futures():
    assert me.infer_margin_type([_spot_btc(), _marked_perp()]) == "crypto_futures"


def test_unmarked_crypto_pair_is_not_assumed_perpetual():
    """Without a marker a bare pair is spot: no suffix and no PERPETUAL claim, so no 10% rate."""
    plain = {"symbol": "BTCUSDT", "asset_class": "CRYPTO", "quantity": 0.1, "avg_cost": 95000, "last": 95000}
    assert me.infer_margin_type([_spot_btc(), plain]) == "crypto_spot"
    res = _run(MGNFunction(FunctionDeps()).execute(positions=[_spot_btc(), plain]))
    by_symbol = {p["symbol"]: p for p in res.data["accounts"][0]["positions"]}
    assert by_symbol["BTCUSDT"]["initial_margin"] == pytest.approx(9500.0)


def test_portfolio_position_perpetual_marker_is_honored(monkeypatch):
    book = [
        PortfolioPosition(instrument=Instrument(symbol="BTC-USD", asset_class=AssetClass.CRYPTO),
                          quantity=0.5, avg_cost=95000),
        PortfolioPosition(instrument=Instrument.crypto(
            symbol="BTCUSDT", metadata={"contract_type": "PERPETUAL"}),
            quantity=0.1, avg_cost=95000),
    ]

    class _State:
        def __init__(self, *a, **k):
            self.positions = book
            self.cash = {}

        def import_legacy_crypto(self):
            pass

    monkeypatch.setattr(state_mod, "PortfolioState", _State)
    monkeypatch.setattr(me, "PortfolioState", _State)
    monkeypatch.setattr(me, "_save_config", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(me, "_load_config", lambda: {})
    result = me.calc_all_accounts(prices={"BTC-USD": 95000.0, "BTCUSDT": 95000.0})
    by_symbol = {p["symbol"]: p for p in result["accounts"][0]["positions"]}
    assert result["accounts"][0]["margin_type"] == "crypto_futures"
    assert by_symbol["BTC-USD"]["initial_margin"] == pytest.approx(47500.0)
    assert by_symbol["BTCUSDT"]["initial_margin"] == pytest.approx(950.0)
