"""Q4 audit C9: SL/TP fields are wired into evaluate() / evaluate_last_bar().

Before this fix, ``spec.position.stop_loss_pct`` / ``take_profit_pct`` were
schema-only — the evaluator silently ignored them. A "5% SL" was wishful
thinking; a sustained drawdown would never auto-exit.
"""
from __future__ import annotations

import pandas as pd
import pytest

from showme.strategies.evaluate import (
    _check_sl_tp_intrabar,
    evaluate,
    evaluate_last_bar,
)
from showme.strategies.spec import (
    Position,
    Rule,
    StrategySpec,
)


def _df_with_ohlc(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    n = len(rows)
    idx = pd.date_range("2026-05-22", periods=n, freq="h")
    return pd.DataFrame({
        "open": [r[0] for r in rows],
        "high": [r[1] for r in rows],
        "low": [r[2] for r in rows],
        "close": [r[3] for r in rows],
        "volume": [1000] * n,
    }, index=idx)


class TestCheckSlTpIntrabar:
    def test_long_sl_hit_when_low_crosses(self):
        # Entry 100, SL 5% → 95. Low 94 < 95 → hit at 95.
        px, reason = _check_sl_tp_intrabar(
            side="long", entry_price=100.0, high=101.0, low=94.0,
            sl_pct=5.0, tp_pct=None,
        )
        assert px == pytest.approx(95.0)
        assert reason == "sl_hit"

    def test_long_tp_hit_when_high_crosses(self):
        # Entry 100, TP 5% → 105. High 106 > 105 → hit at 105.
        px, reason = _check_sl_tp_intrabar(
            side="long", entry_price=100.0, high=106.0, low=99.0,
            sl_pct=None, tp_pct=5.0,
        )
        assert px == pytest.approx(105.0)
        assert reason == "tp_hit"

    def test_short_sl_hit_when_high_crosses(self):
        # Short entry 100, SL 5% → 105. High 106 > 105 → hit at 105.
        px, reason = _check_sl_tp_intrabar(
            side="short", entry_price=100.0, high=106.0, low=99.0,
            sl_pct=5.0, tp_pct=None,
        )
        assert px == pytest.approx(105.0)
        assert reason == "sl_hit"

    def test_short_tp_hit_when_low_crosses(self):
        # Short entry 100, TP 5% → 95. Low 94 < 95 → hit at 95.
        px, reason = _check_sl_tp_intrabar(
            side="short", entry_price=100.0, high=101.0, low=94.0,
            sl_pct=None, tp_pct=5.0,
        )
        assert px == pytest.approx(95.0)
        assert reason == "tp_hit"

    def test_pessimistic_resolution_sl_wins_over_tp_on_same_bar(self):
        # Both SL and TP hit on the same bar: SL fires first (H22).
        px, reason = _check_sl_tp_intrabar(
            side="long", entry_price=100.0, high=110.0, low=90.0,
            sl_pct=5.0, tp_pct=5.0,
        )
        assert reason == "sl_hit"
        assert px == pytest.approx(95.0)

    def test_no_hit_returns_none(self):
        px, reason = _check_sl_tp_intrabar(
            side="long", entry_price=100.0, high=101.0, low=99.0,
            sl_pct=5.0, tp_pct=5.0,
        )
        assert px is None
        assert reason is None

    def test_no_sl_tp_set_returns_none(self):
        px, reason = _check_sl_tp_intrabar(
            side="long", entry_price=100.0, high=200.0, low=10.0,
            sl_pct=None, tp_pct=None,
        )
        assert px is None and reason is None


def _spec_with_sl_tp(sl_pct=None, tp_pct=None, side="long") -> StrategySpec:
    return StrategySpec(
        name="sl_tp_test",
        entry_rules=[Rule(kind="greater_than", left="close", right="literal:99")],
        exit_rules=[Rule(kind="less_than", left="close", right="literal:0")],  # never triggers
        position=Position(side=side, stop_loss_pct=sl_pct, take_profit_pct=tp_pct),
    )


def test_evaluate_fires_sl_exit_before_unreachable_rule():
    # Bars: enter on bar 0 (close=100), bar 2 low=94 triggers SL (entry=100, sl=5%).
    df = _df_with_ohlc([
        (99, 101, 99, 100),
        (100, 102, 99, 101),
        (101, 102, 94, 95),  # SL hit
    ])
    spec = _spec_with_sl_tp(sl_pct=5.0)
    events = evaluate(spec, df)
    assert len(events) == 2
    assert events[0].kind == "entry"
    assert events[1].kind == "exit"
    assert events[1].reason == "sl_hit"
    assert events[1].price == pytest.approx(95.0)  # entry * (1 - 0.05)


def test_evaluate_fires_tp_exit():
    df = _df_with_ohlc([
        (99, 101, 99, 100),
        (100, 106, 100, 105),  # TP hit
    ])
    spec = _spec_with_sl_tp(tp_pct=5.0)
    events = evaluate(spec, df)
    assert len(events) == 2
    assert events[1].kind == "exit"
    assert events[1].reason == "tp_hit"
    assert events[1].price == pytest.approx(105.0)


def test_evaluate_last_bar_intrabar_sl_with_entry_price():
    # in_position=True, entry_price=100 supplied; bar's low=94 → SL hit at 95.
    df = _df_with_ohlc([
        (99, 101, 99, 100),
        (100, 102, 94, 96),
    ])
    spec = _spec_with_sl_tp(sl_pct=5.0)
    ev = evaluate_last_bar(spec, df, in_position=True, entry_price=100.0)
    assert ev is not None
    assert ev.kind == "exit"
    assert ev.reason == "sl_hit"
    assert ev.price == pytest.approx(95.0)


def test_evaluate_last_bar_without_entry_price_skips_sl_tp_check():
    # No entry_price → SL/TP check disabled; falls back to rule (won't fire).
    df = _df_with_ohlc([
        (99, 101, 99, 100),
        (100, 102, 50, 60),  # huge drawdown
    ])
    spec = _spec_with_sl_tp(sl_pct=5.0)
    ev = evaluate_last_bar(spec, df, in_position=True, entry_price=None)
    assert ev is None  # rule doesn't fire (less_than 0), no SL/TP without entry_price
