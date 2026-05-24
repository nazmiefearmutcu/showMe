"""Q4 audit C3: commission/fees on PnL aggregation.

Default 8bp (Binance taker) per side. ``compute_commission`` charges both
legs so a round-trip $10k notional costs $16 in fees.
"""
from __future__ import annotations

import pytest

from showme.bots.performance import compute_metrics, compute_trades_from_closed
from showme.bots.record import ClosedTrade
from showme.strategies.sizing import (
    DEFAULT_COMMISSION_RATE,
    compute_commission,
)


def test_default_commission_rate_is_8bp():
    assert DEFAULT_COMMISSION_RATE == pytest.approx(0.0008)


def test_compute_commission_charges_both_legs():
    # $10k notional in/out at 8bp = $1.6 per side × 2 = $3.2.
    # Wait: 8bp = 0.0008; 10000 * 0.0008 = $8 per side × 2 = $16.
    fee = compute_commission(
        entry_price=100.0, exit_price=100.0, qty=100.0,
        commission_rate=0.0008,
    )
    assert fee == pytest.approx(16.0)


def test_commission_uses_entry_and_exit_notionals_independently():
    # entry 100 * 1.0 = 100; exit 110 * 1.0 = 110. Total notional 210.
    # 8bp * 210 = 0.168.
    fee = compute_commission(
        entry_price=100.0, exit_price=110.0, qty=1.0,
        commission_rate=0.0008,
    )
    assert fee == pytest.approx(0.168)


def test_zero_commission_returns_zero():
    fee = compute_commission(
        entry_price=100.0, exit_price=100.0, qty=1.0,
        commission_rate=0.0,
    )
    assert fee == 0.0


def test_negative_commission_treated_as_zero():
    fee = compute_commission(
        entry_price=100.0, exit_price=100.0, qty=1.0,
        commission_rate=-0.01,
    )
    assert fee == 0.0


def test_compute_trades_from_closed_preserves_commission_field():
    ct = ClosedTrade(
        entry_timestamp="2026-05-24T00:00:00",
        exit_timestamp="2026-05-24T01:00:00",
        entry_price=100.0, exit_price=110.0, qty=1.0,
        side="long", pnl=10.0,
        bar_index_entry=0, bar_index_exit=1,
        commission_paid=0.168, funding_paid=0.0,
        net_pnl=10.0 - 0.168,
    )
    [trade] = compute_trades_from_closed([ct])
    assert trade.commission_paid == pytest.approx(0.168)
    assert trade.net_pnl == pytest.approx(9.832)


def test_metrics_report_net_pnl_alongside_gross():
    cts = [
        ClosedTrade(
            entry_timestamp="t1", exit_timestamp="t2",
            entry_price=100.0, exit_price=110.0, qty=1.0, side="long",
            pnl=10.0, bar_index_entry=0, bar_index_exit=1,
            commission_paid=0.168, net_pnl=9.832,
        ),
        ClosedTrade(
            entry_timestamp="t3", exit_timestamp="t4",
            entry_price=110.0, exit_price=105.0, qty=1.0, side="long",
            pnl=-5.0, bar_index_entry=2, bar_index_exit=3,
            commission_paid=0.172, net_pnl=-5.172,
        ),
    ]
    trades = compute_trades_from_closed(cts)
    m = compute_metrics(trades)
    assert m["total_pnl"] == pytest.approx(5.0)        # 10 + -5 gross
    assert m["net_pnl"] == pytest.approx(4.66)         # 9.832 + -5.172
    assert m["trade_count"] == 2
