"""Q1 audit HIGH 11: liquidation pressure direction must match docstring.

Docstring claim: heavy short liquidations (BUY-side forceOrders) → bears
trapped → contrarian BUY. The code at lines 119-130 used to emit
``STRONG_SELL`` / ``SELL`` for SHORT_LIQ dominant — directly contradicting
its own documentation.

The fix makes both dominant patterns emit BUY signals (consistent with
the indicator's stated mean-reversion premise: every large one-sided
liquidation cluster is a contrarian buy).
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest

from showme.engine.indicators.base import Signal
from showme.engine.indicators.liquidation_pressure import LiquidationPressureIndicator


def _liq_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _make_indicator(liqs: pd.DataFrame, **threshold_overrides: Any) -> LiquidationPressureIndicator:
    cache = MagicMock()
    cache.get_liquidations.return_value = liqs
    config = {
        "market_type": "futures",
        "indicator_thresholds": {
            "liquidation_pressure": {
                "window_minutes": 60,
                "strong_imbalance_ratio": 3.0,
                "weak_imbalance_ratio": 1.5,
                "min_total_notional": 100_000.0,
                **threshold_overrides,
            },
        },
    }
    return LiquidationPressureIndicator(config=config, cache=cache, store=None)


def _signal_df() -> pd.DataFrame:
    df = pd.DataFrame({
        "open": [100.0], "high": [101.0], "low": [99.0],
        "close": [100.0], "volume": [1000.0],
    }, index=pd.date_range("2026-05-23", periods=1, freq="h"))
    df.attrs["symbol"] = "BTCUSDT"
    return df


# ── SHORT_LIQ dominant must be contrarian BUY ────────────────────────────


def test_short_liq_dominant_strong_emits_strong_buy():
    """Heavy SHORT_LIQ (BUY-side forceOrders) is a short squeeze →
    contrarian STRONG_BUY (matches docstring), no longer STRONG_SELL."""
    # BUY-side notionals dominate by >5× the SELL-side.
    liqs = _liq_df([
        {"side": "BUY", "price": 50_000.0, "quantity": 5.0},   # 250k notional
        {"side": "BUY", "price": 50_000.0, "quantity": 5.0},   # 250k
        {"side": "BUY", "price": 50_000.0, "quantity": 5.0},   # 250k
        {"side": "SELL", "price": 50_000.0, "quantity": 1.0},  # 50k
    ])
    ind = _make_indicator(liqs)
    result = ind.calculate(_signal_df())
    assert result.signal == Signal.STRONG_BUY, (
        f"SHORT_LIQ dominant should now emit STRONG_BUY (contrarian), got {result.signal}"
    )
    raw = result.raw_values or {}
    assert raw.get("dominant") == "SHORT_LIQ"


def test_short_liq_dominant_weak_emits_buy():
    """Weak SHORT_LIQ imbalance must emit BUY (was SELL)."""
    # BUY side ~2× SELL side — between weak (1.5) and strong (3.0).
    liqs = _liq_df([
        {"side": "BUY", "price": 50_000.0, "quantity": 4.0},   # 200k
        {"side": "BUY", "price": 50_000.0, "quantity": 4.0},   # 200k
        {"side": "SELL", "price": 50_000.0, "quantity": 4.0},  # 200k
    ])
    ind = _make_indicator(liqs)
    result = ind.calculate(_signal_df())
    assert result.signal == Signal.BUY, (
        f"weak SHORT_LIQ imbalance should emit BUY, got {result.signal}"
    )
    raw = result.raw_values or {}
    assert raw.get("dominant") == "SHORT_LIQ"


# ── LONG_LIQ dominant retained as contrarian BUY ─────────────────────────


def test_long_liq_dominant_strong_emits_strong_buy():
    """Heavy LONG_LIQ (SELL-side forceOrders) is long capitulation →
    contrarian STRONG_BUY. This branch was always correct; pin it."""
    liqs = _liq_df([
        {"side": "SELL", "price": 50_000.0, "quantity": 5.0},  # 250k
        {"side": "SELL", "price": 50_000.0, "quantity": 5.0},  # 250k
        {"side": "SELL", "price": 50_000.0, "quantity": 5.0},  # 250k
        {"side": "BUY", "price": 50_000.0, "quantity": 1.0},   # 50k
    ])
    ind = _make_indicator(liqs)
    result = ind.calculate(_signal_df())
    assert result.signal == Signal.STRONG_BUY
    raw = result.raw_values or {}
    assert raw.get("dominant") == "LONG_LIQ"


def test_long_liq_dominant_weak_emits_buy():
    liqs = _liq_df([
        {"side": "SELL", "price": 50_000.0, "quantity": 4.0},  # 200k
        {"side": "SELL", "price": 50_000.0, "quantity": 4.0},  # 200k
        {"side": "BUY", "price": 50_000.0, "quantity": 4.0},   # 200k
    ])
    ind = _make_indicator(liqs)
    result = ind.calculate(_signal_df())
    assert result.signal == Signal.BUY
    raw = result.raw_values or {}
    assert raw.get("dominant") == "LONG_LIQ"


# ── Balanced and below-threshold still neutral ───────────────────────────


def test_balanced_imbalance_emits_neutral():
    liqs = _liq_df([
        {"side": "BUY", "price": 50_000.0, "quantity": 4.0},   # 200k
        {"side": "SELL", "price": 50_000.0, "quantity": 4.0},  # 200k
    ])
    ind = _make_indicator(liqs)
    result = ind.calculate(_signal_df())
    assert result.signal == Signal.NEUTRAL


def test_below_min_notional_emits_neutral():
    liqs = _liq_df([
        {"side": "BUY", "price": 1_000.0, "quantity": 1.0},   # 1k notional
    ])
    ind = _make_indicator(liqs)
    result = ind.calculate(_signal_df())
    assert result.signal == Signal.NEUTRAL
    raw = result.raw_values or {}
    assert raw.get("total") == pytest.approx(1000.0)
