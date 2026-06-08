"""DES function — promotion of yfinance ``info`` fields and contract shape."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from showme.engine.core.base_function import FunctionDeps, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.core.refdata import ReferenceData
from showme.engine.functions.equity.des import (
    DESFunction,
    _coingecko_to_des,
    _epoch_to_iso,
    _normalize_dividend_yield,
    _promote_raw_fields,
)


def _instrument() -> Instrument:
    return Instrument(
        symbol="AAPL",
        asset_class=AssetClass.EQUITY,
        exchange="NMS",
        currency="USD",
        name="Apple Inc.",
    )


class _FakeYFinance:
    """Mocks the BaseDataSource interface used by ``DESFunction``."""

    def __init__(self, payload: Any) -> None:
        self._payload = payload
        self.calls = 0

    async def fetch(self, request: Any) -> Any:  # noqa: D401
        self.calls += 1
        return self._payload


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ── unit helpers ──────────────────────────────────────────────────────────


def test_normalize_dividend_yield_decimal_stays_decimal() -> None:
    assert _normalize_dividend_yield(0.0123) == pytest.approx(0.0123)


def test_normalize_dividend_yield_percent_form_collapses() -> None:
    # yfinance occasionally returns percent (1.23). Make sure we re-encode
    # as a decimal so the UI's `*100` math stays correct (1.23%, not 123%).
    assert _normalize_dividend_yield(1.23) == pytest.approx(0.0123)


def test_normalize_dividend_yield_sub_one_percent_form() -> None:
    # Newer yfinance ships dividendYield in percent form for AAPL-like names
    # (0.36 means 0.36%). The naive ``> 1.0`` threshold would leave it
    # alone and the UI would render 36%. Make sure the 0.2 threshold kicks
    # in and converts to the decimal 0.0036.
    assert _normalize_dividend_yield(0.36) == pytest.approx(0.0036)


def test_normalize_dividend_yield_handles_garbage() -> None:
    assert _normalize_dividend_yield(None) is None
    assert _normalize_dividend_yield("") is None
    assert _normalize_dividend_yield("nope") is None
    assert _normalize_dividend_yield(-0.4) is None


def test_epoch_to_iso_converts_first_trade_date() -> None:
    # 1980-12-12 was AAPL's first trade.
    iso = _epoch_to_iso(345427200)
    assert iso == "1980-12-12"


def test_epoch_to_iso_handles_milliseconds_from_newer_yfinance() -> None:
    # yfinance switched ``firstTradeDateEpochUtc`` (seconds) to
    # ``firstTradeDateMilliseconds`` (ms) circa 2026-Q1. The helper must
    # accept either magnitude.
    iso = _epoch_to_iso(345479400_000)
    assert iso == "1980-12-12"


def test_epoch_to_iso_rejects_zero_and_negative() -> None:
    assert _epoch_to_iso(0) is None
    assert _epoch_to_iso(-5) is None
    assert _epoch_to_iso("garbage") is None


def test_promote_raw_fields_flattens_yfinance_info_onto_data() -> None:
    data: dict[str, Any] = {"symbol": "AAPL"}
    raw = {
        "regularMarketPrice": 282.62,
        "previousClose": 271.30,
        "trailingPE": 30.5,
        "forwardPE": 28.1,
        "beta": 1.24,
        "trailingAnnualDividendYield": 0.0050,
        "dividendYield": 0.50,  # newer yfinance percent form
        "fiftyTwoWeekHigh": 290.5,
        "fiftyTwoWeekLow": 165.0,
        "marketCap": 4_200_000_000_000,
        "fullTimeEmployees": 161_000,
        "firstTradeDateEpochUtc": 345427200,
        "longBusinessSummary": "Apple Inc. designs and sells smartphones.",
    }

    _promote_raw_fields(data, raw)

    assert data["regularMarketPrice"] == 282.62
    assert data["previousClose"] == 271.30
    assert data["trailingPE"] == 30.5
    assert data["forwardPE"] == 28.1
    assert data["beta"] == 1.24
    assert data["dividendYield"] == pytest.approx(0.005)
    assert data["fiftyTwoWeekHigh"] == 290.5
    assert data["fiftyTwoWeekLow"] == 165.0
    assert data["market_cap"] == 4_200_000_000_000
    assert data["employees"] == 161_000
    assert data["ipo_date"] == "1980-12-12"
    assert data["description"].startswith("Apple")
    # Change percent derived from last vs previousClose when missing.
    assert data["regularMarketChangePercent"] == pytest.approx(
        (282.62 / 271.30 - 1.0) * 100.0
    )


def test_promote_raw_fields_does_not_overwrite_existing_values() -> None:
    data: dict[str, Any] = {
        "trailingPE": 25.0,
        "description": "User-supplied description.",
    }
    _promote_raw_fields(
        data, {"trailingPE": 99.0, "longBusinessSummary": "raw summary"}
    )
    assert data["trailingPE"] == 25.0
    assert data["description"] == "User-supplied description."


# ── full function flow ────────────────────────────────────────────────────


def test_des_execute_flattens_reference_data_extras_raw() -> None:
    fn = DESFunction()
    raw_info = {
        "trailingPE": 30.5,
        "forwardPE": 28.1,
        "beta": 1.24,
        "dividendYield": 0.0050,
        "fiftyTwoWeekHigh": 290.5,
        "fiftyTwoWeekLow": 165.0,
        "regularMarketPrice": 282.62,
        "previousClose": 271.30,
        "marketCap": 4_200_000_000_000,
        "fullTimeEmployees": 161_000,
        "shortName": "Apple",
        "longName": "Apple Inc.",
    }
    rd = ReferenceData(
        symbol="AAPL",
        name="Apple Inc.",
        asset_class="EQUITY",
        exchange="NMS",
        currency="USD",
        country="United States",
        sector="Technology",
        industry="Consumer Electronics",
        market_cap=4_200_000_000_000,
        employees=161_000,
        website="https://apple.com",
        description="Apple Inc. designs and sells smartphones.",
        source="yfinance",
        extras={"raw": raw_info},
    )
    fn.deps = FunctionDeps(yfinance=_FakeYFinance(rd))

    result = _run(fn.execute(_instrument()))
    assert isinstance(result, FunctionResult)
    data = result.data
    assert data["symbol"] == "AAPL"
    assert data["trailingPE"] == 30.5
    assert data["forwardPE"] == 28.1
    assert data["beta"] == 1.24
    assert data["dividendYield"] == pytest.approx(0.005)
    assert data["fiftyTwoWeekHigh"] == 290.5
    assert data["fiftyTwoWeekLow"] == 165.0
    assert data["regularMarketPrice"] == 282.62
    assert data["previousClose"] == 271.30
    assert data["regularMarketChangePercent"] == pytest.approx(
        (282.62 / 271.30 - 1.0) * 100.0
    )
    # Rows are always populated.
    assert isinstance(data["rows"], list) and len(data["rows"]) >= 6
    fields = {row["field"] for row in data["rows"]}
    assert {"Name", "Sector", "Industry", "Market cap", "Employees"}.issubset(fields)
    # Methodology + field dictionary are wired.
    assert "methodology" in data
    assert "trailingPE" in data["field_dictionary"]
    # Heavy raw blob is stripped from the wire payload.
    extras = data.get("extras")
    assert extras is None or "raw" not in extras
    # Exchange code expands to the human-readable name.
    assert data["exchange_name"]
    assert result.sources == ["yfinance"]


def test_des_execute_dict_branch_builds_rows() -> None:
    fn = DESFunction()
    finnhub_payload = {
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "market_cap": 4_100_000_000_000,
        "employees": 158_000,
        "exchange": "NMS",
        "country": "United States",
        "currency": "USD",
        "website": "https://apple.com",
        "description": "Designs and sells smartphones.",
    }
    fn.deps = FunctionDeps(yfinance=_FakeYFinance(finnhub_payload))

    result = _run(fn.execute(_instrument()))
    data = result.data
    assert data["sector"] == "Technology"
    assert isinstance(data["rows"], list)
    assert len(data["rows"]) >= 6
    assert data["methodology"]
    assert data["exchange_name"]


def test_des_execute_returns_provider_unavailable_when_no_source_responds() -> None:
    fn = DESFunction()
    fn.deps = FunctionDeps()  # no providers wired

    result = _run(fn.execute(_instrument()))
    data = result.data
    assert data["status"] == "provider_unavailable"
    assert "next_actions" in data and data["next_actions"]
    assert data["description"] is None
    assert result.sources == ["yfinance", "finnhub", "sec_edgar"]


def test_des_execute_provider_error_surfaces_in_data() -> None:
    class _Boom:
        async def fetch(self, _req: Any) -> Any:
            raise RuntimeError("boom")

    fn = DESFunction()
    fn.deps = FunctionDeps(yfinance=_Boom())

    result = _run(fn.execute(_instrument()))
    data = result.data
    # Falls through to the no-source fallback because every provider raised.
    assert data["status"] == "provider_unavailable"
    # Provider errors are attached to data so the UI can surface them.
    errors = data.get("provider_errors", [])
    assert any("boom" in str(err) for err in errors)


def test_des_execute_raises_without_instrument() -> None:
    fn = DESFunction()
    with pytest.raises(ValueError):
        _run(fn.execute(None))


# ── Crypto path ───────────────────────────────────────────────────────────


def _btc_instrument() -> Instrument:
    return Instrument(
        symbol="BTCUSDT",
        asset_class=AssetClass.CRYPTO,
        exchange="BINANCE",
        currency="USDT",
        name="Bitcoin",
    )


def _coingecko_btc_payload() -> dict[str, Any]:
    return {
        "id": "bitcoin",
        "symbol": "btc",
        "name": "Bitcoin",
        "market_cap_rank": 1,
        "categories": ["Cryptocurrency", "Layer 1 (L1)"],
        "country_origin": "",
        "genesis_date": "2009-01-03",
        "hashing_algorithm": "SHA-256",
        "block_time_in_minutes": 10,
        "description": {"en": "Bitcoin is the first decentralized cryptocurrency."},
        "links": {
            "homepage": ["https://bitcoin.org", ""],
            "repos_url": {"github": ["https://github.com/bitcoin/bitcoin"]},
        },
        "market_data": {
            "current_price": {"usd": 92_345.0},
            "market_cap": {"usd": 1_800_000_000_000},
            "total_volume": {"usd": 35_000_000_000},
            "high_24h": {"usd": 93_500.0},
            "low_24h": {"usd": 91_000.0},
            "price_change_percentage_24h": 1.25,
            "ath": {"usd": 109_000.0},
            "ath_date": {"usd": "2025-01-20T14:30:00.000Z"},
            "atl": {"usd": 67.81},
            "atl_date": {"usd": "2013-07-06T00:00:00.000Z"},
            "circulating_supply": 19_700_000,
            "total_supply": 19_700_000,
            "max_supply": 21_000_000,
        },
    }


def test_coingecko_mapper_flattens_market_data() -> None:
    out = _coingecko_to_des(_coingecko_btc_payload(), "BTCUSDT")
    assert out["asset_class"] == "CRYPTO"
    assert out["symbol"] == "BTC"
    assert out["name"] == "Bitcoin"
    assert out["regularMarketPrice"] == 92_345.0
    assert out["market_cap"] == 1_800_000_000_000
    assert out["regularMarketChangePercent"] == pytest.approx(1.25)
    # previousClose synthesized from change_pct
    assert out["previousClose"] == pytest.approx(92_345.0 / 1.0125)
    assert out["all_time_high"] == 109_000.0
    assert out["all_time_high_date"] == "2025-01-20T14:30:00.000Z"
    assert out["circulating_supply"] == 19_700_000
    assert out["max_supply"] == 21_000_000
    assert out["genesis_date"] == "2009-01-03"
    assert out["hashing_algorithm"] == "SHA-256"
    assert out["block_time_in_minutes"] == 10
    assert "Layer 1 (L1)" in out["categories"]
    assert out["website"] == "https://bitcoin.org"
    assert out["github_repo"] == "https://github.com/bitcoin/bitcoin"


def test_des_execute_crypto_uses_coingecko_first() -> None:
    fn = DESFunction()
    cg = _FakeYFinance(_coingecko_btc_payload())
    cc = _FakeYFinance({"name": "ignored"})
    yf = _FakeYFinance({"name": "ignored"})
    # Wire the providers in the order DES expects for crypto.
    fn.deps = FunctionDeps(coingecko=cg, cryptocompare=cc, yfinance=yf)

    result = _run(fn.execute(_btc_instrument()))
    data = result.data

    assert result.sources == ["coingecko"]
    assert cg.calls == 1
    assert cc.calls == 0
    assert yf.calls == 0
    assert data["asset_class"] == "CRYPTO"
    assert data["symbol"] == "BTC"
    assert data["regularMarketPrice"] == 92_345.0
    assert data["market_cap"] == 1_800_000_000_000
    assert data["all_time_high"] == 109_000.0
    assert data["circulating_supply"] == 19_700_000
    # Crypto rows must surface the crypto-specific fields, not Employees/Sector.
    fields = {row["field"] for row in data["rows"]}
    assert {"Circulating supply", "Max supply", "Hashing algorithm", "Genesis date"}.issubset(
        fields
    )
    assert "Employees" not in fields


def test_des_asset_classes_include_crypto() -> None:
    classes = {ac.value for ac in DESFunction.asset_classes}
    assert "CRYPTO" in classes
    assert "EQUITY" in classes


def test_des_crypto_provider_unavailable_when_all_fail() -> None:
    fn = DESFunction()
    fn.deps = FunctionDeps()  # no providers wired
    result = _run(fn.execute(_btc_instrument()))
    data = result.data
    assert data["status"] == "provider_unavailable"
    assert result.sources == ["coingecko", "cryptocompare", "yfinance"]


# ── CoinGecko ID-mismatch guard ───────────────────────────────────────────
#
# Unmapped symbols fall back to ``symbol.lower()`` as the CoinGecko id. That
# id can resolve to a *different* asset (e.g. requesting "GAS" returns a coin
# whose canonical symbol is not "GAS"), which would otherwise present the WRONG
# coin's profile under the requested ticker. The adapter must refuse to pass a
# symbol-mismatched payload off as the requested asset.


import httpx  # noqa: E402

from showme.engine.core.base_data_source import DataKind, DataRequest  # noqa: E402
from showme.engine.core.instrument import Instrument as _Instrument  # noqa: E402
from showme.engine.data_sources.crypto.coingecko_adapter import (  # noqa: E402
    CoinGeckoAdapter,
)


def _adapter_with_refdata(payload: dict[str, Any]) -> CoinGeckoAdapter:
    """Build a CoinGeckoAdapter whose HTTP client returns ``payload`` for the
    ``/coins/{id}`` REFDATA call, using an httpx MockTransport (no network)."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    adapter = CoinGeckoAdapter()
    adapter._client = httpx.AsyncClient(
        base_url=adapter.base_url,
        transport=httpx.MockTransport(_handler),
    )
    return adapter


def _refdata_request(symbol: str) -> DataRequest:
    return DataRequest(
        kind=DataKind.REFDATA,
        instrument=_Instrument(
            symbol=symbol, asset_class=AssetClass.CRYPTO, exchange="BINANCE",
            currency="USD",
        ),
    )


def test_coingecko_refdata_rejects_symbol_mismatch_for_unmapped_id() -> None:
    # "GAS" is not in _ID_MAP → id falls back to "gas"; suppose CoinGecko's
    # "gas" coin actually carries a different canonical symbol. The adapter
    # must NOT present that coin as "GAS".
    wrong = {
        "id": "gas",
        "symbol": "neogas",  # canonical symbol differs from the request
        "name": "Some Other Coin",
        "market_data": {"current_price": {"usd": 5.0}},
    }
    adapter = _adapter_with_refdata(wrong)
    out = _run(adapter.fetch(_refdata_request("GAS")))
    # Honest no-profile result, NOT the mismatched coin's data.
    assert isinstance(out, dict)
    assert out.get("status") == "provider_unavailable"
    assert out.get("name") != "Some Other Coin"


def test_coingecko_refdata_accepts_matching_symbol_for_unmapped_id() -> None:
    # An unmapped symbol whose CoinGecko id resolves to the SAME symbol is fine.
    good = {
        "id": "somecoin",
        "symbol": "somecoin",
        "name": "Some Coin",
        "market_data": {"current_price": {"usd": 1.0}},
    }
    adapter = _adapter_with_refdata(good)
    out = _run(adapter.fetch(_refdata_request("SOMECOIN")))
    assert out.get("name") == "Some Coin"
    assert out.get("symbol") == "somecoin"


def test_coingecko_base_symbol_strips_separator() -> None:
    # The guard compares the returned coin symbol against the requested base
    # symbol. For separator-style tickers ("BTC-USD", "BTC/USD") the separator
    # must be stripped along with the quote suffix, else the base would carry a
    # trailing "-"/"/" and falsely mismatch a correct coin.
    assert CoinGeckoAdapter._base_symbol("BTCUSDT") == "BTC"
    assert CoinGeckoAdapter._base_symbol("BTC-USD") == "BTC"
    assert CoinGeckoAdapter._base_symbol("BTC/USD") == "BTC"


def test_coingecko_refdata_accepts_hyphenated_matching_symbol() -> None:
    # An unmapped, hyphen-separated ticker whose coin's canonical symbol matches
    # the base must be ACCEPTED — not falsely rejected by a trailing-separator
    # base ("FOO-" != "FOO"). Guards the _base_symbol separator fix.
    good = {
        "id": "foo-usd",
        "symbol": "foo",
        "name": "Foo Coin",
        "market_data": {"current_price": {"usd": 1.0}},
    }
    adapter = _adapter_with_refdata(good)
    out = _run(adapter.fetch(_refdata_request("FOO-USD")))
    assert out.get("name") == "Foo Coin"
    assert out.get("status") != "provider_unavailable"


def test_coingecko_refdata_trusts_mapped_id_even_if_symbol_differs() -> None:
    # Mapped ids (e.g. MATIC→polygon-pos) are curated; the returned symbol may
    # legitimately differ from the Binance ticker, so the guard must not fire.
    payload = {
        "id": "polygon-pos",
        "symbol": "pol",  # CoinGecko renamed MATIC's symbol to POL
        "name": "Polygon",
        "market_data": {"current_price": {"usd": 0.5}},
    }
    adapter = _adapter_with_refdata(payload)
    out = _run(adapter.fetch(_refdata_request("MATIC")))
    assert out.get("name") == "Polygon"
