"""MGN#2-RQ residual: a non-crypto DERIVATIVE line never takes the crypto_futures 10% rate.

An account stored before the ``inferred`` flag existed (or one the user set to
crypto_futures explicitly) has no way to say its type was inferred. Its ES / options
(DERIVATIVE, non-perpetual) lines must still take the futures per-contract rule, because
a 10%-of-notional crypto rate is not a rule for an index future. Crypto perpetuals in the
same account keep the crypto_futures rate.
"""
from __future__ import annotations

import pytest

import showme.engine.services.margin_engine as me


def _es(qty: float = 2) -> dict:
    return {"symbol": "ES", "asset_class": "DERIVATIVE", "quantity": qty, "avg_cost": 5000, "last": 5000}


def _perp(qty: float = 0.1) -> dict:
    return {"symbol": "BTC-PERP", "asset_class": "CRYPTO", "quantity": qty, "avg_cost": 95000, "last": 95000}


def _legacy_cfg(margin_type: str = "crypto_futures") -> dict:
    # Shape written before the inferred flag: no "inferred" key.
    return {"accounts": {"main": {"margin_type": margin_type, "cash": 0.0,
                                   "currency": "USD", "overrides": {}}}}


def _by_symbol(account: dict) -> dict:
    return {p["symbol"]: p for p in account["positions"]}


def test_legacy_crypto_futures_account_prices_es_at_futures_per_contract_rule():
    account = me.calc_account("main", [_es()], cfg=_legacy_cfg())
    assert account["initial_margin"] == pytest.approx(24000.0)


def test_legacy_crypto_futures_account_keeps_perp_at_crypto_futures_rate_next_to_es():
    account = me.calc_account("main", [_es(), _perp()], cfg=_legacy_cfg())
    by_symbol = _by_symbol(account)
    assert by_symbol["ES"]["initial_margin"] == pytest.approx(24000.0)
    assert by_symbol["BTC-PERP"]["initial_margin"] == pytest.approx(950.0)


def test_explicit_crypto_futures_account_prices_es_at_futures_per_contract_rule():
    cfg = {"accounts": {"main": {"margin_type": "crypto_futures", "cash": 0.0, "currency": "USD",
                                  "overrides": {}, "inferred": False}}}
    account = me.calc_account("main", [_es()], cfg=cfg)
    assert account["initial_margin"] == pytest.approx(24000.0)
