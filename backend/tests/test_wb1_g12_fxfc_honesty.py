"""FXFC honesty: band vol, confidence score and spot freshness.

FXFC#1  The "confidence" score was 78 - 9*T, a tenor-only constant that
        read as model confidence. It is removed from the rows.
FXFC#3  Band vol defaulted to a flat 0.085 for every pair. The bands now use
        live realized FX vol per tenor (the shared OVDV term structure), an
        explicit vol_annualized input, or null when neither is available.
FXFC#4  A yfinance spot fetched while the FX market is closed (weekend) was
        labelled live with no timing. The fetch time and an off-session
        warning are now returned.

Network is patched: no provider is called.
"""
from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone

import pytest

from showme.engine.functions.fx import _funcs as fx
from showme.engine.functions.fx._funcs import FXFCFunction


def _run(coro):
    return asyncio.run(coro)


def _closes(n: int = 400, start: float = 1.10, step: float = 0.002) -> list[float]:
    """Deterministic ~0.2% daily moves: realized vol is about 3 to 4 percent."""
    out = [start]
    for i in range(1, n):
        sign = 1.0 if (i // 3) % 2 == 0 else -1.0
        out.append(out[-1] * math.exp(sign * step))
    return out


def _realized_vol_1m(closes: list[float]) -> float:
    rets = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]
    win = rets[-21:]
    mean = sum(win) / len(win)
    var = sum((r - mean) ** 2 for r in win) / len(win)
    return math.sqrt(var) * math.sqrt(252.0)


@pytest.fixture
def live_spot(monkeypatch):
    async def _spot(fn, pair, params, quote_info=None):  # noqa: ARG001
        return 1.1143, "yfinance", "live_yfinance_quote"

    monkeypatch.setattr(fx, "_resolve_spot", _spot)
    return _spot


@pytest.fixture
def live_history(monkeypatch):
    async def _close_series(fn, pair, params):  # noqa: ARG001
        return _closes()

    monkeypatch.setattr(fx, "_close_series", _close_series)


@pytest.fixture
def no_history(monkeypatch):
    async def _close_series(fn, pair, params):  # noqa: ARG001
        return []

    monkeypatch.setattr(fx, "_close_series", _close_series)


def test_confidence_score_is_not_emitted(live_spot, live_history):
    """FXFC#1: the tenor-only confidence heuristic is gone from rows and dictionary."""
    result = _run(FXFCFunction().execute(pair="EURUSD", r_base=0.035, r_quote=0.045))
    for row in result.data["forecast"]:
        assert "confidence" not in row
    assert "confidence" not in result.data["field_dictionary"]


def test_band_vol_is_live_realized_not_flat_default(live_spot, live_history):
    """FXFC#3: bands use realized vol for the tenor, not 0.085."""
    result = _run(FXFCFunction().execute(pair="EURUSD", r_base=0.035, r_quote=0.045))
    data = result.data
    assert data["vol_source"] == "live_realized_vol"
    assert data["status"] == "ok"

    expected_1m = _realized_vol_1m(_closes())
    assert data["vol_annualized"] == pytest.approx(expected_1m, rel=1e-4)
    assert data["vol_annualized"] != pytest.approx(0.085)

    row_1m = next(r for r in data["forecast"] if r["horizon"] == "1M")
    t = row_1m["tenor_years"]
    spot = data["spot"]
    half_band = row_1m["upper_band"] - row_1m["forecast"]
    assert half_band == pytest.approx(spot * row_1m["vol_annualized"] * math.sqrt(t), abs=1e-5)
    assert row_1m["vol_annualized"] != pytest.approx(0.085)


def test_no_history_gives_null_bands_not_a_constant(live_spot, no_history):
    """FXFC#3: without realized vol the bands are null and say why; no 8.5% is used."""
    result = _run(FXFCFunction().execute(pair="EURUSD", r_base=0.035, r_quote=0.045))
    data = result.data
    assert data["status"] == "bands_unavailable"
    assert data["vol_source"] == "none"
    assert data["vol_annualized"] is None
    assert data["reason"]
    for row in data["forecast"]:
        assert row["lower_band"] is None
        assert row["upper_band"] is None
        # The CIP forward itself does not need vol and is still served.
        assert row["forecast"] is not None
    assert any("realized vol" in w or "vol" in w for w in result.warnings)


def test_explicit_vol_input_is_used_and_labelled(live_spot, no_history):
    result = _run(FXFCFunction().execute(pair="EURUSD", r_base=0.035, r_quote=0.045, vol_annualized=0.07))
    data = result.data
    assert data["vol_source"] == "user_inputs"
    assert data["vol_annualized"] == pytest.approx(0.07)
    assert data["status"] == "ok"


def test_live_false_does_not_fetch_realized_vol(live_spot, monkeypatch):
    called = {"n": 0}

    async def _close_series(fn, pair, params):  # noqa: ARG001
        called["n"] += 1
        return _closes()

    monkeypatch.setattr(fx, "_close_series", _close_series)
    result = _run(FXFCFunction().execute(pair="EURUSD", r_base=0.035, r_quote=0.045, live=False))
    assert called["n"] == 0
    assert result.data["vol_annualized"] is None
    assert result.data["status"] == "bands_unavailable"


def test_spot_fetch_time_is_returned(live_spot, live_history):
    """FXFC#4: the spot carries the time it was fetched."""
    result = _run(FXFCFunction().execute(pair="EURUSD", r_base=0.035, r_quote=0.045))
    stamp = result.data["spot_fetched_at"]
    assert datetime.fromisoformat(stamp).tzinfo is not None
    assert "fx_market_open_at_fetch" in result.data


def test_weekend_yfinance_spot_is_flagged(live_spot, live_history, monkeypatch):
    """FXFC#4: a Sunday pre-open yfinance quote is not presented as a live print."""
    sunday_early = datetime(2026, 11, 8, 0, 7, tzinfo=timezone.utc)  # Sunday, before 22:00 UTC
    monkeypatch.setattr(fx, "_fxfc_now", lambda: sunday_early)
    result = _run(FXFCFunction().execute(pair="EURUSD", r_base=0.035, r_quote=0.045))
    assert result.data["fx_market_open_at_fetch"] is False
    assert any("market is closed" in w for w in result.warnings), result.warnings


def test_weekday_yfinance_spot_is_not_flagged(live_spot, live_history, monkeypatch):
    tuesday = datetime(2026, 11, 10, 14, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(fx, "_fxfc_now", lambda: tuesday)
    result = _run(FXFCFunction().execute(pair="EURUSD", r_base=0.035, r_quote=0.045))
    assert result.data["fx_market_open_at_fetch"] is True
    assert all("market is closed" not in w for w in result.warnings)


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        (datetime(2026, 11, 6, 21, 59, tzinfo=timezone.utc), True),   # Friday, before close
        (datetime(2026, 11, 6, 22, 0, tzinfo=timezone.utc), False),   # Friday close
        (datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc), False),   # Saturday
        (datetime(2026, 11, 8, 21, 59, tzinfo=timezone.utc), False),  # Sunday, before open
        (datetime(2026, 11, 8, 22, 0, tzinfo=timezone.utc), True),    # Sunday open
        (datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc), True),     # Monday
    ],
)
def test_fx_market_session_helper(when, expected):
    assert fx._fx_market_open(when) is expected


# FXFC#2: the CIP forward must not be computed from the 2024-06 reference
# policy-rate table (or the 0.04 unknown-currency fallback). Without explicit
# r_base / r_quote inputs the forward is null and the envelope says why.


def test_default_run_has_no_forward_from_reference_rate_table(live_spot, live_history):
    """FXFC#2: no policy rate supplied -> no CIP forward, no table constant."""
    result = _run(FXFCFunction().execute(pair="EURUSD"))
    data = result.data
    assert data["status"] == "needs_input"
    assert data["base_rate"] is None
    assert data["quote_rate"] is None
    assert data["rate_source"] == "none"
    for row in data["forecast"]:
        assert row["forecast"] is None
        assert row["forward_points"] is None
        assert row["lower_band"] is None
        assert row["upper_band"] is None
    assert any("r_base" in w or "policy rate" in w for w in result.warnings), result.warnings
    assert "reference_policy_rate" not in result.sources


def test_forward_uses_user_supplied_rates_and_is_labelled(live_spot, live_history):
    """FXFC#2: explicit rates drive the CIP forward and are labelled user_inputs."""
    result = _run(FXFCFunction().execute(pair="EURUSD", r_base=0.035, r_quote=0.045))
    data = result.data
    assert data["status"] == "ok"
    assert data["rate_source"] == "user_inputs"
    assert data["base_rate"] == pytest.approx(0.035)
    assert data["quote_rate"] == pytest.approx(0.045)
    row_3m = next(r for r in data["forecast"] if r["horizon"] == "3M")
    expected = fx._forward(data["spot"], 0.035, 0.045, row_3m["tenor_years"])
    assert row_3m["forecast"] == pytest.approx(round(expected, 6), abs=1e-6)
    assert "user_inputs_policy_rates" in result.sources


def test_one_missing_rate_still_gives_no_forward(live_spot, live_history):
    """FXFC#2: a single supplied rate is not enough; no half-substituted forward."""
    result = _run(FXFCFunction().execute(pair="EURUSD", r_quote=0.045))
    assert result.data["status"] == "needs_input"
    assert all(row["forecast"] is None for row in result.data["forecast"])


def test_unknown_currency_gets_no_0_04_fallback(live_spot, live_history):
    """FXFC#2: exotic pairs do not receive the 0.04 generic rate either."""
    result = _run(FXFCFunction().execute(pair="USDMXN", r_base=0.045))
    assert result.data["quote_rate"] is None
    assert all(row["forecast"] is None for row in result.data["forecast"])
