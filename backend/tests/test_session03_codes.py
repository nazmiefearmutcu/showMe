"""Session-03 bug-hunt regressions for BTUNE / CACT / CHGS / CRPR / CRVF / COUN.

These pin the specific contract changes made in Session 03:

* BTUNE — live fetch failure surfaces a warning AND flips status to
  `computed_fallback`, instead of silently returning a Sharpe table
  labelled `ok`.
* CACT / CHGS / LITM / APPL — missing instrument raises ``ValueError``
  with a descriptive message so the API envelope can surface a useful
  reason string (it used to raise an empty ``ValueError``).
* CHGS — asset coverage now matches TECH (commodity + bond included);
  previously these two asset classes fell into ``_compatibility_function_result``.
* CRPR — payload now carries an explicit ``status`` field (`reference_baseline`
  for the bundled stub, `user_input` when a ``rating`` block was passed) so the
  contract normalizer cannot mis-tag the stub as live ``ok``.
* CRVF — non-US ``live=True`` no longer claims FRED as the source; the
  fallback path now emits a warning and labels `source_mode="computed_model"`.
* COUN — unknown country emits a warning instead of silently returning a
  generic profile labeled with the requested ISO code.
"""

from __future__ import annotations

import asyncio

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.bond._stubs import CRPRFunction
from showme.engine.functions.bond.crvf import CRVFFunction
from showme.engine.functions.equity.cact import CACTFunction
from showme.engine.functions.macro.coun import COUNFunction
from showme.engine.functions.misc._bonus import APPLFunction, CHGSFunction, LITMFunction
from showme.engine.functions.portfolio.btune import BTUNEFunction


def _run(coro):
    # Use ``asyncio.run`` so each test runs against a fresh event loop;
    # the previous ``get_event_loop().run_until_complete`` pattern hits
    # ``RuntimeError: no current event loop`` on Python 3.13 once an
    # earlier test closes the implicit loop.
    return asyncio.run(coro)


@pytest.fixture
def deps() -> FunctionDeps:
    return FunctionDeps()


@pytest.fixture
def equity() -> Instrument:
    return Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


# ── BTUNE ─────────────────────────────────────────────────────────────

def test_btune_live_fallback_emits_warning_and_status(deps, equity):
    """When `live=True` is requested but yfinance is unavailable, BTUNE
    must drop to the template path AND tell the client about it via
    `status="computed_fallback"` + a warning."""
    fn = BTUNEFunction(deps)
    res = _run(fn.execute(instrument=equity, live_backtest=True, days=120))
    assert res.data["status"] == "computed_fallback"
    assert res.sources == ["local_backtest_model"]
    assert any("yfinance" in w or "live OHLCV" in w for w in (res.warnings or []))
    assert res.metadata.get("live") is False


def test_btune_no_live_uses_reference_model(deps, equity):
    fn = BTUNEFunction(deps)
    res = _run(fn.execute(instrument=equity))
    assert res.sources == ["local_backtest_model"]
    assert res.data["status"] == "reference"


def test_btune_requires_instrument(deps):
    fn = BTUNEFunction(deps)
    with pytest.raises(ValueError, match="BTUNE requires an instrument symbol"):
        _run(fn.execute(instrument=None))


# ── CACT / LITM / APPL / CHGS — instrument error messages ────────────

def test_cact_requires_instrument(deps):
    with pytest.raises(ValueError, match="CACT requires an instrument symbol"):
        _run(CACTFunction(deps).execute(instrument=None))


def test_chgs_requires_instrument(deps):
    with pytest.raises(ValueError, match="CHGS requires an instrument symbol"):
        _run(CHGSFunction(deps).execute(instrument=None))


def test_litm_requires_instrument(deps):
    with pytest.raises(ValueError, match="LITM requires an instrument symbol"):
        _run(LITMFunction(deps).execute(instrument=None))


def test_appl_requires_instrument(deps):
    with pytest.raises(ValueError, match="APPL requires an instrument symbol"):
        _run(APPLFunction(deps).execute(instrument=None))


# ── CHGS asset_classes ───────────────────────────────────────────────

def test_chgs_supports_commodity_and_bond_like_tech():
    chgs = CHGSFunction
    asset_codes = {a.value for a in chgs.asset_classes}
    assert "COMMODITY" in asset_codes
    assert "BOND" in asset_codes


# ── CRPR status honesty ──────────────────────────────────────────────

def test_crpr_default_payload_reference_baseline(deps):
    """de-garbage 2026-06-01: CRPR no longer ships a hardcoded AA+/Aa1 reference
    table labelled ``reference_baseline``. The default issuer (US Treasury) is a
    sovereign with no SEC CIK, so CRPR's financial-derived model does not apply
    and it returns an HONESTLY-LABELLED sovereign reference profile
    (``source_mode='sovereign_reference'``) with a warning saying the SEC model
    is not applicable — never a silent fake-data table tagged plain ``ok``."""
    res = _run(CRPRFunction(deps).execute(instrument=None))
    assert res.data["status"] == "ok"
    assert res.data["summary"]["source_mode"] == "sovereign_reference"
    # The label must honestly disclose it is a reference / non-model profile.
    assert any("reference sovereign profile" in w or "not applicable" in w
               for w in (res.warnings or [])), res.warnings


def test_crpr_user_input_overrides_status(deps):
    """de-garbage 2026-06-01: an operator-supplied ``rating`` block still wins —
    CRPR echoes it verbatim with ``source_mode='user_input'`` and never lets a
    SEC-derived or reference value overwrite the override. (Status is the
    canonical ``ok`` now; honesty is carried by ``source_mode``.)"""
    rating = {"sp": "BB", "moodys": "Ba1", "fitch": "BB", "outlook": "negative", "watch": "review"}
    res = _run(CRPRFunction(deps).execute(rating=rating, issuer="ACME"))
    assert res.data["status"] == "ok"
    assert res.data["summary"]["source_mode"] == "user_input"
    assert res.data["rows"][0]["rating"] == "BB"


# ── CRVF country + source honesty ────────────────────────────────────

def test_crvf_non_us_live_admits_fallback(deps):
    res = _run(CRVFFunction(deps).execute(country="DE", live=True))
    assert res.sources == ["computed_model"]
    assert res.data["summary"]["source_mode"] == "computed_model"
    assert any("DE" in w or "computed_model" in w for w in res.warnings)


def test_crvf_us_live_without_fred_admits_fallback(deps):
    res = _run(CRVFFunction(deps).execute(country="US", live=True))
    assert res.sources == ["computed_model"]
    assert any("fred" in w.lower() for w in res.warnings)


def test_crvf_no_live_uses_curve_model(deps):
    res = _run(CRVFFunction(deps).execute(country="US"))
    assert res.sources == ["curve_model"]
    assert res.data["summary"]["source_mode"] == "computed_model"


# ── COUN unknown country warning ─────────────────────────────────────

def test_coun_unknown_country_warns(deps):
    res = _run(COUNFunction(deps).execute(country="ZZ"))
    assert any("ZZ" in w for w in (res.warnings or []))
    assert res.metadata.get("country_known") is False


def test_coun_known_country_no_baseline_warning(deps):
    res = _run(COUNFunction(deps).execute(country="US"))
    assert res.metadata.get("country_known") is True
    # No baseline warning for a known country (live=False path).
    assert not any("no curated profile" in w for w in (res.warnings or []))
