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
    assert is_crypto_symbol("SUSDT")
    assert is_crypto_symbol("4USDT")
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


def test_fetch_crypto_quote_falls_back_to_binance_futures(monkeypatch) -> None:
    def fake_get(url: str, *_args, **_kwargs) -> FakeResponse:
        if "fapi.binance.com" in url:
            return FakeResponse({
                "symbol": "4USDT",
                "lastPrice": "0.01231",
                "openPrice": "0.013024",
                "priceChangePercent": "-5.482",
                "volume": "518439928",
                "quoteVolume": "6481387.8610410",
                "highPrice": "0.013279",
                "lowPrice": "0.011518",
            })
        return FakeResponse({"code": -1121, "msg": "Invalid symbol."})

    monkeypatch.setattr("showme.quotes.requests.get", fake_get)

    out = fetch_crypto_quote_sync("4USDT")

    assert out["symbol"] == "4USDT"
    assert out["last"] == 0.01231
    assert out["change_pct"] == -5.482
    assert out["source"] == "binance_futures"
    assert out["raw"]["venue"] == "usdm_futures"


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
