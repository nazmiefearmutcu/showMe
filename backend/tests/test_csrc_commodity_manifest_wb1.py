"""wb1-g17 / CSRC#5 — the served CSRC manifest must describe the function it serves.

CSRCFunction is the Commodity Screener (futures complex, yfinance =F quotes).
The manifest used to describe a Binance/CoinGecko crypto screener, so every
manifest-based truth check ran against text the function never serves.
"""
from __future__ import annotations

import re

import pytest

from showme.manifest import REGISTRY, load_seeds
from showme.manifest.enums import AssetClass


@pytest.fixture(scope="module", autouse=True)
def _load_seeds_once() -> None:
    load_seeds()


def test_csrc_manifest_names_the_commodity_screener() -> None:
    manifest = REGISTRY.get("CSRC")
    assert manifest.name == "Commodity Screener"
    assert list(manifest.asset_classes) == [AssetClass.COMMODITY]


def test_csrc_manifest_text_has_no_crypto_claims() -> None:
    manifest = REGISTRY.get("CSRC")
    text = " ".join([manifest.intent, manifest.methodology]).lower()
    for crypto_term in (r"binance", r"coingecko", r"usdt", r"crypto", r"market.cap", r"\bath\b"):
        assert re.search(crypto_term, text) is None, (
            f"commodity manifest must not mention {crypto_term!r}"
        )


def test_csrc_manifest_routes_to_yfinance_futures_quotes() -> None:
    manifest = REGISTRY.get("CSRC")
    assert manifest.provider_chain.primary == "yfinance"
    assert "binance" not in manifest.provider_chain.fallbacks
    assert "coingecko" not in manifest.provider_chain.fallbacks


def test_csrc_manifest_inputs_are_commodity_inputs_only() -> None:
    manifest = REGISTRY.get("CSRC")
    names = {spec.name for spec in manifest.inputs}
    for crypto_input in ("quote_currency", "min_volume_usd_24h", "max_market_cap_rank",
                         "ath_distance_min_pct", "categories", "saved_screen"):
        assert crypto_input not in names
    assert {"sector", "limit", "provider_mode"} <= names


def test_csrc_sector_options_match_the_backend_reference_sectors() -> None:
    from showme.engine.functions.screen._funcs import _commodity_reference_rows

    manifest = REGISTRY.get("CSRC")
    sector_input = next(spec for spec in manifest.inputs if spec.name == "sector")
    backend_sectors = {str(row["sector"]) for row in _commodity_reference_rows()}
    assert set(sector_input.options) - {"all"} == backend_sectors
    assert "Agriculture" not in sector_input.options


def test_csrc_field_dictionary_has_no_agriculture_sector() -> None:
    from showme.engine.functions.screen._funcs import _COMMODITY_FIELDS

    meanings = " ".join(str(entry.get("meaning", "")) for entry in _COMMODITY_FIELDS)
    assert "Agriculture" not in meanings
    assert "Grains" in meanings and "Livestock" in meanings


async def test_csrc_must_have_names_only_keys_the_payload_produces() -> None:
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.screen._funcs import CSRCFunction

    manifest = REGISTRY.get("CSRC")
    result = await CSRCFunction(deps=FunctionDeps()).execute(reference=True)
    missing = [key for key in manifest.output_contract.must_have if key not in result.data]
    assert missing == [], f"CSRC must_have promises keys the payload does not carry: {missing}"
    assert "sector" not in manifest.output_contract.must_have
    assert "data_mode" not in manifest.output_contract.must_have


async def test_csrc_reference_payload_as_of_is_null_not_request_time() -> None:
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.screen._funcs import CSRCFunction

    result = await CSRCFunction(deps=FunctionDeps()).execute(reference=True)
    assert "as_of" in result.data
    assert result.data["as_of"] is None


async def test_csrc_live_rows_and_payload_carry_provider_quote_time(monkeypatch) -> None:
    from datetime import datetime, timezone

    from showme import quotes
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.screen._funcs import CSRCFunction

    quote_time = datetime(2026, 11, 6, 20, 0, tzinfo=timezone.utc)
    quotes.quote_cache_clear()

    async def _fake_fetch(symbol: str) -> dict:
        return {
            "symbol": symbol,
            "last": 80.0,
            "price": 80.0,
            "previous_close": 79.0,
            "change_pct": 1.26,
            "volume": 1000.0,
            "source": "yahoo_chart",
            "raw": {"regular_market_time": quote_time.timestamp()},
        }

    monkeypatch.setattr(quotes, "fetch_quote_snapshot", _fake_fetch)

    class _YFinanceLikeProvider:
        name = "yfinance"

    result = await CSRCFunction(deps=FunctionDeps(yfinance=_YFinanceLikeProvider())).execute(
        live_screen=True, query='sector = "Energy"', limit=50,
    )
    live_rows = [row for row in result.data["rows"] if row.get("quote_state") == "live"]
    assert live_rows, "the fake quote service must resolve at least one energy contract"
    for row in live_rows:
        assert row.get("quote_time") == quote_time.isoformat(), row["symbol"]
    assert result.data["as_of"] == quote_time.isoformat()
