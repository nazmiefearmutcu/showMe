"""Pure-Python indicator primitives for the vendored KAOS strategy.

Vendored from KAOS engine (Entropy repo) pure strategy layer,
Entropy HEAD: edfa322 — parity-tested.

These are faithful pure-Python ports of the indicator arithmetic the KAOS
engine uses at strategy-evaluation time (``crocodile.core.analytics.indicators``
in the Entropy venv). The showme sidecar must not depend on crocodile /
polars, so the exact same math is reproduced here on plain lists:

* EMA   — exponentially weighted mean, ``span=period, adjust=False``
          (alpha = 2 / (span + 1), seeded with the first price).
* RSI   — Wilder smoothing seeded by the mean of the first ``period`` changes;
          first non-null value sits at index ``period``.
* MACD  — fast EMA - slow EMA, signal = EMA(MACD), hist = MACD - signal.
* Bollinger — rolling mean +/- ``k`` * rolling POPULATION std (ddof=0).

Parity contract: ``tests/test_kaos_parity.py`` asserts signal-identical
behaviour against the real Entropy implementation over the same bars.
Nulls (warm-up positions) are represented as ``None`` exactly like the
polars-backed originals.
"""
from __future__ import annotations

from collections.abc import Sequence

__all__ = [
    "calculate_bollinger_bands",
    "calculate_ema",
    "calculate_macd",
    "calculate_rsi",
]


def calculate_ema(prices: Sequence[float], period: int) -> list[float | None]:
    """EMA with ``span=period, adjust=False`` (polars ``ewm_mean`` semantics).

    y[0] = x[0]; y[i] = y[i-1] + alpha * (x[i] - y[i-1]) with
    alpha = 2 / (period + 1). The incremental-delta form is BIT-EXACT with
    polars' ewm kernel (verified against crocodile in the parity test);
    the algebraically-equivalent ``alpha*x + (1-alpha)*prev`` drifts by 1 ULP.
    """
    if period <= 0:
        raise ValueError("Period must be a positive integer.")
    n = len(prices)
    if n == 0:
        return []
    alpha = 2.0 / (period + 1.0)
    out: list[float | None] = [None] * n
    prev = float(prices[0])
    out[0] = prev
    for i in range(1, n):
        x = float(prices[i])
        prev = prev + alpha * (x - prev)
        out[i] = prev
    return out


def _wilder_average(
    changes: list[float | None], period: int
) -> list[float | None]:
    """Wilder's smoothed average seeded by the mean of changes[1..period].

    Mirrors the polars implementation: the seed is the simple mean of the
    ``period`` changes starting at index 1 (index 0 of a diff series is the
    null warm-up slot), and the recursion is an EWMA with alpha = 1/period
    applied to ``[seed] + changes[period+1:]``. The first ``period`` output
    slots are ``None``.
    """
    window = changes[1 : period + 1]
    if any(v is None for v in window):
        seed: float | None = None
    else:
        seed = sum(float(v) for v in window) / period  # type: ignore[arg-type]
    rest = changes[period + 1 :]
    alpha = 1.0 / period
    out: list[float | None] = [None] * period
    if seed is None:
        for _ in rest:
            out.append(None)
        return out
    prev = seed
    out.append(prev)
    for v in rest:
        x = 0.0 if v is None else float(v)
        prev = prev + alpha * (x - prev)
        out.append(prev)
    return out


def calculate_rsi(prices: Sequence[float], period: int) -> list[float | None]:
    """RSI (Wilder). First non-null value at index ``period``."""
    if period <= 0:
        raise ValueError("Period must be a positive integer.")
    n = len(prices)
    if n == 0:
        return []
    if n <= period:
        return [None] * n
    changes: list[float | None] = [None] * n
    for i in range(1, n):
        changes[i] = float(prices[i]) - float(prices[i - 1])
    gains: list[float | None] = [None] * n
    losses: list[float | None] = [None] * n
    for i in range(1, n):
        c = changes[i]
        assert c is not None
        gains[i] = max(0.0, c)
        losses[i] = -c if c < 0.0 else 0.0
    avg_gain = _wilder_average(gains, period)
    avg_loss = _wilder_average(losses, period)
    out: list[float | None] = [None] * n
    for i in range(period, n):
        ag, al = avg_gain[i], avg_loss[i]
        if ag is None or al is None:
            out[i] = None
        elif al == 0.0 and ag == 0.0:
            out[i] = 50.0
        elif al == 0.0:
            out[i] = 100.0
        else:
            rs = ag / al
            out[i] = 100.0 - (100.0 / (1.0 + rs))
    return out


def calculate_macd(
    prices: Sequence[float],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """MACD line / signal line / histogram (all EMA adjust=False)."""
    if fast_period <= 0 or slow_period <= 0 or signal_period <= 0:
        raise ValueError("Periods must be positive integers.")
    n = len(prices)
    if n == 0:
        return [], [], []
    fast = calculate_ema(prices, fast_period)
    slow = calculate_ema(prices, slow_period)
    macd_line: list[float] = [
        float(f) - float(s) for f, s in zip(fast, slow)  # type: ignore[arg-type]
    ]
    signal = calculate_ema(macd_line, signal_period)
    hist: list[float | None] = [
        m - float(s) for m, s in zip(macd_line, signal)  # type: ignore[arg-type]
    ]
    return (
        [float(v) for v in macd_line],
        [float(v) if v is not None else None for v in signal],
        hist,
    )


def calculate_bollinger_bands(
    prices: Sequence[float],
    period: int = 20,
    k: float = 2.0,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Bollinger bands with POPULATION std (ddof=0), polars warm-up nulls."""
    if period <= 0:
        raise ValueError("Period must be a positive integer.")
    n = len(prices)
    if n == 0:
        return [], [], []
    upper: list[float | None] = [None] * n
    middle: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n
    for i in range(period - 1, n):
        window = [float(v) for v in prices[i - period + 1 : i + 1]]
        m = sum(window) / period
        var = sum((v - m) * (v - m) for v in window) / period
        std = var ** 0.5
        middle[i] = m
        upper[i] = m + k * std
        lower[i] = m - k * std
    return upper, middle, lower
