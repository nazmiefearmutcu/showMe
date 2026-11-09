"""ESG#5: the ESG manifest must describe the real chain the handler runs.

The handler (engine/functions/equity/esg.py) reads Yahoo Finance sustainability
data first, then a labelled SEC EDGAR 10-K text proxy. It never reports a
vendor score without a provider. The manifest must say so.
"""
from __future__ import annotations

from showme.manifest.enums import DataMode
from showme.manifest.seeds.esg_seed import esg


def _manifest():
    return esg


def test_primary_is_yfinance_with_sec_edgar_proxy_fallback():
    m = _manifest()
    assert m.provider_chain.primary == "yfinance"
    assert "sec_edgar" in m.provider_chain.fallbacks


def test_default_mode_is_not_not_configured():
    m = _manifest()
    assert m.defaults["provider_mode"] != DataMode.NOT_CONFIGURED.value


def test_methodology_describes_sustainalytics_source_and_labelled_proxy():
    text = _manifest().methodology.lower()
    assert "yahoo" in text and "sustainalytics" in text
    assert "sec edgar" in text and "proxy" in text
    assert "not risk scores" in text
    assert "requires a paid vendor" not in text
    assert "no vendor is wired" not in text


def test_acceptable_modes_match_what_the_handler_emits():
    modes = set(_manifest().provider_chain.acceptable_modes)
    # yfinance path -> delayed_reference; EDGAR proxy -> live_official (a live
    # fetch of SEC filings); unavailable / empty -> not_configured.
    assert modes == {DataMode.DELAYED_REFERENCE, DataMode.LIVE_OFFICIAL, DataMode.NOT_CONFIGURED}
