"""Backtest framework: a single in-sample pass (``Backtest``) and a real
walk-forward evaluator built on top of it (``WalkForwardBacktest``).

Plug-in pattern: strategy is a callable
    strategy(bars: pd.DataFrame, state: dict) -> int
where return value is target position in {-1, 0, +1} and ``state`` may
be mutated by the strategy for stickiness across bars.

POSITION BASIS — read this before touching the P&L
--------------------------------------------------
``pos`` is an *exposure fraction of current equity*, not a share count:

    pos = +1  → fully long,  notional = 1.0 x equity
    pos =  0  → flat,        notional = 0
    pos = -1  → fully short,  notional = 1.0 x equity

Both the mark-to-market and the fee are charged on that same basis:

    equity_t = equity_{t-1} * (1 + pos_{t-1} * (P_t / P_{t-1} - 1))
    fee      = |target - pos| * equity * (fee_bps / 10_000)

so a +1% price move on a long position is exactly +1% equity, and a
round trip (0 -> +1 -> 0) costs exactly 2 x fee_bps of equity.

This used to be inconsistent and every reported metric was meaningless:
equity was marked as ``cash += pos * (price - last_price)`` — the P&L of a
SINGLE SHARE — while the fee was charged on ``notional = cash`` (~$10,000
by default). On a $100 stock a 1% move earned $1 while one round trip at
5 bps cost ~$5, so Sharpe / CAGR / Calmar / drawdown were all dominated by
a unit error rather than by the strategy.

Usage:
    bt = Backtest(bars, strategy=my_strategy, fee_bps=5, initial_cash=10_000)
    res = bt.run()          # single IN-SAMPLE pass — no OOS claim
    res.equity_curve        # pd.Series
    res.metrics             # dict

    wf = WalkForwardBacktest(bars, "sma_crossover", n_splits=5)
    wfres = wf.run()        # sequential train/test, OOS-only equity
    wfres.oos_equity_curve
    wfres.summary["worst_fold"]
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
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
    """Bar-by-bar P&L application for a single IN-SAMPLE pass.

    This class makes no out-of-sample claim: the strategy sees every bar it
    is scored on. For an out-of-sample estimate use ``WalkForwardBacktest``.
    """

    def __init__(self, bars: pd.DataFrame, strategy: StrategyFn,
                 *, initial_cash: float = 10_000.0,
                 fee_bps: float = 5.0, allow_short: bool = True,
                 warmup: int = 30, risk_free: float = 0.0,
                 mar: float = 0.0, eval_start: int | None = None) -> None:
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
        # First bar index that is actually traded/scored. Bars before it are
        # still handed to the strategy as history (indicators need a lookback)
        # but produce no position and no equity point. WalkForwardBacktest
        # uses this to score a test slice without discarding its context.
        self.eval_start = eval_start

    def run(self) -> BacktestResult:
        bars = self.bars.reset_index(drop=False)
        n = len(bars)
        start = self.eval_start if self.eval_start is not None else 0
        start = max(0, min(start, max(n - 1, 0)))

        equity = [self.cash0]
        positions = [0]
        trades: list[dict[str, Any]] = []
        state: dict[str, Any] = {}
        eq_val = self.cash0
        pos = 0
        last_price = float(bars["close"].iloc[start])
        for i in range(start + 1, n):
            window = bars.iloc[: i + 1]
            row = bars.iloc[i]
            price = float(row["close"])
            # Mark to market on the SAME basis the fee is charged on:
            # pos is an exposure fraction of equity, so the bar return is
            # pos * simple price return. See the module docstring.
            if pos != 0 and last_price > 0:
                eq_val *= 1.0 + pos * (price / last_price - 1.0)
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
                    # Traded notional is the change in exposure times current
                    # equity: opening 0->+1 turns over 1x equity, flipping
                    # +1->-1 turns over 2x. Same basis as the mark above.
                    turnover = abs(target - pos)
                    notional = turnover * eq_val
                    fee_amt = notional * self.fee
                    eq_val -= fee_amt
                    trades.append({
                        "ts": str(row.iloc[0]),
                        "from": pos, "to": target,
                        "price": price, "fee": fee_amt,
                        "notional": notional,
                    })
                    pos = target
            equity.append(eq_val)
            positions.append(pos)
        idx = bars.iloc[start:start + len(equity), 0]
        eq = pd.Series(equity, index=pd.Index(idx, name=bars.columns[0]))
        ps = pd.Series(positions, index=eq.index)
        metrics = self._metrics(eq, trades, risk_free=self.risk_free, mar=self.mar)
        metrics["in_sample"] = True
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
    rsi_s = 100 - (100 / (1 + rs))
    rsi_s = rsi_s.where(
        ~(loss == 0.0),
        np.where(gain > 0.0, 100.0, 50.0)
    )
    rsi = rsi_s.iloc[-1]
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

# Parameter grids searched on each TRAIN slice. A strategy with an empty grid
# is not fitted at all — its walk-forward result is still strictly OOS, there
# is simply nothing to overfit.
STRATEGY_PARAM_GRID: dict[str, dict[str, list[Any]]] = {
    "sma_crossover": {"fast": [5, 10, 20], "slow": [30, 50, 100]},
    "rsi_meanrev": {"period": [7, 14, 21], "lo": [20, 30], "hi": [70, 80]},
    "buy_and_hold": {},
}


def _param_combos(grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """Expand a grid into concrete kwargs, dropping incoherent combinations."""
    if not grid:
        return [{}]
    keys = sorted(grid)
    combos = []
    for values in itertools.product(*(grid[k] for k in keys)):
        kw = dict(zip(keys, values))
        if "fast" in kw and "slow" in kw and kw["fast"] >= kw["slow"]:
            continue
        if "lo" in kw and "hi" in kw and kw["lo"] >= kw["hi"]:
            continue
        combos.append(kw)
    return combos or [{}]


# ── Walk-forward ───────────────────────────────────────────────────────────
@dataclass
class WalkForwardFold:
    fold: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    train_bars: int
    test_bars: int
    params: dict[str, Any]
    metrics: dict[str, Any]
    oos_return: float


@dataclass
class WalkForwardResult:
    oos_equity_curve: pd.Series
    folds: list[WalkForwardFold] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    trades: list[dict[str, Any]] = field(default_factory=list)


class LeakageError(AssertionError):
    """Raised when a fold's test slice is not strictly after its train slice."""


class WalkForwardBacktest:
    """Sequential train/test evaluation — the thing BTFW always claimed to do.

    The history is cut into ``n_splits`` successive folds. For fold *k* the
    first ``train_pct`` of the fold fits the strategy's parameters by grid
    search; the remainder is then evaluated with those frozen parameters and
    contributes to the reported result. Nothing from a test slice ever
    influences the fit that produced it, and a tripwire asserts the boundary
    on every fold rather than trusting the arithmetic.

    ``anchored`` mode expands the train window from the very first bar;
    ``rolling`` slides a fixed-length train window.

    Reported metrics come from the stitched OOS curve ONLY. The per-fold
    table and ``summary["worst_fold"]`` are always populated so a single
    lucky fold cannot be quoted on its own.
    """

    def __init__(self, bars: pd.DataFrame, strategy_name: str, *,
                 n_splits: int = 5, train_pct: float = 0.7,
                 mode: str = "anchored", initial_cash: float = 10_000.0,
                 fee_bps: float = 5.0, allow_short: bool = True,
                 warmup: int = 30, risk_free: float = 0.0,
                 mar: float = 0.0,
                 param_grid: dict[str, list[Any]] | None = None) -> None:
        if "close" not in bars.columns:
            raise ValueError("bars must have a 'close' column")
        if strategy_name not in STRATEGY_REGISTRY:
            raise ValueError(f"unknown strategy {strategy_name!r}")
        if not 0.1 <= train_pct <= 0.95:
            raise ValueError("train_pct must be within [0.1, 0.95]")
        if n_splits < 2:
            raise ValueError("n_splits must be >= 2")
        if mode not in ("anchored", "rolling"):
            raise ValueError("mode must be 'anchored' or 'rolling'")
        self.bars = bars.copy()
        self.strategy_name = strategy_name
        self.base_fn = STRATEGY_REGISTRY[strategy_name]
        self.n_splits = int(n_splits)
        self.train_pct = float(train_pct)
        self.mode = mode
        self.initial_cash = float(initial_cash)
        self.fee_bps = float(fee_bps)
        self.allow_short = bool(allow_short)
        self.warmup = int(warmup)
        self.risk_free = float(risk_free)
        self.mar = float(mar)
        self.param_grid = (STRATEGY_PARAM_GRID.get(strategy_name, {})
                           if param_grid is None else param_grid)

    def _bind(self, params: dict[str, Any]) -> StrategyFn:
        fn = self.base_fn
        if not params:
            return fn
        def bound(bars: pd.DataFrame, state: dict[str, Any]) -> int:
            return fn(bars, state, **params)
        return bound

    def _score(self, res: BacktestResult) -> float:
        """Fit objective. Sharpe, with a total-return tiebreak; NaN -> -inf."""
        s = res.metrics.get("sharpe")
        if s is None or not np.isfinite(s):
            return float("-inf")
        tr = res.metrics.get("total_return") or 0.0
        return float(s) + 1e-9 * float(tr)

    def _fit(self, bars: pd.DataFrame, train_lo: int, train_hi: int) -> dict[str, Any]:
        """Grid-search on bars[train_lo:train_hi] ONLY."""
        combos = _param_combos(self.param_grid)
        if len(combos) == 1:
            return combos[0]
        train = bars.iloc[:train_hi]          # history up to (not including) test
        best, best_score = combos[0], float("-inf")
        for kw in combos:
            try:
                res = Backtest(
                    train, self._bind(kw), initial_cash=self.initial_cash,
                    fee_bps=self.fee_bps, allow_short=self.allow_short,
                    warmup=max(self.warmup, train_lo), risk_free=self.risk_free,
                    mar=self.mar, eval_start=train_lo,
                ).run()
            except Exception:
                continue
            score = self._score(res)
            if score > best_score:
                best, best_score = kw, score
        return best

    def run(self) -> WalkForwardResult:
        bars = self.bars
        n = len(bars)
        # Reserve warmup bars up front so fold 0 has indicator history.
        usable = n - self.warmup
        if usable < self.n_splits * 4:
            raise ValueError(
                f"not enough bars for {self.n_splits} folds: {n} bars with "
                f"warmup={self.warmup} leaves {usable} usable"
            )
        fold_len = usable // self.n_splits
        idx_labels = [str(v) for v in bars.index]

        folds: list[WalkForwardFold] = []
        oos_returns: list[float] = []
        oos_index: list[Any] = []
        all_trades: list[dict[str, Any]] = []

        for k in range(self.n_splits):
            fold_lo = self.warmup + k * fold_len
            fold_hi = self.warmup + (k + 1) * fold_len if k < self.n_splits - 1 else n
            n_train = max(2, int((fold_hi - fold_lo) * self.train_pct))
            train_lo = 0 if self.mode == "anchored" else fold_lo
            train_hi = fold_lo + n_train          # exclusive
            test_lo = train_hi                    # inclusive
            test_hi = fold_hi                     # exclusive
            if test_hi - test_lo < 2:
                continue

            # ── leakage tripwire ─────────────────────────────────────────
            # The first scored test bar must come strictly after the last bar
            # the fit was allowed to see. Asserted per fold, not assumed.
            if not train_hi <= test_lo:
                raise LeakageError(
                    f"fold {k}: train_hi={train_hi} > test_lo={test_lo} — "
                    "the fit saw bars it is scored on"
                )
            t_train_end = bars.index[train_hi - 1]
            t_test_start = bars.index[test_lo]
            if not t_train_end < t_test_start:
                raise LeakageError(
                    f"fold {k}: train ends {t_train_end} but test starts "
                    f"{t_test_start} — test slice is not strictly after train"
                )

            params = self._fit(bars, train_lo, train_hi)

            # OOS: frozen params, scored only on [test_lo, test_hi).
            res = Backtest(
                bars.iloc[:test_hi], self._bind(params),
                initial_cash=self.initial_cash, fee_bps=self.fee_bps,
                allow_short=self.allow_short,
                warmup=max(self.warmup, test_lo), risk_free=self.risk_free,
                mar=self.mar, eval_start=test_lo,
            ).run()

            fold_ret = res.equity_curve.pct_change().dropna()
            oos_returns.extend(fold_ret.tolist())
            oos_index.extend(list(res.equity_curve.index[1:]))
            for t in res.trades:
                all_trades.append({**t, "fold": k})

            folds.append(WalkForwardFold(
                fold=k,
                train_start=idx_labels[train_lo], train_end=idx_labels[train_hi - 1],
                test_start=idx_labels[test_lo], test_end=idx_labels[test_hi - 1],
                train_bars=train_hi - train_lo, test_bars=test_hi - test_lo,
                params=params, metrics=res.metrics,
                oos_return=float(res.metrics.get("total_return") or 0.0),
            ))

        if not folds:
            raise ValueError("no usable walk-forward folds were produced")

        # Stitch: compound the per-fold OOS returns into one continuous curve.
        eq_vals = [self.initial_cash]
        for r in oos_returns:
            eq_vals.append(eq_vals[-1] * (1.0 + float(r)))
        oos_eq = pd.Series(
            eq_vals,
            index=pd.Index([bars.index[0]] + oos_index, name=bars.index.name),
        )
        oos_metrics = Backtest._metrics(oos_eq, all_trades,
                                        risk_free=self.risk_free, mar=self.mar)
        oos_metrics["in_sample"] = False

        worst = min(folds, key=lambda f: f.oos_return)
        positive = sum(1 for f in folds if f.oos_return > 0)
        summary = {
            "strategy": self.strategy_name,
            "walk_mode": self.mode,
            "n_splits": len(folds),
            "train_pct": self.train_pct,
            "oos_sharpe": oos_metrics.get("sharpe"),
            "oos_cagr": oos_metrics.get("cagr"),
            "oos_total_return": oos_metrics.get("total_return"),
            "oos_max_drawdown": oos_metrics.get("max_drawdown"),
            "positive_steps_pct": positive / len(folds),
            "trades": len(all_trades),
            "in_sample": False,
            # Reported so a single flattering fold cannot be quoted alone.
            "worst_fold": {
                "fold": worst.fold,
                "test_start": worst.test_start,
                "test_end": worst.test_end,
                "params": worst.params,
                "oos_return": worst.oos_return,
                "sharpe": worst.metrics.get("sharpe"),
                "max_drawdown": worst.metrics.get("max_drawdown"),
            },
            "params_per_fold": [f.params for f in folds],
        }
        return WalkForwardResult(oos_equity_curve=oos_eq, folds=folds,
                                 summary=summary, trades=all_trades)
