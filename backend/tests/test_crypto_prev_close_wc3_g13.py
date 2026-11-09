"""ASOF-9: a crypto 24h baseline must not be labelled as a prior close.

CoinGecko ``price_change_percentage_24h`` is measured against the price 24 hours
ago, not a prior session close (crypto trades 24/7). The DES mapper therefore
must not publish that derived price as ``previousClose``. It is exposed as
``price_24h_ago`` with ``change_basis = 24h_rolling``.

Network is not used: the mapper is called on a recorded-shape CoinGecko payload.
"""
from __future__ import annotations

import pytest

from showme.engine.functions.equity.des import _coingecko_to_des, _des_field_dictionary


def _btc_payload() -> dict:
    return {
        "id": "bitcoin",
        "symbol": "btc",
        "name": "Bitcoin",
        "market_cap_rank": 1,
        "market_data": {
            "current_price": {"usd": 92_345.0},
            "market_cap": {"usd": 1_800_000_000_000},
            "high_24h": {"usd": 93_500.0},
            "low_24h": {"usd": 91_000.0},
            "price_change_percentage_24h": 1.25,
            "ath": {"usd": 109_000.0},
            "atl": {"usd": 67.81},
        },
    }


def test_crypto_24h_baseline_is_not_published_as_previous_close() -> None:
    out = _coingecko_to_des(_btc_payload(), "BTCUSDT")
    # Red before the fix: previousClose was the 24h-ago price (92345 / 1.0125).
    assert out["previousClose"] is None
    assert out["previousClose"] != pytest.approx(92_345.0 / 1.0125)


def test_crypto_24h_baseline_is_exposed_under_its_true_name() -> None:
    out = _coingecko_to_des(_btc_payload(), "BTCUSDT")
    assert out["price_24h_ago"] == pytest.approx(92_345.0 / 1.0125)
    assert out["change_basis"] == "24h_rolling"
    assert out["change_24h"] == pytest.approx(92_345.0 - 92_345.0 / 1.0125)


def test_crypto_change_percent_stays_coingecko_own_24h_value() -> None:
    out = _coingecko_to_des(_btc_payload(), "BTCUSDT")
    assert out["regularMarketChangePercent"] == pytest.approx(1.25)


def test_crypto_without_24h_change_has_no_invented_baseline() -> None:
    payload = _btc_payload()
    payload["market_data"]["price_change_percentage_24h"] = None
    out = _coingecko_to_des(payload, "BTCUSDT")
    assert out["price_24h_ago"] is None
    assert out["change_24h"] is None
    assert out["previousClose"] is None


def test_field_dictionary_documents_the_24h_fields() -> None:
    dictionary = _des_field_dictionary()
    assert "24h" in dictionary["price_24h_ago"]
    assert "crypto" in dictionary["previousClose"].lower()
    assert "null" in dictionary["previousClose"].lower() or "none" in dictionary["previousClose"].lower()
