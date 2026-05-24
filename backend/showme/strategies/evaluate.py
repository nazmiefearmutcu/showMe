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
    # H-13 fix: surface position side so the runner can pick BUY vs SELL
    # correctly. Long strategies dispatch BUY-then-close; short strategies
    # dispatch SELL-then-cover. Defaults to "long" for backward compat with
    # callers that don't read this field yet.
    side: str = "long"  # "long" | "short"

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
        # H-14 fix: divide-by-zero produced NaN which then cast to False
        # everywhere — but the original goal was a relative tolerance check.
        # When ``right`` is exactly zero, ratio-based comparison is undefined;
        # fall back to absolute tolerance: |left| <= tol. Negative or NaN tol
        # collapses to False (never equal). The two cases are merged via
        # ``np.where`` row-by-row so the result is a clean boolean Series.
        if not np.isfinite(tol) or tol < 0:
            return pd.Series([False] * len(left), index=left.index)
        right_abs = right.abs()
        # Avoid SettingWithCopyWarning on read-only ratios:
        right_safe = right.replace(0, np.nan).abs()
        ratio = (left - right).abs() / right_safe
        rel = ratio < tol
        absolute = left.abs() <= tol
        # right == 0 → absolute; otherwise → ratio (rel)
        result = pd.Series(
            np.where(right_abs.eq(0), absolute.to_numpy(),
                     rel.fillna(False).to_numpy()),
            index=left.index,
        )
        return result.astype(bool)
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
    # H-13 fix: thread spec.position.side through events so the runner
    # can pick BUY vs SELL based on the strategy's declared side.
    side = spec.position.side
    for i in range(len(df)):
        bar_time = str(df.index[i])
        price = float(close.iloc[i])
        if math.isnan(price):
            continue
        if not in_position:
            cond = bool(entry_truth.iloc[i]) if i < len(entry_truth) else False
            if cond:
                events.append(Event(bar_index=i, bar_time=bar_time,
                                   kind="entry", price=price,
                                   details={}, side=side))
                in_position = True
        else:
            cond = bool(exit_truth.iloc[i]) if i < len(exit_truth) else False
            if cond:
                events.append(Event(bar_index=i, bar_time=bar_time,
                                   kind="exit", price=price,
                                   details={}, side=side))
                in_position = False
    return events


def evaluate_last_bar(
    spec: StrategySpec, df: pd.DataFrame, *, in_position: bool,
) -> Event | None:
    """State-aware single-bar evaluator.

    C-RUNTIME-2 / H-RT-4 fix: instead of replaying the spec's state machine
    over the entire rolling window every tick (which mutates ``in_position``
    based on history the bot has *already* processed), look at the last bar
    only and decide based on the *caller-supplied* position state.

    * If ``in_position is False``: emit an ``entry`` event iff every entry
      rule fires on the last bar.
    * If ``in_position is True``: emit an ``exit`` event iff every exit
      rule fires on the last bar.
    * Otherwise, return ``None`` (no event).

    The caller (typically ``BotRunner.tick``) knows the true position state
    by looking at ``BotRecord.last_processed_event`` and threads that here.
    This avoids the "state-amnesia" bug where a sliding 200-bar window
    could re-fire entry on a bar the bot had already actioned.

    Returns at most one :class:`Event`. ``rule.crosses_*`` still depends on
    the previous bar in ``df`` (shift(1) compared row-by-row), so callers
    should supply at least a 2-bar window. Indicators that need warm-up
    (RSI/EMA/...) should get the usual ~50-200 bars.
    """
    if df.empty or len(df) < 2:
        return None
    indicators = compute(df, spec.indicators)

    if in_position:
        if not spec.exit_rules:
            return None
        truth = _combine(
            [_eval_rule(r, df, indicators) for r in spec.exit_rules],
            spec.exit_logic,
        )
        kind = "exit"
    else:
        if not spec.entry_rules:
            return None
        truth = _combine(
            [_eval_rule(r, df, indicators) for r in spec.entry_rules],
            spec.entry_logic,
        )
        kind = "entry"

    last_i = len(df) - 1
    if last_i >= len(truth):
        return None
    cond = bool(truth.iloc[last_i])
    if not cond:
        return None
    bar_time = str(df.index[last_i])
    price = float(df["close"].iloc[last_i])
    if math.isnan(price):
        return None
    return Event(
        bar_index=last_i, bar_time=bar_time, kind=kind, price=price,
        details={}, side=spec.position.side,
    )
