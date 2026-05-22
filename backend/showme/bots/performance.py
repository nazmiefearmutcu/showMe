"""Pure-aggregation PnL computation from bot signal_log.

Sub-system I. No new storage — derives Trade objects + metrics from
the existing signal_log on each BotRecord.

V1 limitations:
* Long-only PnL math (shorts deferred)
* No commission / slippage modelling
* No mark-to-market on open positions — only closed trades
* sizing_value (from strategy spec) used as trade qty
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Iterable

from showme.bots.record import SignalEntry


@dataclass(frozen=True)
class Trade:
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    qty: float
    pnl: float
    pnl_pct: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_trades(
    signal_log: Iterable[SignalEntry],
    sizing_value: float = 100.0,
) -> list[Trade]:
    """Walk a bot's signal_log and pair entries with subsequent exits (FIFO).

    Skips entries with action == "skipped" (those didn't actually fire).
    Open positions (entry without matching exit) are NOT emitted — we
    only count closed round-trips for v1.
    """
    open_entries: list[SignalEntry] = []
    trades: list[Trade] = []
    for s in signal_log:
        if s.action == "skipped":
            continue
        if s.kind == "entry":
            open_entries.append(s)
        elif s.kind == "exit" and open_entries:
            entry = open_entries.pop(0)
            if entry.price <= 0:
                continue
            # Long-only PnL.
            pnl = (s.price - entry.price) * sizing_value / entry.price
            pnl_pct = (s.price - entry.price) / entry.price * 100
            trades.append(Trade(
                entry_time=entry.bar_time or entry.timestamp or "",
                exit_time=s.bar_time or s.timestamp or "",
                entry_price=entry.price,
                exit_price=s.price,
                qty=sizing_value,
                pnl=pnl,
                pnl_pct=pnl_pct,
            ))
    return trades


def compute_metrics(trades: list[Trade]) -> dict[str, Any]:
    """Aggregate metrics over a list of Trade. Empty input → zeros."""
    n = len(trades)
    if n == 0:
        return {
            "total_pnl": 0.0,
            "win_rate": 0.0,
            "trade_count": 0,
            "avg_pnl": 0.0,
            "max_drawdown": 0.0,
        }
    pnls = [t.pnl for t in trades]
    total = sum(pnls)
    wins = sum(1 for p in pnls if p > 0)
    win_rate = wins / n
    avg = total / n
    # Max drawdown over cumulative pnl:
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cum += p
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd
    return {
        "total_pnl": round(total, 4),
        "win_rate": round(win_rate, 4),
        "trade_count": n,
        "avg_pnl": round(avg, 4),
        "max_drawdown": round(max_dd, 4),
    }


def compute_equity_curve(
    trades: list[Trade],
    starting_equity: float = 10_000.0,
) -> list[dict[str, Any]]:
    """Cumulative equity after each closed trade."""
    out: list[dict[str, Any]] = [{"t": "start", "equity": starting_equity}]
    equity = starting_equity
    for t in trades:
        equity += t.pnl
        out.append({"t": t.exit_time, "equity": round(equity, 4)})
    return out
