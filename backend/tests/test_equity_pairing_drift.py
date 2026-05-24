"""Q4 audit H17: entry-time qty pinned on SignalEntry.

Previously, the exit-pairing path called ``resolve_quantity`` with the
*current* equity at exit-time and used that qty for PnL. If the running
equity changed between entry and exit (live broker, multiple positions),
the recomputed qty silently disagreed with what was actually opened.

Fix: ``SignalEntry.qty`` persists the entry-time qty; exit pairing reads
it back rather than recomputing.
"""
from __future__ import annotations

from showme.bots.performance import compute_trades
from showme.bots.record import SignalEntry


def test_entry_qty_persisted_used_for_pairing():
    entry = SignalEntry(
        bar_index=0, bar_time="t0", kind="entry",
        price=100.0, action="placed",
        qty=2.5,  # entry-time qty (e.g. resolved against $250k equity)
    )
    exit_ = SignalEntry(
        bar_index=1, bar_time="t1", kind="exit",
        price=110.0, action="placed",
        qty=None,  # exits don't persist qty (broker pairs against position)
    )
    # equity=10000 supplied to compute_trades — but should NOT be used for qty.
    trades = compute_trades(
        [entry, exit_], sizing_value=50_000,
        sizing_kind="fixed_quote",  # would recompute to qty = 50000/100 = 500
        side="long", equity=10_000.0,
    )
    assert len(trades) == 1
    # Q4 audit H17: pairing must use the persisted entry.qty=2.5, NOT recompute.
    assert trades[0].qty == 2.5
    # PnL = (110 - 100) * 2.5 = 25.0
    assert trades[0].pnl == 25.0


def test_legacy_entry_without_qty_falls_back_to_recompute():
    # Backward compat: entries minted before this fix have qty=None.
    entry = SignalEntry(
        bar_index=0, bar_time="t0", kind="entry",
        price=100.0, action="placed",
        qty=None,  # legacy
    )
    exit_ = SignalEntry(
        bar_index=1, bar_time="t1", kind="exit",
        price=110.0, action="placed",
    )
    # sizing_kind=fixed_quote $100 → qty = 100/100 = 1.0
    trades = compute_trades(
        [entry, exit_], sizing_value=100,
        sizing_kind="fixed_quote", side="long",
    )
    assert len(trades) == 1
    assert trades[0].qty == 1.0
    assert trades[0].pnl == 10.0  # (110-100) * 1.0


def test_entry_fill_price_threads_to_pnl():
    """Q4 audit C2 cross-cut: when both entries persist fill_price, pairing
    uses fill_price over signal price."""
    entry = SignalEntry(
        bar_index=0, bar_time="t0", kind="entry",
        price=100.0, fill_price=100.5, action="placed", qty=1.0,
    )
    exit_ = SignalEntry(
        bar_index=1, bar_time="t1", kind="exit",
        price=110.0, fill_price=109.5, action="placed",
    )
    trades = compute_trades(
        [entry, exit_], sizing_value=100,
        sizing_kind="fixed_quote", side="long",
    )
    assert len(trades) == 1
    # PnL based on fill prices: 109.5 - 100.5 = 9.0; qty=1 → pnl=9.0
    assert trades[0].pnl == 9.0
    assert trades[0].entry_price == 100.5
    assert trades[0].exit_price == 109.5
