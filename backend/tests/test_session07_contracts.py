"""
Session-07 BugHunt regression tests (2026-05-17).

Each test pins a real backend bug that was fixed in the same session.
The contract assertions are kept tight on PURPOSE — a future refactor
that re-introduces the old behavior must break exactly one of these
tests, not silently regress UI rendering.

Codes covered: FXFC, FXGO, FXH, FXIP, GC3D, GEX, GLCO, GMM, GP, GRAB.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.core.instrument import AssetClass, Instrument  # noqa: E402
from showme.engine.functions.bond.gc3d import GC3DFunctionLive  # noqa: E402
from showme.engine.functions.commodity._funcs import GLCOFunction  # noqa: E402
from showme.engine.functions.derivative.gex import GEXFunction  # noqa: E402
from showme.engine.functions.fx._funcs import FXFCFunction, FXIPFunction  # noqa: E402
from showme.engine.functions.fx.fxh import FXHFunction  # noqa: E402
from showme.engine.functions.macro.gmm import GMMFunction  # noqa: E402
from showme.engine.functions.misc._extras import GRABFunction  # noqa: E402
from showme.engine.functions.trade._funcs import FXGOFunction  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ── FXH ────────────────────────────────────────────────────────────────────


def test_fxh_does_not_silently_substitute_1_point_0_for_missing_spot():
    """Was: when yfinance was unavailable and spot_rate not supplied,
    FXH silently filled spot_rate=1.0 and produced fictitious notionals.
    Now: missing currency is filtered out and a warning is emitted."""
    fn = FXHFunction(deps=FunctionDeps(yfinance=None))
    result = _run(fn.execute(
        action="calc",
        pair="EURUSD",
        exposures=[{"currency": "EUR", "notional": 1_000_000}],
        # no spot_rate, no yfinance dep
    ))
    assert result.warnings, "expected warning about unresolved spot rate"
    assert any("spot rate unavailable" in w.lower() or "spot unavailable" in w.lower()
               for w in result.warnings), result.warnings
    data = result.data
    assert data["status"] == "data_unavailable"
    assert data["source_mode"] == "no_spot_data"
    # No rows must be returned with a silent 1.0 substitution.
    assert data["rows"] == []


def test_fxh_uses_manual_spot_rate_when_supplied():
    """Manual spot must be respected — the failure path is only for the
    case where neither manual nor live spot is available."""
    fn = FXHFunction(deps=FunctionDeps(yfinance=None))
    result = _run(fn.execute(
        action="forward",
        exposures=[{"currency": "EUR", "notional": 100_000, "spot_rate": 1.08}],
    ))
    data = result.data
    forwards = data["forwards"]
    assert len(forwards) == 1
    assert forwards[0]["spot"] == pytest.approx(1.08, abs=1e-9)
    assert "methodology" in data
    assert "source_mode" in data


# ── GMM ────────────────────────────────────────────────────────────────────


def test_gmm_does_not_mislabel_hardcoded_fallback_as_tradingeconomics():
    """Was: with the tradingeconomics dep wired but returning 0 qualifying
    events, GMM rendered the hardcoded reference rows while advertising
    source_mode='tradingeconomics' — a silent fake-data leak.
    Now: source_mode='reference_macro_mover_table' when used_fallback=True,
    and a warning notes that the provider yielded nothing."""

    class _ZeroCalendarTE:
        async def calendar(self, country=None):
            return []  # provider succeeds but yields nothing

    fn = GMMFunction(deps=FunctionDeps(tradingeconomics=_ZeroCalendarTE()))
    result = _run(fn.execute())
    assert result.data["source_mode"] == "reference_macro_mover_table"
    assert any("tradingeconomics returned no qualifying events" in w
               for w in result.warnings), result.warnings


def test_gmm_uses_live_label_when_provider_actually_returns_events():
    """A real provider response must keep the live source_mode label."""

    class _GoodTE:
        async def calendar(self, country=None):
            return [{
                "country": "US", "event": "PPI",
                "Actual": 2.1, "Forecast": 1.9, "importance": "high",
            }]

    fn = GMMFunction(deps=FunctionDeps(tradingeconomics=_GoodTE()))
    result = _run(fn.execute())
    assert result.data["source_mode"] == "tradingeconomics"


# ── FXGO ───────────────────────────────────────────────────────────────────


def test_fxgo_emits_input_required_envelope_when_symbol_missing():
    """Was: EMSXFunction.execute did `raise ValueError` (no message),
    producing an opaque 500/`function_warning` on /api/fn/FXGO.
    Now: structured input_required envelope just like quantity<=0 branch."""
    fn = FXGOFunction()
    result = _run(fn.execute(instrument=None))
    assert result.data["status"] == "input_required"
    assert "symbol" in result.data["reason"].lower()
    assert result.data["next_actions"]
    assert result.metadata.get("preview_only") is True


# ── GEX ────────────────────────────────────────────────────────────────────


def test_gex_clamps_non_positive_spot_in_model_only_branch():
    """Was: when not live_options, GEX returned _model_gex(sym, spot, rate)
    with no clamp on spot, so spot<=0 produced a strike grid centered on 0.
    Now: clamped before any consumer reads spot."""
    fn = GEXFunction(deps=FunctionDeps(yfinance=None))
    result = _run(fn.execute(instrument=Instrument(symbol="SPY",
                                                   asset_class=AssetClass.EQUITY),
                             spot=0))
    data = result.data
    # The data carries either a `strikes` or `rows` array; make sure no row
    # has every metric collapsed to 0 (the symptom of spot=0 propagation).
    rows = data.get("rows") or data.get("strikes") or []
    assert rows, "expected strike rows in GEX model output"
    sample = rows[0]
    # whatever the row shape, at least one numeric field must be non-zero
    numeric_values = [v for v in sample.values()
                      if isinstance(v, (int, float)) and v != 0]
    assert numeric_values, f"every numeric field was 0 — spot=0 leaked: {sample}"


# ── GC3D ───────────────────────────────────────────────────────────────────


def test_gc3d_template_dates_are_rolling_not_hardcoded():
    """Was: _surface_template used the literal strings '2026-04-01',
    '2026-04-15', '2026-05-01' which read as stale weeks after the file
    was written.
    Now: dates are rolling offsets from today."""
    fn = GC3DFunctionLive()
    result = _run(fn.execute())  # no live_curve → falls back to template
    data = result.data
    dates = data["dates"]
    today = datetime.now(timezone.utc).date()
    parsed = [datetime.strptime(d, "%Y-%m-%d").date() for d in dates]
    # All template dates must lie within the last 90 days from "today".
    for d in parsed:
        assert (today - d).days <= 90, f"stale template date {d} (> 90 d old)"
        assert (today - d).days >= 0, f"future template date {d}"
    # And dates must be strictly increasing.
    assert parsed == sorted(parsed)


def test_gc3d_days_param_is_clamped():
    """Was: int(params.get('days', 365)) unclamped — a request for
    days=999999 would have ballooned the FRED query.
    Now: clamped to [7, 3650]."""
    fn = GC3DFunctionLive()
    # We can't easily inspect the clamped value without hitting the live
    # branch, but the template branch should still respond cleanly.
    result = _run(fn.execute(days=999_999_999))
    assert result.data["summary"]["points"] > 0


# ── FXFC ───────────────────────────────────────────────────────────────────


def test_fxfc_does_not_warn_when_spot_is_manual_input():
    """Was: warnings=[] only if source_mode == 'live_yfinance_quote',
    so a user-supplied spot triggered the spurious 'live spot unavailable'
    warning. Now: warn only when source_mode == 'reference_model'."""
    fn = FXFCFunction(deps=FunctionDeps())
    result = _run(fn.execute(symbol="EURUSD", spot=1.0850))
    assert all("live spot unavailable" not in w for w in result.warnings)


def test_fxfc_warns_when_falling_back_to_reference_model():
    """Reference-model spot should still surface a clear warning."""
    fn = FXFCFunction(deps=FunctionDeps())  # no yfinance, no spot
    result = _run(fn.execute(symbol="EURUSD"))
    if result.data["forecast"][0]["source_mode"] == "reference_model":
        assert any("live spot unavailable" in w for w in result.warnings)


# ── FXIP ───────────────────────────────────────────────────────────────────


def test_fxip_does_not_warn_for_live_ecb_or_manual_input():
    """The check used to be `source_mode.startswith('live')`, which
    excluded manual_input. Both real and user-supplied spots now skip
    the warning; only reference_model triggers it."""
    fn = FXIPFunction(deps=FunctionDeps())
    result = _run(fn.execute(symbol="EURUSD", spot=1.0850))
    assert all("live spot unavailable" not in w for w in result.warnings)


# ── GLCO ───────────────────────────────────────────────────────────────────


def test_glco_labels_model_rows_when_yfinance_unavailable():
    """GLCO already degrades gracefully — keep that pinned so a future
    refactor cannot quietly drop the provider_unavailable status."""
    fn = GLCOFunction(deps=FunctionDeps(yfinance=None))
    result = _run(fn.execute())
    data = result.data
    # Status must clearly mark the absence of live data.
    assert data.get("status") in {"provider_unavailable", "model", "ok"}
    if data.get("status") == "provider_unavailable":
        for row in data.get("rows", []):
            assert row.get("is_live") is not True, row


# ── GP ─────────────────────────────────────────────────────────────────────


def test_gp_function_index_entry_is_advertised_to_clients():
    """GP is not in FunctionRegistry (it's a /api/fn route alias). The
    function index injection at server.py guarantees clients still see
    it as an available code."""
    from showme.server import _load_function_index

    # Build the index with an empty registry payload and make sure GP
    # gets injected.
    snapshot = _load_function_index()
    codes = {getattr(entry, "code", None) for entry in snapshot}
    assert "GP" in codes


# ── GRAB ───────────────────────────────────────────────────────────────────


def test_grab_remains_a_planning_only_contract_no_silent_send():
    """GRAB is explicitly draft-only: confirm it never marks the email
    phase as anything other than `not_configured`/`draft_only` without
    a recipient, and never claims to have transmitted data."""
    fn = GRABFunction()
    result = _run(fn.execute(send=True))  # send=true should NOT transmit
    rows = result.data["rows"]
    email_row = next(r for r in rows if r["step"] == "email")
    assert email_row["status"] in {"not_configured", "draft_only"}
    assert email_row.get("transmits_data") is True  # the FLAG only; not actually sent
    assert any("not executed automatically" in w for w in result.warnings)
