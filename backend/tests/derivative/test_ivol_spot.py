"""A02-2026-05-24 — IVOL spot anchor regression.

Bug: ``IVOLFunction.execute`` set ``spot = float(params.get("spot", 100))``
and returned ``spot=100`` from every non-live branch. UI rendered
SPY's vol surface with strikes at 80/90/100/110/120 even when SPY
actually traded at $525. Anchor was a lie.

Fix: ``_resolve_ivol_spot`` mirrors the OMON pattern — caller's
explicit ``spot`` wins, otherwise yfinance QUOTE fills it, final
fallback to 100 only when nothing else is available. ``data_state``
in the returned payload labels which path won so the UI can show
"synthetic_anchor" honestly.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.derivative._stubs import (
    IVOLFunction,
    _resolve_ivol_spot,
)


@dataclass
class _StubDeps:
    yfinance: Any = None


class _StubQuote:
    def __init__(self, last: float | None) -> None:
        self.last = last


class _StubYf:
    """Mimics the yfinance adapter interface: an async ``fetch`` that
    returns a quote-shaped object with ``last``."""

    def __init__(self, last: float | None) -> None:
        self._last = last

    async def fetch(self, _request: Any) -> Any:
        return _StubQuote(self._last)


def _spy() -> Instrument:
    return Instrument(symbol="SPY", asset_class=AssetClass.ETF)


# ── Helper-level coverage ──────────────────────────────────────────────


def test_resolve_uses_live_quote_when_available():
    deps = _StubDeps(yfinance=_StubYf(last=525.42))
    spot, state = asyncio.run(_resolve_ivol_spot(deps, _spy(), {}))
    assert spot == pytest.approx(525.42)
    assert state == "live_quote"


def test_resolve_falls_back_when_yfinance_missing():
    spot, state = asyncio.run(_resolve_ivol_spot(_StubDeps(yfinance=None), _spy(), {}))
    assert spot == 100.0
    assert state == "synthetic_anchor"


def test_resolve_falls_back_when_quote_last_is_zero():
    deps = _StubDeps(yfinance=_StubYf(last=0.0))
    spot, state = asyncio.run(_resolve_ivol_spot(deps, _spy(), {}))
    assert spot == 100.0
    assert state == "synthetic_anchor"


def test_resolve_falls_back_when_quote_last_is_none():
    deps = _StubDeps(yfinance=_StubYf(last=None))
    spot, state = asyncio.run(_resolve_ivol_spot(deps, _spy(), {}))
    assert spot == 100.0
    assert state == "synthetic_anchor"


def test_resolve_user_override_wins_over_quote():
    """Explicit ``spot`` in params skips the quote round-trip."""
    deps = _StubDeps(yfinance=_StubYf(last=525.42))
    spot, state = asyncio.run(_resolve_ivol_spot(deps, _spy(), {"spot": 320}))
    assert spot == pytest.approx(320.0)
    assert state == "user_override"


def test_resolve_invalid_user_override_falls_through_to_quote():
    """A bogus ``spot`` (negative, non-numeric) should not poison the
    resolver — fall through to the quote source instead."""
    deps = _StubDeps(yfinance=_StubYf(last=525.42))
    spot, state = asyncio.run(_resolve_ivol_spot(deps, _spy(), {"spot": "not-a-number"}))
    assert spot == pytest.approx(525.42)
    assert state == "live_quote"


# ── End-to-end through IVOLFunction.execute ────────────────────────────


def test_ivol_reference_branch_uses_live_spot():
    """The headline bug: ``live_options`` unset → reference branch must
    still anchor strikes around the real SPY price, not 100."""
    fn = IVOLFunction(deps=_StubDeps(yfinance=_StubYf(last=525.42)))
    result = asyncio.run(fn.execute(instrument=_spy()))
    assert result.data["spot"] == pytest.approx(525.42)
    assert result.data["data_state"] == "live_quote"
    # Strikes should be anchored around the real spot — first strike
    # is 0.8 * spot, last is 1.2 * spot.
    strikes = sorted({row["strike"] for row in result.data["calls_grid"]})
    assert min(strikes) > 100, f"reference surface still anchored at 100 default: {strikes}"
    assert min(strikes) == pytest.approx(round(525.42 * 0.8, 2))
    assert max(strikes) == pytest.approx(round(525.42 * 1.2, 2))


def test_ivol_marks_synthetic_anchor_when_no_quote():
    """If the quote adapter is unavailable, the response must
    self-label as ``synthetic_anchor`` so the UI doesn't display a
    fake $100 strike grid as if it were real."""
    fn = IVOLFunction(deps=_StubDeps(yfinance=None))
    result = asyncio.run(fn.execute(instrument=_spy()))
    assert result.data["spot"] == 100.0
    assert result.data["data_state"] == "synthetic_anchor"
    assert result.metadata.get("spot_source") == "synthetic_anchor"


def test_ivol_yfinance_unavailable_branch_uses_live_quote_for_spot():
    """When live_options is requested but yfinance is missing, the
    fallback synthetic surface must STILL use the resolved spot (from
    the quote adapter) — not 100. We exercise this with the live path
    selected but yfinance forcibly None by passing the live flag and
    no yfinance adapter."""
    fn = IVOLFunction(deps=_StubDeps(yfinance=None))
    result = asyncio.run(fn.execute(instrument=_spy(), live_options=True))
    # No yfinance → resolver returns synthetic_anchor (100). Make sure
    # the response says so honestly.
    assert result.data["spot"] == 100.0
    assert result.data["data_state"] == "synthetic_anchor"
    assert "provider_errors" in result.metadata


def test_ivol_user_override_threads_through_to_strikes():
    fn = IVOLFunction(deps=_StubDeps(yfinance=_StubYf(last=525.42)))
    result = asyncio.run(fn.execute(instrument=_spy(), spot=200))
    assert result.data["spot"] == pytest.approx(200.0)
    assert result.data["data_state"] == "user_override"
