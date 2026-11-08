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
