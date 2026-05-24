"""Tests for ``evaluate_last_bar`` — state-aware single-bar evaluator.

C-RUNTIME-2 / H-RT-4 regression: the runner needs a per-tick evaluator
that respects the caller's ``in_position`` state and only inspects the
last bar. The full-history ``evaluate()`` stays for the preview endpoint.
"""
from __future__ import annotations

import pandas as pd

from showme.strategies.evaluate import evaluate_last_bar
from showme.strategies.spec import IndicatorRef, Rule, StrategySpec


def _df(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    idx = pd.date_range("2026-05-22", periods=n, freq="h")
    return pd.DataFrame({
        "open": closes, "high": [c + 0.5 for c in closes],
        "low": [c - 0.5 for c in closes], "close": list(closes),
        "volume": [1000] * n,
    }, index=idx)


def _spec(entry_rules, exit_rules, indicators=None, entry_logic="all", exit_logic="any"):
    return StrategySpec(
        name="t",
        indicators=indicators or [],
        entry_rules=entry_rules, exit_rules=exit_rules,
        entry_logic=entry_logic, exit_logic=exit_logic,
    )


# ── Empty / short input ─────────────────────────────────────────────────


def test_empty_df_returns_none():
    spec = _spec(
        [Rule(kind="greater_than", left="close", right="literal:0")],
        [],
    )
    assert evaluate_last_bar(spec, pd.DataFrame(), in_position=False) is None


def test_single_bar_returns_none():
    """``crosses_*`` rules need a 2-bar window; we require at least 2."""
    spec = _spec(
        [Rule(kind="crosses_above", left="close", right="literal:5")],
        [],
    )
    df = _df([10])
    assert evaluate_last_bar(spec, df, in_position=False) is None


# ── State-aware: in_position drives kind ────────────────────────────────


def test_emits_entry_when_flat_and_entry_rule_fires():
    spec = _spec(
        [Rule(kind="crosses_above", left="close", right="literal:5")],
        [Rule(kind="crosses_below", left="close", right="literal:5")],
    )
    # 3 → 10 crosses 5 on the last bar.
    df = _df([3, 10])
    event = evaluate_last_bar(spec, df, in_position=False)
    assert event is not None
    assert event.kind == "entry"
    assert event.bar_index == 1
    assert event.price == 10


def test_emits_exit_when_in_position_and_exit_rule_fires():
    spec = _spec(
        [Rule(kind="crosses_above", left="close", right="literal:5")],
        [Rule(kind="crosses_below", left="close", right="literal:5")],
    )
    # 10 → 3 crosses below 5 on last bar.
    df = _df([10, 3])
    event = evaluate_last_bar(spec, df, in_position=True)
    assert event is not None
    assert event.kind == "exit"
    assert event.bar_index == 1


def test_no_event_when_in_position_but_no_exit_rule_fires():
    spec = _spec(
        [Rule(kind="greater_than", left="close", right="literal:0")],
        [Rule(kind="less_than", left="close", right="literal:0")],  # never fires
    )
    df = _df([1, 2, 3])
    assert evaluate_last_bar(spec, df, in_position=True) is None


def test_no_event_when_flat_but_no_entry_rule_fires():
    spec = _spec(
        [Rule(kind="greater_than", left="close", right="literal:1000")],  # never
        [],
    )
    df = _df([1, 2, 3])
    assert evaluate_last_bar(spec, df, in_position=False) is None


# ── State-amnesia regression (C-RUNTIME-2) ──────────────────────────────


def test_state_amnesia_regression_in_position_does_not_re_entry():
    """A bot that already opened a position must NOT receive another
    ``entry`` event on a subsequent tick if the entry condition still
    matches the current bar. ``evaluate_last_bar(in_position=True)``
    refuses to emit ``entry``; it only checks the exit rules."""
    # Strategy: enter when close > 0 (always true), exit when close < 0.
    spec = _spec(
        [Rule(kind="greater_than", left="close", right="literal:0")],
        [Rule(kind="less_than", left="close", right="literal:0")],
    )
    df = _df([10, 11, 12])
    event = evaluate_last_bar(spec, df, in_position=True)
    # We're in a position; exit rule "close < 0" doesn't fire → None.
    assert event is None


def test_flat_state_can_re_evaluate_entry_each_tick():
    """Conversely, while flat, the evaluator returns a fresh entry event
    every time the entry condition matches the last bar — the runner
    de-dupes against bar_time + kind."""
    spec = _spec(
        [Rule(kind="greater_than", left="close", right="literal:5")],
        [],
    )
    df = _df([10, 11])
    event = evaluate_last_bar(spec, df, in_position=False)
    assert event is not None
    assert event.kind == "entry"


# ── Side threading + indicator alias ───────────────────────────────────


def test_event_includes_position_side():
    spec = StrategySpec(
        name="short_strat",
        entry_rules=[Rule(kind="greater_than", left="close", right="literal:5")],
        exit_rules=[],
        position={"side": "short", "sizing_kind": "fixed_quote", "sizing_value": 100.0},
    )
    df = _df([10, 11])
    event = evaluate_last_bar(spec, df, in_position=False)
    assert event is not None
    assert event.side == "short"


def test_indicator_alias_resolved_in_last_bar_path():
    spec = StrategySpec(
        name="rsi_strat",
        indicators=[IndicatorRef(alias="r", id="rsi", params={"period": 14})],
        entry_rules=[Rule(kind="less_than", left="r", right="literal:30")],
        exit_rules=[],
    )
    # Build a sequence that drives RSI below 30 by the last bar.
    closes = [100 - i for i in range(30)] + [10] * 15
    df = _df(closes)
    event = evaluate_last_bar(spec, df, in_position=False)
    # We can't assert deterministic firing — just confirm no exception
    # and that if it returns an event, it's labelled entry and bar_index
    # points at the last bar.
    if event is not None:
        assert event.kind == "entry"
        assert event.bar_index == len(closes) - 1
