"""Rule evaluator: turns a StrategySpec + OHLCV into entry/exit events.

State machine: flat → in_position → flat. On each bar, evaluate all
entry rules (combined via entry_logic) when flat; all exit rules
(combined via exit_logic) when in_position. Emit one event per state
transition.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, asdict
from typing import Any

import numpy as np
import pandas as pd

from showme.strategies.compute import compute
from showme.strategies.spec import Rule, StrategySpec

LOG = logging.getLogger("showme.strategies.evaluate")

_PRICE_FIELDS = {"close", "open", "high", "low", "volume"}


@dataclass(frozen=True)
class Event:
    bar_index: int
    bar_time: str
    kind: str           # "entry" | "exit"
    price: float
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def _resolve_operand(operand: str, df: pd.DataFrame,
                     indicators: dict[str, pd.Series]) -> pd.Series:
    if operand.startswith("literal:"):
        val = float(operand.split(":", 1)[1])
        return pd.Series([val] * len(df), index=df.index)
    if operand in _PRICE_FIELDS:
        return df[operand]
    if operand in indicators:
        return indicators[operand]
    # Unknown operand: NaN series so all comparisons collapse to False.
    return pd.Series([np.nan] * len(df), index=df.index)


def _eval_rule(rule: Rule, df: pd.DataFrame,
               indicators: dict[str, pd.Series]) -> pd.Series:
    left = _resolve_operand(rule.left, df, indicators)
    right = _resolve_operand(rule.right, df, indicators)
    if rule.kind == "greater_than":
        return left > right
    if rule.kind == "less_than":
        return left < right
    if rule.kind == "equals_approximately":
        tol = float(rule.tolerance or 0.0)
        return (left - right).abs() / right.replace(0, np.nan).abs() < tol
    # Cross detection: compare current vs previous bar.
    if rule.kind == "crosses_above":
        return (left.shift(1) <= right.shift(1)) & (left > right)
    if rule.kind == "crosses_below":
        return (left.shift(1) >= right.shift(1)) & (left < right)
    raise ValueError(f"unknown rule kind: {rule.kind}")


def _combine(series_list: list[pd.Series], logic: str) -> pd.Series:
    if not series_list:
        # No rules: never fires.
        return pd.Series([False] * 0)
    if logic == "all":
        result = series_list[0].astype(bool)
        for s in series_list[1:]:
            result = result & s.astype(bool)
        return result
    if logic == "any":
        result = series_list[0].astype(bool)
        for s in series_list[1:]:
            result = result | s.astype(bool)
        return result
    raise ValueError(f"unknown logic: {logic}")


def evaluate(spec: StrategySpec, df: pd.DataFrame) -> list[Event]:
    """Run the spec's state machine over the OHLCV and emit events."""
    if df.empty:
        return []
    indicators = compute(df, spec.indicators)

    if spec.entry_rules:
        entry_truth = _combine(
            [_eval_rule(r, df, indicators) for r in spec.entry_rules],
            spec.entry_logic,
        )
    else:
        entry_truth = pd.Series([False] * len(df), index=df.index)

    if spec.exit_rules:
        exit_truth = _combine(
            [_eval_rule(r, df, indicators) for r in spec.exit_rules],
            spec.exit_logic,
        )
    else:
        exit_truth = pd.Series([False] * len(df), index=df.index)

    events: list[Event] = []
    in_position = False
    close = df["close"]
    for i in range(len(df)):
        bar_time = str(df.index[i])
        price = float(close.iloc[i])
        if math.isnan(price):
            continue
        if not in_position:
            cond = bool(entry_truth.iloc[i]) if i < len(entry_truth) else False
            if cond:
                events.append(Event(bar_index=i, bar_time=bar_time,
                                   kind="entry", price=price, details={}))
                in_position = True
        else:
            cond = bool(exit_truth.iloc[i]) if i < len(exit_truth) else False
            if cond:
                events.append(Event(bar_index=i, bar_time=bar_time,
                                   kind="exit", price=price, details={}))
                in_position = False
    return events
