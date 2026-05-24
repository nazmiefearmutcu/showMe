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
                 warmup: int = 30, risk_free: float = 0.0,
                 mar: float = 0.0) -> None:
        if "close" not in bars.columns:
            raise ValueError("bars must have a 'close' column")
        self.bars = bars.copy()
        self.strategy = strategy
        self.cash0 = initial_cash
        self.fee = fee_bps / 10_000
        self.allow_short = allow_short
        self.warmup = warmup
        # Audit Q3 #9 — explicit risk-free + MAR knobs (default 0 preserves
        # legacy behaviour). Sharpe uses `risk_free` (per-period subtracted
        # from mean return), Sortino uses `mar` as the downside threshold.
        self.risk_free = float(risk_free)
        self.mar = float(mar)

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
                    # Audit Q3 #8 — fee notional must reflect the actual
                    # market value being turned over, not raw cash. When
                    # `pos==0` we're opening (notional = full cash); when
                    # `pos!=0` we're flipping/closing, so use |pos| * price
                    # equivalent which equals `cash` only at flat. For
                    # mark-to-market correctness, use the position value
                    # (cash already reflects MV via the per-bar P&L update).
                    notional = cash * max(abs(pos), 1.0) if pos != 0 else cash
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
        metrics = self._metrics(eq, trades, risk_free=self.risk_free, mar=self.mar)
        return BacktestResult(equity_curve=eq, positions=ps, trades=trades,
                              metrics=metrics, final_equity=float(eq.iloc[-1]))

    @staticmethod
    def _metrics(
        equity: pd.Series,
        trades: list[dict[str, Any]],
        *,
        risk_free: float = 0.0,
        mar: float = 0.0,
    ) -> dict[str, float]:
        ret = equity.pct_change().dropna()
        total_return = float(equity.iloc[-1] / equity.iloc[0] - 1)
        n = max(len(equity), 1)
        ann_factor = math.sqrt(252)
        # Audit Q3 #9 — Sharpe: subtract per-period rf from mean before
        # annualizing. `risk_free` is annualized → divide by 252.
        rf_per_period = risk_free / 252.0
        if not ret.empty and ret.std() > 0:
            sharpe = float((ret.mean() - rf_per_period) / ret.std()) * ann_factor
        else:
            sharpe = 0.0
        # Max drawdown
        peak = equity.cummax()
        dd = (equity / peak - 1)
        max_dd = float(dd.min())
        # Audit Q3 #9 — Sortino: numerator is (mean − MAR), denominator is
        # sqrt(mean(min(r−MAR, 0)²)) i.e. downside deviation, not std of
        # negatives. Annualized by sqrt(252).
        if not ret.empty:
            excess = ret - mar
            downside_sq = np.minimum(excess, 0.0) ** 2
            downside_dev = float(np.sqrt(downside_sq.mean()))
            if downside_dev > 0:
                sortino = float((ret.mean() - mar) / downside_dev) * ann_factor
            else:
                sortino = 0.0
        else:
            sortino = 0.0
        # Audit Q3 #10 — Calmar: require at least ~3 months of equity
        # observations. A 1-day backtest produces CAGR in millions.
        years = n / 252
        if years < 0.25 or equity.iloc[0] <= 0:
            cagr = None
            calmar = None
        else:
            cagr_val = float((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1)
            cagr = cagr_val
            calmar = (cagr_val / abs(max_dd)) if max_dd != 0 else None
        wins = sum(1 for t in trades if t.get("from", 0) != 0)  # crude trade count
        return {
            "total_return": total_return,
            "cagr": cagr,
            "sharpe": sharpe,
            "sortino": sortino,
            "calmar": calmar,
            "max_drawdown": max_dd,
            "trades": len(trades),
            "win_rate_proxy": float(wins) / max(len(trades), 1),
            "samples": int(n),
            "risk_free": float(risk_free),
            "mar": float(mar),
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
