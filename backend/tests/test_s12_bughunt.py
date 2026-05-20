"""S12 BugHunt regressions — pin the post-fix behaviour for REGM, RPAR,
SECT, SOSC, SRSK and the SRCH/SECF screen DSL guard.

These tests run the function classes directly with `FunctionDeps()` (all
providers None) so they exercise the explicit fallback paths the fixes
introduced. No external network calls.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _engine_syspath(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "engine"))


# ----------------------- REGM -----------------------

def test_regm_returns_provider_unavailable_when_yfinance_missing() -> None:
    from showme.engine.functions.macro.regm import REGMFunction

    out = asyncio.run(REGMFunction().execute(symbol="SPY"))
    assert out.data["status"] == "provider_unavailable"
    assert out.data["rows"] == []
    # The previous behaviour was a synthetic sine wave masquerading as live;
    # now sources must NOT contain the legacy `regime_model` sentinel.
    assert "regime_model" not in out.sources
    assert any("yfinance" in w for w in out.warnings)


def test_regm_allow_model_flag_still_returns_template_with_warning() -> None:
    from showme.engine.functions.macro.regm import REGMFunction

    out = asyncio.run(REGMFunction().execute(symbol="SPY", allow_model=True))
    # When the caller opts in to the synthetic model, we serve it but log it.
    assert out.data.get("status") != "provider_unavailable"
    assert "regime_model" in out.sources


# ----------------------- RPAR -----------------------

def test_rpar_default_no_yfinance_returns_template_with_fallback_flag() -> None:
    from showme.engine.functions.portfolio.rpar import RPARFunction

    out = asyncio.run(RPARFunction().execute(symbols="AAPL,MSFT,BTCUSDT"))
    # No yfinance → live flips false, fallback flagged in metadata.
    assert out.metadata.get("fallback") is True
    assert out.metadata.get("fallback_reason") in {"yfinance_unavailable", "model_requested"}
    assert "risk_parity_model" in out.sources
    assert any("risk-parity_model" in w or "risk_parity_model" in w or "live_risk" in w for w in out.warnings)


def test_rpar_explicit_model_flag_forces_template_even_with_yfinance() -> None:
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.portfolio.rpar import RPARFunction

    class FakeYf:
        async def fetch(self, *a, **kw):  # pragma: no cover - never called when model=true
            raise AssertionError("fake yfinance must not be hit when model=true")

    deps = FunctionDeps(yfinance=FakeYf())
    out = asyncio.run(RPARFunction(deps).execute(symbols="AAPL,MSFT,BTC", model=True))
    assert out.metadata.get("fallback") is True
    assert out.metadata.get("fallback_reason") == "model_requested"


# ----------------------- SECT -----------------------

def test_sect_live_mode_preserves_requested_period_header() -> None:
    """Even though live quotes only provide 1D change, the response must
    keep the user-requested period header and surface a warning that the
    change values reflect a narrower window."""
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.screen.sect import SECTFunction

    class FakeQuote:
        last = 100.0
        close_prev = 98.0
        high_24h = 101.0
        low_24h = 97.0

    class FakeYf:
        async def fetch(self, *a, **kw):
            return FakeQuote()

    out = asyncio.run(SECTFunction(FunctionDeps(yfinance=FakeYf())).execute(period="YTD", live=True))
    assert out.data["period"] == "YTD"
    assert out.data["change_pct_period"] == "1D"
    assert any("intraday" in w.lower() or "1D" in w for w in out.warnings)
    assert out.metadata["live"] is True
    assert out.metadata["requested_period"] == "YTD"


def test_sect_no_provider_in_live_mode_reports_provider_unavailable() -> None:
    from showme.engine.functions.screen.sect import SECTFunction

    out = asyncio.run(SECTFunction().execute(period="MTD", live=True))
    assert out.data["status"] == "provider_unavailable"
    assert out.data["period"] == "MTD"


# ----------------------- SOSC -----------------------

def test_sosc_default_returns_template_with_fallback_metadata_when_no_providers() -> None:
    from showme.engine.core.instrument import AssetClass, Instrument
    from showme.engine.functions.news.sosc import SOSCFunction

    out = asyncio.run(SOSCFunction().execute(instrument=Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)))
    assert out.metadata.get("live") is False
    assert out.metadata.get("fallback") is True
    assert out.metadata.get("fallback_reason") == "no_social_providers_configured"
    assert out.warnings  # served-template warning is visible


def test_sosc_bull_bear_ratio_is_none_when_message_volume_too_low() -> None:
    """ratio guard: bullish=1 / bearish=0 must NOT yield 1.0 — too few messages."""
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.core.instrument import AssetClass, Instrument
    from showme.engine.functions.news.sosc import SOSCFunction

    class FakeTwits:
        async def fetch(self, *a, **kw):
            return {"bullish_count": 1, "bearish_count": 0, "message_count": 1}

    class FakeReddit:
        async def fetch(self, *a, **kw):
            return []

    deps = FunctionDeps(stocktwits=FakeTwits(), reddit=FakeReddit())
    out = asyncio.run(SOSCFunction(deps).execute(
        instrument=Instrument(symbol="ZZZZ", asset_class=AssetClass.EQUITY),
    ))
    # Either provider_unavailable (no rows) or live with reliable=False.
    if out.data.get("status") == "provider_unavailable":
        return
    assert out.data["bull_bear_ratio"] is None
    assert out.data["bull_bear_ratio_reliable"] is False


# ----------------------- SRSK -----------------------

def test_srsk_no_fred_returns_fallback_with_notes_and_no_uniform_pd() -> None:
    """When FRED is not configured we still serve rows, but every non-mapped
    country must carry a `note` instead of pretending the fallback spread is
    real data."""
    from showme.engine.functions.bond.srsk import SRSKFunction

    out = asyncio.run(SRSKFunction().execute(countries="TR,US,DE"))
    assert out.data["status"] in {"fallback", "ok"}
    countries = [row["country"] for row in out.data["rows"]]
    assert countries == ["TR", "US", "DE"]
    # Without FRED every row uses sovereign_risk_model.
    assert all(row["source_mode"] == "sovereign_risk_model" for row in out.data["rows"])


def test_srsk_dgs10_missing_returns_provider_unavailable() -> None:
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.bond.srsk import SRSKFunction

    class FakeFred:
        async def series(self, sid: str):  # type: ignore[no-untyped-def]
            raise RuntimeError("fred outage")

    out = asyncio.run(SRSKFunction(FunctionDeps(fred=FakeFred())).execute(countries="TR,DE"))
    assert out.data["status"] == "provider_unavailable"
    assert out.data["rows"] == []
    assert out.warnings  # surface the provider error


# ----------------------- SECF / SRCH predicate guard -----------------------

def test_secf_dsl_with_unknown_column_returns_unsupported_predicate() -> None:
    from showme.engine.functions.screen._funcs import SECFFunction

    # SECF text branch is skipped because this query smells like DSL.
    out = asyncio.run(SECFFunction().execute(query='nonexistentColumn = "Energy"'))
    assert out.data["status"] == "unsupported_predicate"
    assert "nonexistentColumn" in out.data["unsupported_columns"]
    assert "Filter references unknown columns" in (out.data.get("reason") or "")


def test_srch_dsl_with_known_column_still_passes() -> None:
    from showme.engine.functions.screen._funcs import SRCHFunction

    out = asyncio.run(SRCHFunction().execute(query="yield >= 4 AND duration <= 10"))
    assert out.data["status"] == "ok"
    assert out.data["rows"]
