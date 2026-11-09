"""MGN#6: model constants are named, the buying-power rate has no hidden floor, calc is read-only."""
from __future__ import annotations

import pytest

import showme.engine.services.margin_engine as me
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.portfolio.state import PortfolioPosition


def test_fx_buying_power_uses_the_real_2_percent_rate_not_a_5_percent_floor():
    """Equity 10,000 with FX at 2% initial: surplus 8,000 / 0.02 = 400,000 (a 5% floor gave 160,000)."""
    pos = [{"symbol": "EURUSD", "asset_class": "FX", "quantity": 100000, "avg_cost": 1.0, "last": 1.0}]
    # equity = cash + market value = -90,000 + 100,000 = 10,000 ; initial = 100,000 * 2% = 2,000
    cfg = {"accounts": {"fx": {"margin_type": "fx", "cash": -90000.0, "currency": "USD", "overrides": {}}}}
    acct = me.calc_account("fx", pos, cfg=cfg)
    assert acct["equity"] == pytest.approx(10000.0)
    assert acct["initial_margin"] == pytest.approx(2000.0)
    assert acct["buying_power"] == pytest.approx((10000.0 - 2000.0) / 0.02)


def test_portfolio_multipliers_are_named_module_constants():
    assert me.PORTFOLIO_MAINTENANCE_SCALE == pytest.approx(0.6)
    assert me.PORTFOLIO_BUYING_POWER_MULTIPLE == pytest.approx(4.0)


def test_portfolio_account_buying_power_uses_named_multiple():
    pos = [{"symbol": "SPY", "asset_class": "ETF", "quantity": 10, "avg_cost": 100, "last": 100}]
    cfg = {"accounts": {"p": {"margin_type": "portfolio", "cash": 0.0, "currency": "USD", "overrides": {}}}}
    acct = me.calc_account("p", pos, cfg=cfg)
    assert acct["buying_power"] == pytest.approx(max(acct["equity"] - acct["initial_margin"], 0)
                                                 * me.PORTFOLIO_BUYING_POWER_MULTIPLE)


def test_calc_all_accounts_does_not_write_margin_config(monkeypatch):
    writes: list[dict] = []
    book = [PortfolioPosition(instrument=Instrument(symbol="BTC-USD", asset_class=AssetClass.CRYPTO),
                              quantity=0.5, avg_cost=95000)]

    class _State:
        def __init__(self, *a, **k):
            self.positions = book
            self.cash = {}

        def import_legacy_crypto(self):
            pass

    monkeypatch.setattr(me, "PortfolioState", _State)
    monkeypatch.setattr(me, "_save_config", lambda cfg: writes.append(cfg))
    monkeypatch.setattr(me, "_load_config", lambda: {})
    result = me.calc_all_accounts(prices={"BTC-USD": 95000.0})
    assert writes == []
    assert result["accounts"][0]["margin_type"] == "crypto_spot"
