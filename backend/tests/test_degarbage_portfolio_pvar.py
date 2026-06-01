"""Live de-garbage test for PVAR (Portfolio VaR & ES via yfinance, keyless).

Covers: PVAR (showme.engine.functions.portfolio.pvar.PVARFunction).

Asserts the handler returns real, computed VaR/ES rows (no longer the old
hardcoded BTC/AAPL constants: notional 100000, vol 0.22, var -0.025) when
the network is available, and degrades to a clean provider_unavailable /
empty shape offline so the suite stays green without connectivity.
"""
from __future__ import annotations

import asyncio

import pytest

from showme.engine.functions.portfolio.pvar import PVARFunction


def _run(coro):
    # ``asyncio.get_event_loop()`` raises ``RuntimeError: There is no current
    # event loop`` on Python 3.10+ when no loop is set in the main thread.
    # ``asyncio.run`` creates, drives and closes a fresh loop deterministically.
    return asyncio.run(coro)


# The exact canned constants the old _sample_pvar stub returned. If any of
# these reappear as the headline numbers, the stub has crept back in.
_OLD_CONSTANTS = {100000.0, 0.22, -0.025, -2500.0}


def test_pvar_live_or_graceful():
    handler = PVARFunction()
    result = _run(handler.execute(confidence_level=0.99, horizon="1d", method="historical"))
    data = result.data
    status = data.get("status")
    assert status in {"ok", "modeled", "empty", "provider_unavailable"}

    # Methodology must always be present and describe real computation.
    assert data.get("methodology"), "methodology must be present"
    assert "field_dictionary" in data

    if status in {"ok", "modeled"}:
        rows = data.get("rows") or []
        assert rows, "ok status must carry real per-position rows"
        # Every row must be a real computed dict with a symbol + contract keys.
        for r in rows:
            assert r.get("symbol")
            assert "component_var" in r
            assert "weight" in r
        # Headline VaR/ES must be real floats, not the old constants.
        var = data.get("var")
        es = data.get("expected_shortfall")
        assert isinstance(var, float) and var == var  # not None / not NaN
        assert isinstance(es, float)
        assert es >= var, "ES must dominate VaR for the same confidence"
        assert var not in _OLD_CONSTANTS, "headline VaR is a stale hardcoded constant"
        assert abs(var) > 0.0, "VaR should be a non-trivial loss number"
        # Provenance + contract fields the manifest requires.
        for key in ("as_of", "confidence_level", "horizon", "method", "data_mode"):
            assert key in data, f"missing contract field {key}"
        assert "yfinance" in [s.lower() for s in result.sources] or status == "modeled"
        # Loss-distribution series for the DISTRIBUTION chart pane.
        assert isinstance(data.get("series"), list)
    else:
        # Offline / rate-limited / no positions: must degrade cleanly.
        assert data.get("reason") or data.get("next_actions")
        assert data.get("var") is None


def test_pvar_higher_confidence_higher_var_when_live():
    """VaR(99) >= VaR(95) on the same portfolio + window (semantic invariant).

    Skips the comparison cleanly when the provider is unavailable.
    """
    handler = PVARFunction()
    r95 = _run(handler.execute(confidence_level=0.95, horizon="1d", method="parametric"))
    r99 = _run(handler.execute(confidence_level=0.99, horizon="1d", method="parametric"))
    if r95.data.get("status") not in {"ok", "modeled"} or r99.data.get("status") not in {"ok", "modeled"}:
        pytest.skip("provider unavailable; skipping live VaR-monotonicity check")
    var95 = r95.data.get("var")
    var99 = r99.data.get("var")
    assert var95 is not None and var99 is not None
    assert var99 >= var95 - 1e-6, "higher confidence must not lower parametric VaR"


def test_pvar_parametric_scales_with_horizon_when_live():
    """Parametric VaR grows with horizon and lands near root-t.

    The manifest formula keeps a drift term (VaR = -muDt + z*sigma*sqrt(Dt)),
    so the realised 10d/1d ratio sits between the pure-vol root-t value
    (~3.16) and the linear-drift bound; we assert it is materially > 1 and
    in a sane band rather than pinning it to an idealised driftless number.
    """
    handler = PVARFunction()
    r1 = _run(handler.execute(confidence_level=0.99, horizon="1d", method="parametric"))
    r10 = _run(handler.execute(confidence_level=0.99, horizon="10d", method="parametric"))
    if r1.data.get("status") not in {"ok", "modeled"} or r10.data.get("status") not in {"ok", "modeled"}:
        pytest.skip("provider unavailable; skipping horizon scaling check")
    v1 = r1.data.get("var")
    v10 = r10.data.get("var")
    if not v1:
        pytest.skip("degenerate (zero) 1d VaR; cannot test ratio")
    ratio = v10 / v1
    # 10d VaR must be larger than 1d and within a sane band around root-t.
    assert ratio > 1.0, f"10d VaR must exceed 1d VaR, got ratio {ratio}"
    assert 2.0 < ratio < 11.0, f"parametric VaR horizon scaling out of band: {ratio}"
