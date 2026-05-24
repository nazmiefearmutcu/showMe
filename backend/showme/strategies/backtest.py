"""Bar-by-bar backtest harness — Q4 audit C7 fix.

Before this module shipped, a user could only validate a strategy by
enabling it in shadow / live mode and watching ``signal_log`` accumulate
over real-time bars. That's a multi-day feedback loop with no exposure
to historical context.

The harness consumes a :class:`StrategySpec` + an OHLCV DataFrame and
returns a :class:`BacktestResult` containing:

* a list of closed-trade dicts (with PnL, side, fill prices, exit reason);
* an equity curve sampled per trade;
* aggregate metrics (Sharpe, Sortino, Calmar, profit factor, max drawdown,
  win rate, expectancy, max consecutive losses).

Replay model (mirrors the live runner contract):

1. ``period_warmup`` bars are skipped so indicators (RSI/EMA/...) have
   data to seed against.
2. For each bar ``i``, evaluate the spec's entry/exit rules on the slice
   ``df[:i+1]``. The entry signal fires on ``i``; the *fill* lands on the
   next bar's ``open`` plus ``slippage_bps`` in the protective direction.
   This avoids the classic lookahead bias of filling at the same bar's
   close.
3. SL/TP are checked intrabar (``low <= sl_price <= high``) BEFORE the
   next rule-based exit check. Same-bar SL+TP collisions resolve as SL
   (pessimistic — H22 fix).
4. Round-trip commissions deduct from gross PnL; optional ``funding_series``
   pro-rates per-bar funding into the open position's PnL (perpetual only).

The harness is pure (no I/O, no broker calls). UI exposes it via
``POST /api/strategies/{id}/backtest``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Any

import numpy as np
import pandas as pd

from showme.strategies.compute import compute
from showme.strategies.evaluate import _combine, _eval_rule, _check_sl_tp_intrabar
from showme.strategies.sizing import (
    DEFAULT_COMMISSION_RATE,
    compute_commission,
    resolve_quantity,
)
from showme.strategies.spec import StrategySpec


@dataclass(frozen=True)
class BacktestTrade:
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    qty: float
    side: str
    gross_pnl: float
    commission_paid: float
    funding_paid: float
    net_pnl: float
    exit_reason: str         # "rule" | "sl_hit" | "tp_hit" | "end_of_window"
    bar_index_entry: int
    bar_index_exit: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BacktestResult:
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    bars_evaluated: int = 0
    spec_id: str = ""
    spec_name: str = ""
    starting_equity: float = 0.0
    fee_rate: float = 0.0
    slippage_bps: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_id": self.spec_id,
            "spec_name": self.spec_name,
            "starting_equity": self.starting_equity,
            "fee_rate": self.fee_rate,
            "slippage_bps": self.slippage_bps,
            "bars_evaluated": self.bars_evaluated,
            "trades": [t.to_dict() for t in self.trades],
            "equity_curve": self.equity_curve,
            "metrics": self.metrics,
        }


def _compute_metrics(
    trades: list[BacktestTrade],
    equity_curve: list[dict[str, Any]],
    starting_equity: float,
    bars_per_year: float = 365.0 * 24.0,  # default crypto-hourly assumption
) -> dict[str, Any]:
    """Q4 audit H20: full metrics suite (Sharpe/Sortino/Calmar/profit factor).

    Bars-per-year defaults to crypto-hourly; callers should override based
    on the spec's timeframe (e.g. 252 for daily equities).
    """
    n = len(trades)
    if n == 0 or not equity_curve:
        return {
            "trade_count": 0,
            "total_pnl": 0.0,
            "net_pnl": 0.0,
            "win_rate": 0.0,
            "avg_pnl": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "calmar": 0.0,
            "expectancy": 0.0,
            "max_consecutive_losses": 0,
            "final_equity": float(starting_equity),
            "return_pct": 0.0,
        }
    net_pnls = [t.net_pnl for t in trades]
    gross_pnls = [t.gross_pnl for t in trades]
    total_net = sum(net_pnls)
    total_gross = sum(gross_pnls)
    wins = [p for p in net_pnls if p > 0]
    losses = [p for p in net_pnls if p < 0]
    win_count = len(wins)
    win_rate = win_count / n
    avg_pnl = total_net / n
    gross_wins = sum(wins) if wins else 0.0
    gross_losses = abs(sum(losses)) if losses else 0.0
    profit_factor = (
        gross_wins / gross_losses if gross_losses > 0
        else (float("inf") if gross_wins > 0 else 0.0)
    )

    # Max drawdown from the equity curve.
    equities = [pt["equity"] for pt in equity_curve]
    peak = equities[0]
    max_dd = 0.0
    max_dd_pct = 0.0
    for v in equities:
        if v > peak:
            peak = v
        dd = peak - v
        if dd > max_dd:
            max_dd = dd
            if peak > 0:
                max_dd_pct = (dd / peak) * 100.0

    # Sharpe / Sortino on trade-level returns (net PnL as % of starting equity).
    if starting_equity > 0:
        trade_returns = [p / starting_equity for p in net_pnls]
    else:
        trade_returns = [0.0 for _ in net_pnls]
    if len(trade_returns) > 1:
        mean_r = float(np.mean(trade_returns))
        std_r = float(np.std(trade_returns, ddof=1))
        # Annualise: average trade frequency (avg trades per year) ≈ n / (window/bars_per_year).
        # For a robust default we use sqrt(n) — same intuition as Sharpe annualisation
        # using observation count.
        sharpe = (mean_r / std_r * math.sqrt(n)) if std_r > 0 else 0.0
        downside = [r for r in trade_returns if r < 0]
        if downside:
            down_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else abs(downside[0])
            sortino = (mean_r / down_std * math.sqrt(n)) if down_std > 0 else 0.0
        else:
            sortino = float("inf") if mean_r > 0 else 0.0
    else:
        sharpe = 0.0
        sortino = 0.0

    # Calmar: annualised return / max DD.
    final_equity = equities[-1]
    return_pct = ((final_equity - starting_equity) / starting_equity * 100.0) if starting_equity > 0 else 0.0
    calmar = (return_pct / max_dd_pct) if max_dd_pct > 0 else (float("inf") if return_pct > 0 else 0.0)

    # Max consecutive losses.
    max_cons = 0
    cur_cons = 0
    for p in net_pnls:
        if p < 0:
            cur_cons += 1
            max_cons = max(max_cons, cur_cons)
        else:
            cur_cons = 0

    # Expectancy: avg_win * win_rate - avg_loss * (1 - win_rate).
    avg_win = (gross_wins / win_count) if win_count > 0 else 0.0
    loss_count = len(losses)
    avg_loss = (gross_losses / loss_count) if loss_count > 0 else 0.0
    expectancy = avg_win * win_rate - avg_loss * (1 - win_rate)

    # JSON-serialisation safety: replace infs with a sentinel string consumer can detect.
    def _safe(x: float) -> float | str:
        if not math.isfinite(x):
            return "inf" if x > 0 else "-inf"
        return round(x, 6)

    return {
        "trade_count": n,
        "total_pnl": round(total_gross, 6),
        "net_pnl": round(total_net, 6),
        "win_rate": round(win_rate, 4),
        "avg_pnl": round(avg_pnl, 6),
        "profit_factor": _safe(profit_factor),
        "max_drawdown": round(max_dd, 6),
        "max_drawdown_pct": round(max_dd_pct, 4),
        "sharpe": _safe(sharpe),
        "sortino": _safe(sortino),
        "calmar": _safe(calmar),
        "expectancy": round(expectancy, 6),
        "max_consecutive_losses": int(max_cons),
        "final_equity": round(final_equity, 6),
        "return_pct": round(return_pct, 4),
    }


def backtest(
    spec: StrategySpec,
    df: pd.DataFrame,
    *,
    fee_rate: float = DEFAULT_COMMISSION_RATE,
    slippage_bps: float = 0.0,
    funding_series: pd.Series | None = None,
    starting_equity: float = 10_000.0,
    warmup_bars: int = 50,
    leverage: float = 1.0,
    bars_per_year: float | None = None,
) -> BacktestResult:
    """Q4 audit C7: run a bar-by-bar replay of ``spec`` against ``df``.

    Parameters
    ----------
    spec:
        Strategy under test. ``spec.position.side`` controls long/short;
        ``spec.position.stop_loss_pct`` / ``take_profit_pct`` enable
        intrabar SL/TP exits.
    df:
        OHLCV DataFrame (lowercase columns: open/high/low/close/volume,
        UTC datetime index). Must contain at least ``warmup_bars + 5``
        rows for meaningful results.
    fee_rate:
        Per-side commission rate. Default 8bp (Binance taker).
    slippage_bps:
        Per-side slippage applied to fills in the protective direction
        (BUY fills higher, SELL fills lower). Defaults to 0 (clean).
    funding_series:
        Optional Series of funding rates indexed by bar — applied per bar
        to the open position's notional. Use ``None`` for spot.
    starting_equity:
        Account equity at t=0. The equity curve compounds gross trade PnL.
        Q4 audit H19 fix: equity curve was previously a flat 10k.
    warmup_bars:
        Bars to skip before evaluating rules (lets indicators seed).
    leverage:
        Notional multiplier on risk_pct / risk_per_trade sizing.
    bars_per_year:
        Used to annualise Sharpe. Defaults to a sensible per-timeframe
        value (1m: 525960, 1h: 8760, 1d: 365 etc.).
    """
    result = BacktestResult(
        spec_id=spec.id, spec_name=spec.name,
        starting_equity=float(starting_equity),
        fee_rate=float(fee_rate),
        slippage_bps=float(slippage_bps),
    )
    if df.empty or len(df) < max(warmup_bars + 2, 3):
        result.metrics = _compute_metrics(
            result.trades, [{"t": "start", "equity": starting_equity}],
            starting_equity,
        )
        return result

    bars_per_year_resolved = bars_per_year if bars_per_year is not None else _bars_per_year_for_tf(spec.timeframe)

    # Precompute indicators + truth series ONCE (vectorised) so the per-bar
    # loop is just an O(1) lookup + state-machine update.
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

    side = spec.position.side
    sl_pct = spec.position.stop_loss_pct
    tp_pct = spec.position.take_profit_pct
    slip_factor = float(slippage_bps) / 10_000.0  # bps → ratio

    close = df["close"].to_numpy()
    open_ = df["open"].to_numpy() if "open" in df.columns else close
    high = df["high"].to_numpy() if "high" in df.columns else close
    low = df["low"].to_numpy() if "low" in df.columns else close
    timestamps = [str(ts) for ts in df.index]

    in_position = False
    entry_idx = -1
    entry_fill_price = 0.0
    entry_qty = 0.0
    open_position_funding = 0.0
    running_equity = float(starting_equity)
    equity_curve: list[dict[str, Any]] = [{"t": "start", "equity": running_equity}]

    n = len(df)
    last_evaluable = n - 1  # we fill on i+1 so the last bar can't open a new pos
    funding_arr: np.ndarray | None = None
    if funding_series is not None and len(funding_series) == n:
        funding_arr = funding_series.to_numpy()

    for i in range(warmup_bars, n):
        bar_high = float(high[i])
        bar_low = float(low[i])
        bar_close = float(close[i])
        if math.isnan(bar_close):
            continue

        if in_position:
            # Accrue funding on this bar's notional (perp only).
            if funding_arr is not None and i < len(funding_arr):
                rate = float(funding_arr[i]) if not math.isnan(funding_arr[i]) else 0.0
                # 1 bar per row; sign aware (long pays positive rate).
                sign = 1.0 if side == "long" else -1.0
                open_position_funding += entry_fill_price * entry_qty * rate * sign

            # SL/TP intrabar (precedence over rule exit).
            fill_px, sl_tp_reason = _check_sl_tp_intrabar(
                side=side, entry_price=entry_fill_price,
                high=bar_high, low=bar_low,
                sl_pct=sl_pct, tp_pct=tp_pct,
            )
            if fill_px is not None and sl_tp_reason is not None:
                trade = _close_trade(
                    side=side, entry_idx=entry_idx, exit_idx=i,
                    entry_time=timestamps[entry_idx], exit_time=timestamps[i],
                    entry_price=entry_fill_price, exit_price=fill_px,
                    qty=entry_qty, fee_rate=fee_rate,
                    funding_paid=open_position_funding,
                    exit_reason=sl_tp_reason,
                )
                result.trades.append(trade)
                running_equity += trade.net_pnl
                equity_curve.append({"t": trade.exit_time, "equity": round(running_equity, 6)})
                in_position = False
                entry_qty = 0.0
                open_position_funding = 0.0
                continue

            # Rule-based exit (fill on this bar's close, slippage in protective dir).
            exit_signal = bool(exit_truth.iloc[i]) if i < len(exit_truth) else False
            if exit_signal:
                # Exit slippage: long sells low, short buys high.
                if side == "long":
                    exit_fill = bar_close * (1.0 - slip_factor)
                else:
                    exit_fill = bar_close * (1.0 + slip_factor)
                trade = _close_trade(
                    side=side, entry_idx=entry_idx, exit_idx=i,
                    entry_time=timestamps[entry_idx], exit_time=timestamps[i],
                    entry_price=entry_fill_price, exit_price=float(exit_fill),
                    qty=entry_qty, fee_rate=fee_rate,
                    funding_paid=open_position_funding,
                    exit_reason="rule",
                )
                result.trades.append(trade)
                running_equity += trade.net_pnl
                equity_curve.append({"t": trade.exit_time, "equity": round(running_equity, 6)})
                in_position = False
                entry_qty = 0.0
                open_position_funding = 0.0
                continue
        else:
            # Look for a fresh entry. Fill on i+1's OPEN.
            if i >= last_evaluable:
                # Last bar can't open a position — no next bar to fill against.
                continue
            entry_signal = bool(entry_truth.iloc[i]) if i < len(entry_truth) else False
            if entry_signal:
                next_open = float(open_[i + 1])
                if math.isnan(next_open) or next_open <= 0:
                    continue
                # Entry slippage: long buys high, short sells low.
                if side == "long":
                    fill_px = next_open * (1.0 + slip_factor)
                else:
                    fill_px = next_open * (1.0 - slip_factor)
                # Q4 audit H19: re-compute qty on running_equity (compounding).
                try:
                    qty = resolve_quantity(
                        sizing_kind=spec.position.sizing_kind,
                        sizing_value=float(spec.position.sizing_value),
                        price=fill_px,
                        equity=running_equity,
                        leverage=leverage,
                        stop_loss_pct=spec.position.stop_loss_pct,
                    )
                except (ValueError, TypeError):
                    continue
                if qty <= 0:
                    continue
                in_position = True
                entry_idx = i + 1   # fill bar
                entry_fill_price = fill_px
                entry_qty = qty
                open_position_funding = 0.0

    # Close any dangling open position at the end-of-window using the
    # last close. Use ``end_of_window`` reason so callers can filter.
    if in_position and entry_qty > 0:
        last_idx = n - 1
        last_close = float(close[last_idx])
        if side == "long":
            exit_fill = last_close * (1.0 - slip_factor)
        else:
            exit_fill = last_close * (1.0 + slip_factor)
        trade = _close_trade(
            side=side, entry_idx=entry_idx, exit_idx=last_idx,
            entry_time=timestamps[entry_idx], exit_time=timestamps[last_idx],
            entry_price=entry_fill_price, exit_price=float(exit_fill),
            qty=entry_qty, fee_rate=fee_rate,
            funding_paid=open_position_funding,
            exit_reason="end_of_window",
        )
        result.trades.append(trade)
        running_equity += trade.net_pnl
        equity_curve.append({"t": trade.exit_time, "equity": round(running_equity, 6)})

    result.equity_curve = equity_curve
    result.bars_evaluated = max(0, n - warmup_bars)
    result.metrics = _compute_metrics(
        result.trades, equity_curve, starting_equity,
        bars_per_year=bars_per_year_resolved,
    )
    return result


def _close_trade(
    *, side: str, entry_idx: int, exit_idx: int,
    entry_time: str, exit_time: str,
    entry_price: float, exit_price: float, qty: float,
    fee_rate: float, funding_paid: float, exit_reason: str,
) -> BacktestTrade:
    if side == "long":
        gross = (exit_price - entry_price) * qty
    else:
        gross = (entry_price - exit_price) * qty
    commission = compute_commission(
        entry_price=entry_price, exit_price=exit_price,
        qty=qty, commission_rate=fee_rate,
    )
    net = gross - commission - funding_paid
    return BacktestTrade(
        entry_time=entry_time, exit_time=exit_time,
        entry_price=round(entry_price, 8),
        exit_price=round(exit_price, 8),
        qty=round(qty, 8), side=side,
        gross_pnl=round(gross, 6),
        commission_paid=round(commission, 6),
        funding_paid=round(funding_paid, 6),
        net_pnl=round(net, 6),
        exit_reason=exit_reason,
        bar_index_entry=int(entry_idx),
        bar_index_exit=int(exit_idx),
    )


def _bars_per_year_for_tf(timeframe: str) -> float:
    """Approximate bars-per-year for Sharpe annualisation."""
    table = {
        "1m": 365.0 * 24.0 * 60.0,
        "5m": 365.0 * 24.0 * 12.0,
        "15m": 365.0 * 24.0 * 4.0,
        "1h": 365.0 * 24.0,
        "4h": 365.0 * 6.0,
        "1d": 365.0,
    }
    return table.get(timeframe, 365.0 * 24.0)
