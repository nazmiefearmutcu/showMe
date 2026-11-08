"""MAP universe honesty (wc1-g28, MAP#2): the map holds MSCI single-country ETFs only.

The function describes itself as an MSCI single-country ETF heatmap. Tickers
checked against the public quote chart endpoint (2026-11-08):
  SPY   = State Street SPDR S&P 500 ETF Trust (not MSCI)
  VGK   = Vanguard FTSE Europe ETF (not MSCI, not single-country)
  FXI   = iShares China Large-Cap ETF (FTSE China 50, not MSCI)
  VNM   = VanEck Vietnam ETF (not MSCI)
  XU100.IS = BIST 100 (an index, not an ETF)
  EGPT  = not found (HTTP 404)
  EUSA  = iShares MSCI USA Equal Weighted ETF (MSCI)
  MCHI  = iShares MSCI China ETF (MSCI)
Offline: no quote is fetched in this module.
"""

from __future__ import annotations

import pytest

from showme.engine.functions.screen import wmap

NON_MSCI_OR_NOT_ETF = {"SPY", "VGK", "FXI", "VNM", "XU100.IS", "EGPT"}


def test_no_non_msci_or_non_etf_ticker_is_in_the_map() -> None:
    assert NON_MSCI_OR_NOT_ETF.isdisjoint(set(wmap._COUNTRY_ETFS.values()))


def test_non_single_country_or_index_markets_are_not_in_the_map() -> None:
    # EU (a multi-country aggregate with no MSCI single-country ETF here), BIST
    # (an index), VN (no MSCI ETF) and EG (ticker does not resolve) are removed
    # rather than shown under a label they do not earn.
    for country in ("EU", "BIST", "VN", "EG"):
        assert country not in wmap._COUNTRY_ETFS


@pytest.mark.parametrize(
    ("country", "etf"),
    [("US", "EUSA"), ("CN", "MCHI"), ("GB", "EWU"), ("JP", "EWJ"), ("BR", "EWZ")],
)
def test_country_maps_to_its_msci_single_country_etf(country: str, etf: str) -> None:
    assert wmap._COUNTRY_ETFS[country] == etf


def test_seed_field_dictionary_names_the_tickers_in_the_map() -> None:
    # The rows[].etf description still listed SPY and VGK after MAP#2 removed them.
    from showme.manifest.seeds.map_seed import market_map

    etf_description = market_map.field_dict["rows[].etf"].description
    assert "SPY" not in etf_description
    assert "VGK" not in etf_description
    assert "EUSA" in etf_description


def test_seed_says_the_us_tile_is_equal_weight_msci_not_the_sp500() -> None:
    # EUSA is iShares MSCI USA Equal Weighted, so a US tile must not read as the S&P 500.
    from showme.manifest.seeds.map_seed import market_map

    methodology = market_map.methodology
    assert "EUSA" in methodology
    assert "equal-weighted" in methodology.lower()
    assert "not the S&P 500" in methodology


def test_seed_does_not_call_the_model_mode_deterministic_prices() -> None:
    # MAP#3: model mode carries no prices, so the seed must not describe a priced fallback.
    from showme.manifest.seeds.map_seed import market_map

    manifest = market_map
    assert "deterministic fallback" not in manifest.methodology
    live_input = next(spec for spec in manifest.inputs if spec.name == "live")
    assert "deterministic" not in live_input.description
