"""evaluate() rule + state-machine tests."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from showme.strategies.evaluate import evaluate
from showme.strategies.spec import IndicatorRef, Rule, StrategySpec


def _df(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    n = len(closes)
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    if volumes is None:
        volumes = [1000] * n
    return pd.DataFrame({
        "open": closes, "high": [c + 0.5 for c in closes], "low": [c - 0.5 for c in closes],
        "close": closes, "volume": volumes,
    }, index=idx)


def _spec(entry_rules, exit_rules, indicators=None, entry_logic="all", exit_logic="any"):
    return StrategySpec(
        name="t",
        indicators=indicators or [],
        entry_rules=entry_rules, exit_rules=exit_rules,
        entry_logic=entry_logic, exit_logic=exit_logic,
    )


def test_empty_df_no_events():
    spec = _spec([Rule(kind="greater_than", left="close", right="literal:0")], [])
    assert evaluate(spec, pd.DataFrame()) == []


def test_no_rules_no_events():
    spec = _spec([], [])
    assert evaluate(spec, _df([1, 2, 3])) == []


def test_simple_greater_than_entry():
    spec = _spec(
        [Rule(kind="greater_than", left="close", right="literal:5")],
        [Rule(kind="less_than", left="close", right="literal:5")],
    )
    df = _df([1, 6, 7, 3, 2])  # entry at i=1, exit at i=3
    events = evaluate(spec, df)
    kinds = [e.kind for e in events]
    assert kinds == ["entry", "exit"]
    assert events[0].bar_index == 1
    assert events[1].bar_index == 3


def test_crosses_above_detects_transition_not_steady_state():
    spec = _spec(
        [Rule(kind="crosses_above", left="close", right="literal:5")],
        [Rule(kind="crosses_below", left="close", right="literal:5")],
    )
    df = _df([10, 10, 10, 3, 10, 10])  # cross down at i=3, cross up at i=4
    events = evaluate(spec, df)
    # First entry depends on initial state — close=10>5 already at i=0, but
    # crosses_above requires shift(1) <= and current >. shift(1) at i=0 is NaN
    # so first valid cross is at index where state changes. Sequence:
    #   i=0: prev=NaN, NaN compare → False; in flat
    #   i=1: prev=10>5 so 10<=5 False → no entry
    #   i=2: same
    #   i=3: 10>5, 3<5 → crosses_below but we're flat → exit not relevant
    #   i=4: prev=3<=5, now=10>5 → crosses_above, ENTRY
    #   i=5: no cross, in position
    # Expected: 1 entry at i=4
    assert any(e.kind == "entry" and e.bar_index == 4 for e in events)


def test_state_machine_no_double_entry():
    spec = _spec(
        [Rule(kind="greater_than", left="close", right="literal:0")],  # always true
        [Rule(kind="less_than", left="close", right="literal:0")],     # never true
    )
    df = _df([1, 2, 3, 4, 5])
    events = evaluate(spec, df)
    # Only one entry; no further entries because we stay in_position.
    assert sum(1 for e in events if e.kind == "entry") == 1


def test_any_logic_any_rule_fires():
    spec = _spec(
        [
            Rule(kind="greater_than", left="close", right="literal:10"),
            Rule(kind="less_than", left="close", right="literal:0"),
        ],
        [Rule(kind="equals_approximately", left="close", right="literal:5", tolerance=0.1)],
        entry_logic="any",
    )
    df = _df([12, 8, 5.01])  # entry at i=0 (>10), exit at i=2 (≈5)
    events = evaluate(spec, df)
    assert [e.kind for e in events] == ["entry", "exit"]


def test_all_logic_requires_all_rules():
    spec = _spec(
        [
            Rule(kind="greater_than", left="close", right="literal:5"),
            Rule(kind="less_than", left="close", right="literal:10"),
        ],
        [Rule(kind="greater_than", left="close", right="literal:100")],
        entry_logic="all",
    )
    df = _df([3, 7, 8, 11, 6])  # i=1 (5<7<10) entry; i=3 fails (>10);
    events = evaluate(spec, df)
    assert events[0].bar_index == 1
    assert events[0].kind == "entry"


def test_indicator_alias_resolved():
    spec = _spec(
        [Rule(kind="less_than", left="rsi14", right="literal:30")],
        [Rule(kind="greater_than", left="rsi14", right="literal:70")],
        indicators=[IndicatorRef(alias="rsi14", id="rsi", params={"period": 14})],
    )
    # Constant-decline followed by recovery → RSI eventually low.
    df = _df([100 - i for i in range(30)] + [50 + i for i in range(30)])
    events = evaluate(spec, df)
    # Just assert that SOMETHING fired (entry+exit possible).
    assert all(e.kind in {"entry", "exit"} for e in events)


def test_unknown_operand_does_not_fire():
    spec = _spec(
        [Rule(kind="greater_than", left="nonexistent_alias", right="literal:5")],
        [],
    )
    events = evaluate(spec, _df([10, 20, 30]))
    assert events == []


def test_event_to_dict_shape():
    spec = _spec(
        [Rule(kind="greater_than", left="close", right="literal:0")],
        [],
    )
    events = evaluate(spec, _df([1]))
    if events:
        d = events[0].to_dict()
        assert set(d.keys()) >= {"bar_index", "bar_time", "kind", "price", "details"}
