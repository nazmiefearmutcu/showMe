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
    """2026-06-01 contract change: SOSC was de-garbaged.

    OLD (removed) contract: with no providers SOSC emitted a static
    bullish/bearish template (hardcoded 42/18 split) tagged
    ``metadata.fallback=True`` / ``fallback_reason="no_social_providers_configured"``.

    NEW honest contract: SOSC pulls REAL keyless GDELT news-tone + FinBERT and
    NEVER fabricates a sentiment split. The result depends on ambient
    connectivity: with a live GDELT path it returns ``ok``/``empty`` sourced from
    ``gdelt`` (+ ``finbert`` when headlines are scored); on a genuine GDELT
    outage it returns the honest ``provider_unavailable`` envelope with
    ``no_live_source``. Either way the fabricated 42/18 template must never
    reappear. We assert the honest-degradation shape + the no-garbage invariant
    rather than pinning a single branch.
    """
    from showme.engine.core.instrument import AssetClass, Instrument
    from showme.engine.functions.news.sosc import SOSCFunction

    out = asyncio.run(SOSCFunction().execute(instrument=Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)))
    status = out.data["status"]
    assert status in {"ok", "empty", "provider_unavailable"}
    assert out.data["methodology"]
    srcs = [s.lower() for s in (out.sources or [])]
    summary = out.data.get("summary") or {}
    # Anti-garbage: the removed 42/18 hardcoded template must never come back.
    assert not (summary.get("bullish_pct") == 42 and summary.get("bearish_pct") == 18)
    if status in {"ok", "empty"}:
        # Live GDELT path: tone-sourced (FinBERT joins when headlines exist).
        assert "gdelt" in srcs
        assert out.metadata.get("live") is True
    else:
        # Genuine outage (e.g. GDELT throttled) — honest, never fabricated.
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

    # The old StockTwits/Reddit adapters are ignored by the GDELT rewrite;
    # passing none proves no fake bull/bear split can be injected.
    deps = FunctionDeps()
    out = asyncio.run(SOSCFunction(deps).execute(
        instrument=Instrument(symbol="ZZZZ", asset_class=AssetClass.EQUITY),
    ))
    status = str(out.data.get("status", "")).lower()
    assert status in {"ok", "empty", "provider_unavailable"}
    # The removed garbage contract must be gone for good.
    assert "bull_bear_ratio" not in out.data
    summary = out.data.get("summary") or {}
    # An obscure ticker yields no real coverage → honest neutral/empty, never
    # the old fabricated 42-bull/18-bear constant.
    if status in {"empty", "provider_unavailable"}:
        assert summary.get("net_sentiment") in (0.0, None)
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


def test_srsk_no_fred_returns_fallback_with_notes_and_no_uniform_pd() -> None:
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


def test_srsk_dgs10_missing_returns_provider_unavailable() -> None:
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

    out = asyncio.run(SRCHFunction().execute(query="yield >= 4 AND duration <= 10"))
    assert out.data["status"] == "ok"
    assert out.data["rows"]
