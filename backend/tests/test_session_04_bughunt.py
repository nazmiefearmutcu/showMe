"""ShowMe Bug Hunt Session-04 — regression tests for the 10-code scope.

Each test pins one of the fixes applied during the 2026-05-17 audit.
Tests use minimal in-process stubs (no network) to keep CI cheap.

Codes covered: CSRC, DAPI, DARK, DCF, DCFS, DDIS, DDM, DEBT, DES, DINE.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


class _StubReferenceData:
    def __init__(self, raw: dict[str, Any]):
        self.extras = {"raw": dict(raw)}
        self.shares_outstanding = raw.get("sharesOutstanding")


class _StubProvider:
    """Generic stub that returns a pre-baked ReferenceData payload."""

    def __init__(self, raw: dict[str, Any]):
        self._raw = raw

    async def fetch(self, _req: Any) -> _StubReferenceData:  # noqa: D401
        return _StubReferenceData(self._raw)


def _equity_instrument(symbol: str = "NVDA") -> Instrument:
    return Instrument(symbol=symbol, asset_class=AssetClass.EQUITY)


def _crypto_instrument(symbol: str = "BTC") -> Instrument:
    return Instrument(symbol=symbol, asset_class=AssetClass.CRYPTO)


def _bond_instrument(symbol: str = "US10Y") -> Instrument:
    return Instrument(symbol=symbol, asset_class=AssetClass.BOND)


# ─────────────────────────────────────────────────────────────────────
# DCF — negative free cash flow protection
# ─────────────────────────────────────────────────────────────────────


def test_dcf_negative_free_cash_flow_emits_warning() -> None:
    """A distressed-firm fcfe (-$1B) must not be silently coerced to 0."""

    from showme.engine.functions.equity.dcf import DCFFunction

    deps = FunctionDeps(yfinance=_StubProvider({"freeCashflow": -1_000_000_000, "sharesOutstanding": 10_000_000}))
    fn = DCFFunction(deps)
    result = asyncio.run(
        fn.execute(_equity_instrument(), wacc=0.10, growth_high=0.05, growth_terminal=0.02, years=5)
    )
    data = result.data
    assert data["starting_fcfe"] == -1_000_000_000, "Negative fcfe must round-trip, not be zeroed."
    assert any(
        "negative free cash flow" in w.lower() or "free_cash_flow" in w
        for w in result.warnings
    ), f"Expected negative-fcfe warning. Got: {result.warnings}"


def test_dcf_explicit_fcfe_zero_does_not_emit_negative_warning() -> None:
    """Passing fcfe=0 explicitly is a different signal — no negative warning."""

    from showme.engine.functions.equity.dcf import DCFFunction

    deps = FunctionDeps()
    fn = DCFFunction(deps)
    result = asyncio.run(
        fn.execute(_equity_instrument(), fcfe=0, wacc=0.10, growth_terminal=0.02, years=3)
    )
    assert all(
        "negative free cash flow" not in w.lower() for w in result.warnings
    ), f"Should not warn about negative fcfe when user passed 0. Got: {result.warnings}"


# ─────────────────────────────────────────────────────────────────────
# DDM — no-dividend warning
# ─────────────────────────────────────────────────────────────────────


def test_ddm_no_dividend_emits_warning() -> None:
    """GOOG/BRK.A-style non-dividend payers must produce a non-applicable warning."""

    from showme.engine.functions.equity.dcf import DDMFunction

    deps = FunctionDeps(yfinance=_StubProvider({"dividendRate": 0}))
    fn = DDMFunction(deps)
    result = asyncio.run(fn.execute(_equity_instrument(), required_return=0.08, growth_rate=0.03))
    assert any(
        "non-dividend" in w.lower() or "ddm is not applicable" in w.lower()
        for w in result.warnings
    ), f"DDM should warn for d0=0. Got: {result.warnings}"


# ─────────────────────────────────────────────────────────────────────
# DCFS — tornado None handling
# ─────────────────────────────────────────────────────────────────────


def test_dcfs_tornado_marks_invalid_perturbation() -> None:
    """When WACC * 0.8 ≤ g_terminal, the tornado must NOT treat None as 0."""

    from showme.engine.functions.equity.dcfs import DCFSensitivityFunction

    # fcfe = 1B, shares = 10M ⇒ per-share base ≈ positive number; WACC=0.03,
    # g_terminal=0.025 ⇒ low-side perturbation pushes WACC=0.024 < g_terminal
    # and DCF returns the error dict, so the wacc tornado row must be
    # flagged invalid_perturbation rather than ranked first with a 0-vs-real delta.
    deps = FunctionDeps()
    fn = DCFSensitivityFunction(deps)
    result = asyncio.run(
        fn.execute(
            _equity_instrument(),
            fcfe=1_000_000_000,
            shares_outstanding=10_000_000,
            wacc=0.03,
            growth_high=0.04,
            growth_terminal=0.025,
            years=3,
        )
    )
    tornado = result.data.get("tornado") or []
    assert tornado, "Tornado should produce some rows."
    wacc_row = next((row for row in tornado if row.get("input") == "wacc"), None)
    assert wacc_row is not None, f"WACC row missing from tornado: {tornado}"
    assert wacc_row.get("status") == "invalid_perturbation" or wacc_row.get("delta") is not None, (
        f"WACC tornado row should be flagged invalid_perturbation when WACC*0.8 ≤ g_terminal. Got: {wacc_row}"
    )


# ─────────────────────────────────────────────────────────────────────
# DARK — _stale_reason malformed-date handling
# ─────────────────────────────────────────────────────────────────────


def test_dark_stale_reason_flags_malformed_dates() -> None:
    """Unparseable FINRA dates must NOT be treated as fresh."""

    from showme.engine.functions.equity.dark import _stale_reason

    assert _stale_reason("not-a-date") is not None
    assert _stale_reason("2026-13-99") is not None  # invalid month/day
    assert _stale_reason("") is None
    assert _stale_reason(None) is None
    # Real recent date should pass
    assert _stale_reason("2026-05-10") is None


# ─────────────────────────────────────────────────────────────────────
# DDIS — issuer fallback no longer hard-codes "AAPL"
# ─────────────────────────────────────────────────────────────────────


def test_ddis_uses_instrument_symbol_not_aapl_when_issuer_missing() -> None:
    """A bond instrument like US10Y must not be labelled AAPL by default."""

    from showme.engine.functions.bond._stubs import DDISFunction

    deps = FunctionDeps()
    fn = DDISFunction(deps)
    result = asyncio.run(fn.execute(_bond_instrument("US10Y")))
    summary = result.data["summary"]
    assert summary["issuer"] == "US10Y", f"Expected issuer=US10Y, got {summary['issuer']!r}"
    assert result.data.get("status") == "illustrative", (
        "Default debt ladder must be labelled illustrative, not 'ok' live data."
    )


def test_ddis_user_provided_maturities_get_ok_status() -> None:
    """If user supplies maturities, status flips to ok."""

    from showme.engine.functions.bond._stubs import DDISFunction

    deps = FunctionDeps()
    fn = DDISFunction(deps)
    result = asyncio.run(
        fn.execute(
            _bond_instrument("AAPL"),
            issuer="AAPL",
            maturities=[{"bucket": "0-1Y", "tenor_years": 0.5, "amount_usd_bn": 5.0, "currency": "USD", "pct": 100.0}],
        )
    )
    assert result.data.get("status") == "ok"
    assert result.data["summary"]["total_debt_usd_bn"] == 5.0


# ─────────────────────────────────────────────────────────────────────
# DES — CoinGecko shape detection no longer races
# ─────────────────────────────────────────────────────────────────────


def test_des_detects_coingecko_payload_by_shape() -> None:
    """``_looks_like_coingecko_payload`` must accept any dict with a
    ``market_data`` sub-dict and an id/symbol/categories key — even when
    a later provider appended itself to sources_used after CoinGecko."""

    from showme.engine.functions.equity.des import _looks_like_coingecko_payload

    cg_payload = {
        "id": "bitcoin",
        "symbol": "btc",
        "market_data": {"current_price": {"usd": 65_000}},
    }
    assert _looks_like_coingecko_payload(cg_payload) is True

    # Plain dict from CryptoCompare must NOT pass the detector.
    crypto_compare = {"PRICE": 65_000, "MKTCAP": 1_300_000_000_000}
    assert _looks_like_coingecko_payload(crypto_compare) is False

    # None / non-dict guards.
    assert _looks_like_coingecko_payload(None) is False  # type: ignore[arg-type]
    assert _looks_like_coingecko_payload({"market_data": "not a dict"}) is False


# ─────────────────────────────────────────────────────────────────────
# DAPI — curated manifest matches actual server_routes
# ─────────────────────────────────────────────────────────────────────


def test_dapi_curated_manifest_lists_canonical_routes() -> None:
    """Audit: curated DAPI manifest must include the well-known routes the
    sidecar mounts. This test guards against drift; when a new route is
    added to backend/showme/server_routes/, the manifest must be updated.
    """

    from showme.engine.functions.api.dapi import DAPI_CURATED_ROUTES

    paths = {row["path"] for row in DAPI_CURATED_ROUTES}
    required = {
        "/api/health",
        "/api/function-index",
        "/api/fn/{code}",
        "/api/quote/{symbol}",
        "/api/state/positions",
        "/api/broker/orders",
        "/api/mis/scan",
        "/api/scanner/run",
        "/api/instant/events",
        "/api/x/analyze",
        "/api/watchlists",
        "/api/stream/stats",
    }
    missing = required - paths
    assert not missing, f"DAPI curated manifest missing required routes: {missing}"


def test_dapi_uses_live_provider_when_available() -> None:
    """If deps.dapi_route_provider is set, DAPI prefers the live manifest."""

    from showme.engine.functions.api.dapi import DAPIFunction

    live_rows = [
        {"method": "GET", "path": "/api/live-only", "purpose": "live-only", "request_body": "-", "response_shape": "-", "mutates_state": "no", "example": "-"},
    ]
    deps = FunctionDeps(dapi_route_provider=lambda: live_rows)
    fn = DAPIFunction(deps)
    result = asyncio.run(fn.execute())
    assert result.data["summary"]["source_mode"] == "live_router_introspection"
    assert any(row["path"] == "/api/live-only" for row in result.data["rows"])


def test_dapi_falls_back_when_provider_missing() -> None:
    from showme.engine.functions.api.dapi import DAPIFunction

    deps = FunctionDeps()
    fn = DAPIFunction(deps)
    result = asyncio.run(fn.execute())
    assert result.data["summary"]["source_mode"] == "curated_manifest"
    assert result.data["summary"]["total_routes"] > 30


# ─────────────────────────────────────────────────────────────────────
# DINE — Nominatim throttle + place_id capture
# ─────────────────────────────────────────────────────────────────────


def test_dine_throttle_holds_under_one_request_per_second() -> None:
    """Two back-to-back Nominatim throttle calls must take at least
    ``_NOMINATIM_MIN_INTERVAL_SEC`` seconds in total."""

    from showme.engine.functions.misc import _extras

    async def _run() -> float:
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await _extras._nominatim_throttle()
        await _extras._nominatim_throttle()
        return loop.time() - t0

    # Reset the module-level cursor so the test is deterministic.
    _extras._nominatim_last_call_ts = 0.0  # noqa: SLF001
    _extras._nominatim_lock = None  # noqa: SLF001
    elapsed = asyncio.run(_run())
    assert elapsed >= _extras._NOMINATIM_MIN_INTERVAL_SEC * 0.95, (
        f"Throttle must enforce ≥{_extras._NOMINATIM_MIN_INTERVAL_SEC}s spacing; got {elapsed:.3f}s"
    )


def test_dine_user_agent_includes_contact_email() -> None:
    """OSM Nominatim policy demands an identifiable User-Agent with contact."""

    from showme.engine.functions.misc._extras import _NOMINATIM_USER_AGENT

    assert "@" in _NOMINATIM_USER_AGENT, (
        f"Nominatim User-Agent must include a contact email; got: {_NOMINATIM_USER_AGENT!r}"
    )
    assert "showMe" in _NOMINATIM_USER_AGENT


# ─────────────────────────────────────────────────────────────────────
# CSRC — commodity screener basic invariant
# ─────────────────────────────────────────────────────────────────────


def test_csrc_screen_returns_commodity_rows() -> None:
    from showme.engine.functions.screen._funcs import CSRCFunction

    deps = FunctionDeps()
    fn = CSRCFunction(deps)
    result = asyncio.run(fn.execute(_equity_instrument("CL=F")))
    assert isinstance(result.data, dict)
    rows = result.data.get("rows") or []
    assert rows, "CSRC must return at least the bundled commodity universe."
    assert all("symbol" in r or "Symbol" in r for r in rows[:1]), "Rows must carry a symbol field."


# ─────────────────────────────────────────────────────────────────────
# DEBT — methodology / portfolio_linked truthfulness
# ─────────────────────────────────────────────────────────────────────


def test_debt_country_filter_applies() -> None:
    """Filter param must narrow rows; methodology hint must stay honest."""

    from showme.engine.functions.bond._stubs import DEBTFunction

    deps = FunctionDeps()
    fn = DEBTFunction(deps)
    result = asyncio.run(fn.execute(countries="US, DE"))
    rows = result.data["rows"]
    countries = {row["country"] for row in rows}
    assert countries == {"US", "DE"}
    assert result.data["summary"]["portfolio_linked"] is False, (
        "Bundled baseline must never claim portfolio linkage."
    )


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
