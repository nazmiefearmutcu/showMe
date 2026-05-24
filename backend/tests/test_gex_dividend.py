"""D03-2026-05-24 (H7+H8): GEX dividend yield + intraday 0DTE T.

H7: bs_gamma now accepts ``q`` and includes ``-q`` in the drift + the
    ``exp(-qT)`` discount on the gamma.
H8: 0DTE expiries get fractional-day T instead of being clamped to 0
    once the calendar date arrives.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.services.gamma_exposure import bs_gamma, chain_gex  # noqa: E402


def test_bs_gamma_div_yield_changes_result() -> None:
    """Same option: q=0 vs q=0.10 — dividend yield should change gamma
    via the e^(-qT) factor + drift shift. (NB: at the special point
    r-q=0.5σ² the two effects can cancel exactly; we use q=0.10 to
    avoid that degenerate setup.)"""
    g_no_div = bs_gamma(100, 100, 0.20, 1.0, 0.045, 0.0)
    g_div = bs_gamma(100, 100, 0.20, 1.0, 0.045, 0.10)
    assert g_div != g_no_div  # not a no-op
    # 1-yr 10% div => exp(-qT) factor ≈ 0.905 is the dominant effect.
    assert g_div < g_no_div  # at q=0.10, drag dominates the d1 shift


def test_chain_gex_dividend_threaded_through() -> None:
    """chain_gex accepts div_yield and passes it to bs_gamma."""
    calls = [{"strike": 100, "openInterest": 1000,
              "impliedVolatility": 0.20, "expiry": "2026-12-31"}]
    puts: list = []
    spot = 100
    res_no_div = chain_gex(spot=spot, calls=calls, puts=puts, rate=0.045,
                           div_yield=0.0)
    res_div = chain_gex(spot=spot, calls=calls, puts=puts, rate=0.045,
                        div_yield=0.10)
    # div_yield must influence GEX, not silently be discarded.
    assert res_div["call_gex_total"] != res_no_div["call_gex_total"]


def test_0dte_intraday_t_is_finite() -> None:
    """0DTE call (expiry == today) used to be T=0 → gamma=0. Now it's
    a finite intraday slice."""
    today_str = datetime.now(timezone.utc).date().isoformat()
    calls = [{"strike": 100, "openInterest": 5000,
              "impliedVolatility": 0.40, "expiry": today_str}]
    res = chain_gex(spot=100, calls=calls, puts=[], rate=0.045)
    # call_gex_total should be NON-ZERO; old code returned 0 because
    # _T defaulted to 0 for expiry==today (today - today = 0 days).
    assert res["call_gex_total"] != 0


def test_explicit_T_overrides_expiry() -> None:
    """If caller passes T directly, no expiry parsing happens."""
    calls = [{"strike": 100, "openInterest": 1000,
              "impliedVolatility": 0.30, "T": 0.5}]  # 6 months
    res = chain_gex(spot=100, calls=calls, puts=[], rate=0.045)
    assert res["call_gex_total"] != 0
