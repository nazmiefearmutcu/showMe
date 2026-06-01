"""Degarbage regression tests for screen/micro.py (MICRO).

MICRO must surface a REAL Binance spot L2 order-book snapshot for crypto
(bids/asks/spread_bps/microprice/imbalance/data_mode/as_of) and an honest,
non-synthetic explicit_unavailable payload for non-crypto asset classes.

Live-network assertions are guarded: if Binance is unreachable the test
asserts the graceful provider_unavailable shape instead.
"""
from __future__ import annotations

import socket

import pytest

from showme.engine.core.instrument import AssetClass, Instrument


def _network_ok(host: str = "api.binance.com", port: int = 443, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _make_handler():
    from showme.engine.functions.screen.micro import MICROFunction

    return MICROFunction(deps=None)


_MUST_HAVE = {"as_of", "symbol", "bids", "asks", "spread_bps", "microprice", "data_mode"}


@pytest.mark.asyncio
async def test_micro_crypto_returns_real_l2_or_graceful_unavailable():
    handler = _make_handler()
    instrument = Instrument(symbol="BTCUSDT", asset_class=AssetClass.CRYPTO)
    result = await handler.execute(instrument=instrument, depth_levels=20)
    data = result.data

    assert result.code == "MICRO"
    assert result.sources == ["binance"]
    assert _MUST_HAVE.issubset(data.keys())
    assert "status" in data
    assert isinstance(data.get("methodology"), str) and data["methodology"]
    assert isinstance(data.get("field_dictionary"), dict) and data["field_dictionary"]
    assert isinstance(data.get("rows"), list)

    if data["status"] == "ok":
        # Real live L2 ladder — not the old hardcoded/futures payload.
        assert data["data_mode"] == "live_exchange"
        bids = data["bids"]
        asks = data["asks"]
        assert len(bids) == 20
        assert len(asks) == 20
        # Real values: bids strictly decreasing, asks strictly increasing.
        bid_prices = [b["price"] for b in bids]
        ask_prices = [a["price"] for a in asks]
        assert all(bid_prices[i] > bid_prices[i + 1] for i in range(len(bid_prices) - 1))
        assert all(ask_prices[i] < ask_prices[i + 1] for i in range(len(ask_prices) - 1))
        # spread_bps positive and matches the documented formula.
        best_bid = bids[0]["price"]
        best_ask = asks[0]["price"]
        mid = (best_bid + best_ask) / 2
        expected = (best_ask - best_bid) / mid * 10_000
        assert data["spread_bps"] > 0
        assert abs(data["spread_bps"] - expected) < 1e-6
        # microprice sits between best bid and best ask.
        assert best_bid <= data["microprice"] <= best_ask
        assert -1.0 <= data["imbalance"] <= 1.0
        # rows are real ladder entries.
        assert all("cum_size" in r and "notional" in r for r in data["rows"])
    else:
        # Genuine outage -> honest empty ladder, never synthetic.
        assert data["status"] == "provider_unavailable"
        assert data["data_mode"] == "provider_unavailable"
        assert data["bids"] == []
        assert data["asks"] == []
        assert data.get("next_actions")


@pytest.mark.asyncio
async def test_micro_equity_is_explicit_unavailable_not_synthetic():
    handler = _make_handler()
    instrument = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    result = await handler.execute(instrument=instrument)
    data = result.data

    # No L2 provider for equities -> explicit_unavailable, empty ladder.
    assert data["data_mode"] == "explicit_unavailable"
    assert data["bids"] == []
    assert data["asks"] == []
    assert data.get("spread_bps") is None
    assert data.get("microprice") is None
    assert _MUST_HAVE.issubset(data.keys())
    assert isinstance(data.get("methodology"), str) and data["methodology"]
    # next_action points to the QUOTE/GP pane.
    actions_text = " ".join(
        a.get("label", "") if isinstance(a, dict) else str(a) for a in data.get("next_actions", [])
    ).lower()
    assert "gp" in actions_text or "quote" in actions_text


@pytest.mark.asyncio
async def test_micro_no_instrument_is_graceful():
    handler = _make_handler()
    result = await handler.execute(instrument=None)
    data = result.data
    assert _MUST_HAVE.issubset(data.keys())
    assert data["bids"] == []
    assert data["asks"] == []
    assert isinstance(data.get("methodology"), str) and data["methodology"]


@pytest.mark.asyncio
async def test_micro_offline_shape_is_coherent():
    """Shape contract holds regardless of network state."""
    handler = _make_handler()
    instrument = Instrument(symbol="BTCUSDT", asset_class=AssetClass.CRYPTO)
    result = await handler.execute(instrument=instrument, depth_levels=10)
    assert isinstance(result.data, dict)
    assert result.code == "MICRO"
    assert result.data["status"] in {"ok", "empty", "provider_unavailable"}
    if not _network_ok():
        # Offline: must be the graceful provider_unavailable shape, no synthetic fields.
        assert result.data["status"] == "provider_unavailable"
        assert result.data["bids"] == []
        assert result.data["asks"] == []
