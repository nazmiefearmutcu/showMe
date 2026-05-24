"""Q4 audit C4: funding rate cost on perpetual positions.

Binance perp charges funding every 8h. ``compute_funding_delta`` pro-rates
the rate over an arbitrary tick interval so a 60s tick deducts the right
60s slice.
"""
from __future__ import annotations

import pytest

from showme.strategies.sizing import compute_funding_delta


def test_long_pays_positive_funding_rate():
    # $10k notional, 0.01% funding rate per 8h, dt = 8h → pays exactly notional × 0.0001.
    delta = compute_funding_delta(
        position_notional=10_000.0, funding_rate=0.0001,
        dt_seconds=8 * 3600.0, side="long",
    )
    assert delta == pytest.approx(1.0)  # 10k × 0.0001 × 1


def test_short_receives_positive_funding_rate():
    # Same as above but short: sign flipped — short RECEIVES from long.
    delta = compute_funding_delta(
        position_notional=10_000.0, funding_rate=0.0001,
        dt_seconds=8 * 3600.0, side="short",
    )
    assert delta == pytest.approx(-1.0)  # negative = received


def test_pro_rated_per_tick():
    # 60s tick = 60/28800 of the full 8h interval. Long pays a tiny slice.
    full_charge = 10_000.0 * 0.0001
    expected = full_charge * (60.0 / (8 * 3600.0))
    delta = compute_funding_delta(
        position_notional=10_000.0, funding_rate=0.0001,
        dt_seconds=60.0, side="long",
    )
    assert delta == pytest.approx(expected)


def test_dt_clamped_at_interval():
    # dt > interval shouldn't double-charge — exchange only charges once per 8h.
    delta_double = compute_funding_delta(
        position_notional=10_000.0, funding_rate=0.0001,
        dt_seconds=16 * 3600.0, side="long",
    )
    delta_single = compute_funding_delta(
        position_notional=10_000.0, funding_rate=0.0001,
        dt_seconds=8 * 3600.0, side="long",
    )
    assert delta_double == pytest.approx(delta_single)


def test_zero_rate_returns_zero():
    delta = compute_funding_delta(
        position_notional=10_000.0, funding_rate=0.0,
        dt_seconds=8 * 3600.0,
    )
    assert delta == 0.0


def test_zero_notional_returns_zero():
    delta = compute_funding_delta(
        position_notional=0.0, funding_rate=0.0001,
        dt_seconds=8 * 3600.0,
    )
    assert delta == 0.0


def test_btc_long_one_week_realistic_drag():
    # Realistic scenario from the audit: 7-day BTC long, average funding 0.01% per 8h.
    # 7 days = 21 funding events. notional=10k.
    # Total drag ≈ 10000 * 0.0001 * 21 = $21 over the week ≈ 0.21% of notional.
    one_event = compute_funding_delta(
        position_notional=10_000.0, funding_rate=0.0001,
        dt_seconds=8 * 3600.0, side="long",
    )
    total = one_event * 21
    assert total == pytest.approx(21.0)
