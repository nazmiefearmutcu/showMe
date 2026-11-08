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


def test_regm_allow_model_flag_never_serves_a_synthetic_series() -> None:
    """allow_model used to serve a sine-wave 'regime_model'; it is now ignored."""
    from showme.engine.functions.macro.regm import REGMFunction

    # Data policy: allow_model=true no longer substitutes a templated series.
    out = asyncio.run(REGMFunction().execute(symbol="SPY", allow_model=True))
    assert out.data["status"] == "provider_unavailable"
    assert out.data["current"] == {}
    assert "regime_model" not in out.sources


# ----------------------- RPAR -----------------------

def test_rpar_default_no_yfinance_is_explicit_state_not_template() -> None:
    from showme.engine.functions.portfolio.rpar import RPARFunction

    out = asyncio.run(RPARFunction().execute(symbols="AAPL,MSFT,BTCUSDT"))
    # No yfinance → live flips false; the response is an explicit state with no invented weights.
    assert out.metadata.get("fallback") is True
    assert out.metadata.get("fallback_reason") == "yfinance_unavailable"
    assert out.sources == []
    assert out.data["status"] == "provider_unavailable"
    assert out.data["weights"] == {}


def test_rpar_explicit_model_flag_is_explicit_state_and_skips_yfinance() -> None:
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.portfolio.rpar import RPARFunction

    class FakeYf:
        async def fetch(self, *a, **kw):  # pragma: no cover - never called when model=true
            raise AssertionError("fake yfinance must not be hit when model=true")

    deps = FunctionDeps(yfinance=FakeYf())
    out = asyncio.run(RPARFunction(deps).execute(symbols="AAPL,MSFT,BTC", model=True))
    assert out.metadata.get("fallback") is True
    assert out.metadata.get("fallback_reason") == "model_requested"
    assert out.data["status"] == "needs_input"
    assert out.data["weights"] == {}


# ----------------------- SECT -----------------------

def test_sect_live_mode_preserves_requested_period_header() -> None:
    """A requested YTD window with no daily history must not be relabelled as a
    1D change: the change is null and a warning names the missing YTD base."""
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
    assert all(r["change_pct"] is None for r in out.data["rows"])
    assert all(r["change_pct_period"] is None for r in out.data["rows"])
    assert any("YTD" in w for w in out.warnings), out.warnings
    assert out.metadata["live"] is True
    assert out.metadata["requested_period"] == "YTD"


def test_sect_no_provider_in_live_mode_reports_provider_unavailable() -> None:
    from showme.engine.functions.screen.sect import SECTFunction

    out = asyncio.run(SECTFunction().execute(period="MTD", live=True))
    assert out.data["status"] == "provider_unavailable"
    assert out.data["period"] == "MTD"


# ----------------------- SOSC -----------------------

def test_sosc_default_returns_template_with_fallback_metadata_when_no_providers() -> None:
    """2026-06-01 contract change: SOSC was de-garbaged.

    OLD (removed) contract: with no providers SOSC emitted a static
    bullish/bearish template (hardcoded 42/18 split) tagged
    ``metadata.fallback=True`` / ``fallback_reason="no_social_providers_configured"``.

    NEW honest contract (S3a): SOSC reads Awareness entity sentiment and NEVER
    fabricates a sentiment split. With Awareness down it returns the honest
    ``provider_unavailable`` envelope with ``no_live_source``; the fabricated 42/18
    template must never reappear. Awareness is mocked offline here.
    """
    import httpx

    from showme.engine.core.instrument import AssetClass, Instrument
    from showme.engine.data_sources.awareness import AwarenessClient
    from showme.engine.functions.news.sosc import SOSCFunction

    def _down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    fn = SOSCFunction()
    fn._awareness = AwarenessClient("http://aw.test", transport=httpx.MockTransport(_down), autostart=False)
    out = asyncio.run(fn.execute(instrument=Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)))
    status = out.data["status"]
    assert status == "provider_unavailable"
    assert out.data["methodology"]
    srcs = [s.lower() for s in (out.sources or [])]
    # Anti-garbage: the removed 42/18 hardcoded template must never come back.
    assert "bullish_pct" not in out.data
    assert "no_live_source" in srcs
    assert out.metadata.get("live") is False
    assert out.warnings  # provider-unavailable warning is visible


def test_sosc_never_fabricates_a_sentiment_for_thin_coverage() -> None:
    """de-garbage 2026-06-01: SOSC was rewritten from a StockTwits/Reddit
    bull/bear aggregator (the removed ``bull_bear_ratio``/``_sentiment_rows``
    contract) to a keyless GDELT news-tone + FinBERT signal. The anti-garbage
    intent is preserved: for a ticker with little/no real coverage SOSC must
    NOT invent a confident sentiment — it returns an honest empty /
    provider_unavailable (net_sentiment 0.0 or None, no fabricated rows), and
    crucially never the old hardcoded 42/18 bull/bear template."""
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.core.instrument import AssetClass, Instrument
    from showme.engine.functions.news.sosc import SOSCFunction

    import httpx

    from showme.engine.data_sources.awareness import AwarenessClient

    # An offline awareness answers nothing; no fake bull/bear split can appear.
    def _down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    deps = FunctionDeps()
    fn = SOSCFunction(deps)
    fn._awareness = AwarenessClient("http://aw.test", transport=httpx.MockTransport(_down), autostart=False)
    out = asyncio.run(fn.execute(
        instrument=Instrument(symbol="ZZZZ", asset_class=AssetClass.EQUITY),
    ))
    status = str(out.data.get("status", "")).lower()
    assert status == "provider_unavailable"
    # The removed garbage contract must be gone for good.
    assert "bull_bear_ratio" not in out.data
    assert "news" not in out.data
    assert not (out.data.get("rows") or [])


# ----------------------- SRSK -----------------------

# A keyless World Bank REST reply is ``[meta, [obs, ...]]`` with the latest
# governance/macro value under ``value``. The SRSK ``worldbank`` adapter seam is
# called as ``adapter.indicator(iso3, indicator)`` (it tries indicator/series/
# get/fetch in turn), so the fake exposes ``indicator(iso3, indicator)`` and
# returns a distinct per-ISO3 value — keeping risk scores non-uniform.
class _FakeWorldBank:
    _BY_ISO3 = {"TUR": 90.0, "USA": 35.0, "DEU": 20.0}

    async def indicator(self, iso3, indicator):  # type: ignore[no-untyped-def]
        value = self._BY_ISO3.get(iso3, 50.0)
        return [{"page": 1, "total": 1}, [{"value": value, "date": "2024"}]]


class _FredOutage:
    async def series(self, series_id: str, *a, **k):  # noqa: ARG002
        raise RuntimeError("fred outage (test)")


def _pin_fred_outage(monkeypatch) -> None:
    """SRSK#5 added the keyless FRED fallback; these 'no FRED' cases pin it to an
    outage so they stay offline and keep testing the World Bank paths."""
    from showme.engine.functions.bond import srsk as srsk_mod

    monkeypatch.setattr(srsk_mod, "fred_with_keyless_fallback", lambda fred, client=None: _FredOutage())


def test_srsk_no_fred_returns_fallback_with_notes_and_no_uniform_pd(monkeypatch) -> None:
    """2026-06-01 contract change: SRSK was de-garbaged.

    OLD (removed) contract: SRSK was FRED-gated and, without FRED, tagged every
    row ``sovereign_risk_model`` with a uniform proxy spread.

    NEW honest contract: SRSK is keyless World-Bank-primary; FRED 10Y yields are
    an OPTIONAL refinement only. Without FRED it serves REAL per-country rows
    sourced from the World Bank (status ok, ``sources`` includes ``worldbank``,
    every row ``source_mode=worldbank``). We inject a fake World Bank adapter
    (the ``worldbank`` dep seam) so the test is deterministic offline, and assert
    the new honest contract plus the anti-garbage invariant that per-country risk
    scores are NOT uniform.
    """
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.bond.srsk import SRSKFunction

    _pin_fred_outage(monkeypatch)
    out = asyncio.run(
        SRSKFunction(FunctionDeps(worldbank=_FakeWorldBank())).execute(countries="TR,US,DE")
    )
    assert out.data["status"] == "ok"
    countries = [row["country"] for row in out.data["rows"]]
    assert countries == ["TR", "US", "DE"]
    assert "worldbank" in [s.lower() for s in out.sources]
    assert all(row["source_mode"] == "worldbank" for row in out.data["rows"])
    # Anti-garbage: distinct per-country risk scores, never a uniform PD.
    scores = [r["risk_score"] for r in out.data["rows"]]
    assert len(set(scores)) > 1, "uniform risk score across countries is the old garbage"


def test_srsk_dgs10_missing_returns_provider_unavailable(monkeypatch) -> None:
    """2026-06-01 contract change: SRSK was de-garbaged to keyless
    World-Bank-primary; FRED 10Y yields are an OPTIONAL refinement only.

    A missing FRED series no longer drives provider_unavailable — a TOTAL World
    Bank outage does. To exercise that branch deterministically (and offline) we
    monkeypatch the World Bank fetch seam to raise ``_WBUnavailable`` for every
    country, so SRSK returns the honest provider_unavailable envelope (empty
    rows). FRED also fails, proving it is non-essential to the result.
    """
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.bond import srsk as srsk_mod
    from showme.engine.functions.bond.srsk import SRSKFunction

    class FakeFred:
        async def series(self, sid: str):  # type: ignore[no-untyped-def]
            raise RuntimeError("fred outage")

    fn = SRSKFunction(FunctionDeps(fred=FakeFred()))
    _pin_fred_outage(monkeypatch)

    async def _boom(self, iso3, indicator):  # type: ignore[no-untyped-def]
        raise srsk_mod._WBUnavailable("world bank unreachable")

    # Patch the per-indicator fetch so the keyless World Bank path is a hard
    # outage without touching the network.
    fn._wb_fetch_indicator = _boom.__get__(fn, SRSKFunction)  # type: ignore[method-assign]

    out = asyncio.run(fn.execute(countries="TR,DE"))
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

    # The known-column guard is independent of the live tier chain; pin the
    # deterministic reference path (live providers are exercised in
    # test_srch_live_bonds.py with monkeypatched providers).
    out = asyncio.run(
        SRCHFunction().execute(query="yield >= 4 AND duration <= 10", live=False)
    )
    # H-6 (2026-09-08): with no live refresh the matched rows are labelled
    # "reference" (not "ok") with a top-level warning.
    assert out.data["status"] == "reference"
    assert out.warnings, "reference universe must warn it is not live"
    assert out.data["rows"]
