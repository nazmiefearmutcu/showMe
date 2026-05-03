"""Quote snapshot normalization."""
from __future__ import annotations

from showme.quotes import (
    fetch_crypto_quote_sync,
    fetch_equity_quote_sync,
    is_crypto_symbol,
    split_crypto_symbol,
)


class FakeResponse:
    def __init__(self, payload: object, text: str = "") -> None:
        self._payload = payload
        self.text = text

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


def test_crypto_symbol_detection_and_split() -> None:
    assert is_crypto_symbol("BTCUSDT")
    assert is_crypto_symbol("ETH-USD")
    assert split_crypto_symbol("BTCUSDT") == ("BTC", "USDT")
    assert not is_crypto_symbol("AAPL")


def test_fetch_crypto_quote_uses_binance_payload(monkeypatch) -> None:
    def fake_get(*_args, **_kwargs) -> FakeResponse:
        return FakeResponse({
            "symbol": "BTCUSDT",
            "lastPrice": "60000.50",
            "openPrice": "59000.00",
            "priceChangePercent": "1.695",
            "volume": "12345",
            "bidPrice": "60000.00",
            "askPrice": "60001.00",
        })

    monkeypatch.setattr("showme.quotes.requests.get", fake_get)

    out = fetch_crypto_quote_sync("BTCUSDT")

    assert out["symbol"] == "BTCUSDT"
    assert out["last"] == 60000.50
    assert out["previous_close"] == 59000.00
    assert out["change_pct"] == 1.695
    assert out["source"] == "binance"


def test_fetch_equity_quote_uses_yahoo_chart_payload(monkeypatch) -> None:
    def fake_get(*_args, **_kwargs) -> FakeResponse:
        return FakeResponse({
            "chart": {
                "result": [{
                    "meta": {
                        "regularMarketPrice": 200.0,
                        "previousClose": 195.0,
                        "regularMarketVolume": 10_000_000,
                        "currency": "USD",
                    },
                    "indicators": {"quote": [{"close": [190.0, 195.0, 200.0]}]},
                }],
            },
        })

    monkeypatch.setattr("showme.quotes.requests.get", fake_get)

    out = fetch_equity_quote_sync("AAPL")

    assert out["symbol"] == "AAPL"
    assert out["last"] == 200.0
    assert out["previous_close"] == 195.0
    assert out["change_pct"] == (200.0 / 195.0 - 1.0) * 100
    assert out["source"] == "yahoo_chart"
