"""Performance computation tests."""
from __future__ import annotations

from showme.bots.performance import (
    Trade, compute_trades, compute_metrics, compute_equity_curve,
)
from showme.bots.record import SignalEntry


def _sig(kind, price, ts, action="shadow"):
    return SignalEntry(
        bar_index=0, bar_time=ts, kind=kind, price=price,
        action=action, timestamp=ts,
    )


def test_empty_signal_log_no_trades():
    assert compute_trades([]) == []
    assert compute_metrics([])["trade_count"] == 0


def test_single_entry_exit_pair_long_profit():
    log = [
        _sig("entry", 100.0, "2026-05-22T10:00:00Z"),
        _sig("exit", 110.0, "2026-05-22T11:00:00Z"),
    ]
    trades = compute_trades(log, sizing_value=100.0)
    assert len(trades) == 1
    t = trades[0]
    assert t.entry_price == 100.0
    assert t.exit_price == 110.0
    # PnL = (110-100) * 100 / 100 = 10
    assert abs(t.pnl - 10.0) < 0.01
    assert abs(t.pnl_pct - 10.0) < 0.01


def test_unclosed_entry_not_emitted():
    log = [_sig("entry", 100.0, "t1")]
    assert compute_trades(log) == []


def test_skipped_entries_ignored():
    log = [
        _sig("entry", 100.0, "t1", action="skipped"),
        _sig("entry", 105.0, "t2"),
        _sig("exit", 110.0, "t3"),
    ]
    trades = compute_trades(log)
    assert len(trades) == 1
    assert trades[0].entry_price == 105.0


def test_fifo_pairing():
    log = [
        _sig("entry", 100.0, "t1"),
        _sig("entry", 105.0, "t2"),
        _sig("exit", 110.0, "t3"),
        _sig("exit", 115.0, "t4"),
    ]
    trades = compute_trades(log)
    assert len(trades) == 2
    # FIFO: 100→110 first, 105→115 second
    assert trades[0].entry_price == 100.0
    assert trades[0].exit_price == 110.0
    assert trades[1].entry_price == 105.0
    assert trades[1].exit_price == 115.0


def test_metrics_win_rate_and_total():
    log = [
        _sig("entry", 100.0, "t1"), _sig("exit", 110.0, "t2"),  # +10 win
        _sig("entry", 100.0, "t3"), _sig("exit", 105.0, "t4"),  # +5 win
        _sig("entry", 100.0, "t5"), _sig("exit", 95.0, "t6"),   # -5 loss
    ]
    trades = compute_trades(log, sizing_value=100.0)
    m = compute_metrics(trades)
    assert m["trade_count"] == 3
    assert abs(m["win_rate"] - 2/3) < 0.01
    assert abs(m["total_pnl"] - 10.0) < 0.01  # 10 + 5 + (-5) = 10
    assert abs(m["avg_pnl"] - 10/3) < 0.01


def test_max_drawdown():
    # Wins then losses → drawdown from peak
    log = [
        _sig("entry", 100.0, "t1"), _sig("exit", 110.0, "t2"),  # +10 (peak)
        _sig("entry", 100.0, "t3"), _sig("exit", 95.0, "t4"),   # -5 (cum=5)
        _sig("entry", 100.0, "t5"), _sig("exit", 92.0, "t6"),   # -8 (cum=-3, dd=13)
    ]
    trades = compute_trades(log, sizing_value=100.0)
    m = compute_metrics(trades)
    # Peak at 10, lowest at -3 → max_dd = 13
    assert abs(m["max_drawdown"] - 13.0) < 0.5


def test_equity_curve():
    log = [
        _sig("entry", 100.0, "t1"), _sig("exit", 110.0, "t2"),
        _sig("entry", 100.0, "t3"), _sig("exit", 95.0, "t4"),
    ]
    trades = compute_trades(log, sizing_value=100.0)
    curve = compute_equity_curve(trades, starting_equity=10_000)
    assert len(curve) == 3  # start + 2 trades
    assert curve[0]["equity"] == 10_000
    assert abs(curve[1]["equity"] - 10_010) < 0.5
    assert abs(curve[2]["equity"] - 10_005) < 0.5


def test_trade_to_dict():
    t = Trade(entry_time="t1", exit_time="t2", entry_price=100, exit_price=110,
              qty=1.0, pnl=10, pnl_pct=10)
    d = t.to_dict()
    assert d["entry_price"] == 100
    assert d["pnl"] == 10
