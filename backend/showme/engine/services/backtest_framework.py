"""Walk-forward backtest framework.

Plug-in pattern: strategy is a callable
    strategy(bars: pd.DataFrame, state: dict) -> int
where return value is target position in {-1, 0, +1} and ``state`` may
be mutated by the strategy for stickiness across bars.

Usage:
    bt = Backtest(bars, strategy=my_strategy, fee_bps=5, initial_cash=10_000)
    res = bt.run()
    res.equity_curve  # pd.Series
    res.metrics       # dict
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import pandas as pd


StrategyFn = Callable[[pd.DataFrame, dict[str, Any]], int]


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    positions: pd.Series
    trades: list[dict[str, Any]]
    metrics: dict[str, float]
    final_equity: float


class Backtest:
    """Vectorized signal-generation + bar-by-bar P&L application."""

    def __init__(self, bars: pd.DataFrame, strategy: StrategyFn,
                 *, initial_cash: float = 10_000.0,
                 fee_bps: float = 5.0, allow_short: bool = True,
                 warmup: int = 30) -> None:
        if "close" not in bars.columns:
            raise ValueError("bars must have a 'close' column")
        self.bars = bars.copy()
        self.strategy = strategy
        self.cash0 = initial_cash
        self.fee = fee_bps / 10_000
        self.allow_short = allow_short
        self.warmup = warmup

    def run(self) -> BacktestResult:
        bars = self.bars.reset_index(drop=False)
        equity = [self.cash0]
        positions = [0]
        trades: list[dict[str, Any]] = []
        state: dict[str, Any] = {}
        cash = self.cash0
        pos = 0
        last_price = float(bars["close"].iloc[0])
        for i in range(1, len(bars)):
            window = bars.iloc[: i + 1]
            row = bars.iloc[i]
            price = float(row["close"])
            # Mark equity at this bar's close
            if pos != 0:
                cash += pos * (price - last_price)
            last_price = price
            # Decide signal AFTER warmup
            if i >= self.warmup:
                try:
                    target = int(self.strategy(window, state))
                except Exception:
                    target = pos
                if not self.allow_short:
                    target = max(0, target)
                if target != pos:
                    notional = cash * (1.0 if pos == 0 else 1.0)
                    fee_amt = abs(target - pos) * notional * self.fee
                    cash -= fee_amt
                    trades.append({
                        "ts": str(row.iloc[0]),
                        "from": pos, "to": target,
                        "price": price, "fee": fee_amt,
                    })
                    pos = target
            equity.append(cash)
            positions.append(pos)
        idx = bars.iloc[:len(equity), 0]
        eq = pd.Series(equity, index=pd.Index(idx, name=bars.columns[0]))
        ps = pd.Series(positions, index=eq.index)
        metrics = self._metrics(eq, trades)
        return BacktestResult(equity_curve=eq, positions=ps, trades=trades,
                              metrics=metrics, final_equity=float(eq.iloc[-1]))

    @staticmethod
    def _metrics(equity: pd.Series, trades: list[dict[str, Any]]) -> dict[str, float]:
        ret = equity.pct_change().dropna()
        total_return = float(equity.iloc[-1] / equity.iloc[0] - 1)
        n = max(len(equity), 1)
        ann_factor = math.sqrt(252)
        sharpe = float(ret.mean() / (ret.std() + 1e-12)) * ann_factor if not ret.empty else 0.0
        # Max drawdown
        peak = equity.cummax()
        dd = (equity / peak - 1)
        max_dd = float(dd.min())
        # Sortino
        downside = ret[ret < 0]
        sortino = float(ret.mean() / (downside.std() + 1e-12)) * ann_factor if not downside.empty else 0.0
        # Calmar
        years = n / 252
        cagr = float((equity.iloc[-1] / equity.iloc[0]) ** (1 / max(years, 1e-3)) - 1) if equity.iloc[0] > 0 else 0
        calmar = (cagr / abs(max_dd)) if max_dd != 0 else 0
        wins = sum(1 for t in trades if t.get("from", 0) != 0)  # crude trade count
        return {
            "total_return": total_return, "cagr": cagr,
            "sharpe": sharpe, "sortino": sortino, "calmar": calmar,
            "max_drawdown": max_dd,
            "trades": len(trades),
            "win_rate_proxy": float(wins) / max(len(trades), 1),
            "samples": int(n),
        }


# ── Built-in example strategies ────────────────────────────────────────────
def sma_crossover(bars: pd.DataFrame, state: dict[str, Any],
                   *, fast: int = 10, slow: int = 30) -> int:
    if len(bars) < slow:
        return 0
    f = bars["close"].rolling(fast).mean().iloc[-1]
    s = bars["close"].rolling(slow).mean().iloc[-1]
    return 1 if f > s else (-1 if f < s else 0)


def rsi_meanrev(bars: pd.DataFrame, state: dict[str, Any],
                 period: int = 14, lo: int = 30, hi: int = 70) -> int:
    delta = bars["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss = -delta.clip(upper=0).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = (100 - (100 / (1 + rs))).iloc[-1]
    if rsi < lo:  return +1
    if rsi > hi:  return -1
    return state.get("pos", 0)


def buy_and_hold(bars: pd.DataFrame, state: dict[str, Any]) -> int:
    return 1


STRATEGY_REGISTRY: dict[str, StrategyFn] = {
    "sma_crossover": sma_crossover,
    "rsi_meanrev": rsi_meanrev,
    "buy_and_hold": buy_and_hold,
}
