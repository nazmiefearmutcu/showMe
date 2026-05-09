"""Algo backtest framework — replay historical bars + simulate child orders.

Vectorized; no broker calls. Useful for VWAP / TWAP / Iceberg / Sniper
algorithm validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class BacktestResult:
    fills: list[dict[str, Any]] = field(default_factory=list)
    achieved_avg_price: float = 0.0
    benchmark_vwap: float = 0.0
    slippage_bps: float = 0.0
    total_qty: float = 0.0
    fees: float = 0.0


def run_vwap_backtest(
    bars: pd.DataFrame, *,
    target_quantity: float,
    side: str = "BUY",
    duration_bars: int | None = None,
    slices: int = 12,
    fee_bps: float = 5.0,
) -> BacktestResult:
    """Simulate VWAP slicing over the first N bars of ``bars`` (OHLCV DataFrame).

    Each slice is filled at that bar's VWAP (≈ (h+l+c)/3 if no vwap col).
    Benchmark = full-window VWAP. Slippage = (achieved - benchmark) / benchmark.
    """
    if bars.empty:
        return BacktestResult()
    df = bars.head(duration_bars or len(bars)).copy()
    if "vwap" not in df.columns:
        df["vwap"] = (df["high"] + df["low"] + df["close"]) / 3
    weights = df["volume"].values
    if weights.sum() == 0:
        weights = [1.0] * len(df)
    weights = [float(w) / float(sum(weights)) for w in weights]
    per = [target_quantity * w for w in weights]
    fills: list[dict[str, Any]] = []
    bench_num = (df["vwap"] * df["volume"]).sum()
    bench_den = df["volume"].sum()
    benchmark = float(bench_num / bench_den) if bench_den else float(df["vwap"].mean())
    notional = 0.0
    qty_total = 0.0
    for (idx, row), q in zip(df.iterrows(), per):
        if q <= 0:
            continue
        px = float(row["vwap"])
        fills.append({"ts": str(idx), "qty": float(q), "price": px})
        notional += q * px
        qty_total += q
    achieved = notional / qty_total if qty_total else 0.0
    slip = ((achieved - benchmark) / benchmark) * 10_000
    if side.upper() == "SELL":
        slip = -slip
    fees = notional * (fee_bps / 10_000)
    return BacktestResult(
        fills=fills, achieved_avg_price=achieved,
        benchmark_vwap=benchmark, slippage_bps=slip,
        total_qty=qty_total, fees=fees,
    )


def run_twap_backtest(
    bars: pd.DataFrame, *,
    target_quantity: float, side: str = "BUY",
    slices: int = 10, fee_bps: float = 5.0,
) -> BacktestResult:
    if bars.empty:
        return BacktestResult()
    step = max(1, len(bars) // slices)
    selected = bars.iloc[::step].head(slices)
    per = target_quantity / max(1, len(selected))
    notional = sum(per * float(r["close"]) for _, r in selected.iterrows())
    qty = per * len(selected)
    bench_num = (((bars["high"] + bars["low"] + bars["close"]) / 3) * bars["volume"]).sum()
    bench_den = bars["volume"].sum()
    benchmark = float(bench_num / bench_den) if bench_den else float(bars["close"].mean())
    achieved = notional / qty if qty else 0.0
    slip = ((achieved - benchmark) / benchmark) * 10_000
    if side.upper() == "SELL":
        slip = -slip
    return BacktestResult(
        achieved_avg_price=achieved, benchmark_vwap=benchmark,
        slippage_bps=slip, total_qty=qty,
        fees=notional * (fee_bps / 10_000),
        fills=[{"ts": str(idx), "qty": per, "price": float(r["close"])}
                 for idx, r in selected.iterrows()],
    )
