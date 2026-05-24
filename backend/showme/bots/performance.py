"""Pure-aggregation PnL computation from bot signal_log / closed_trades_log.

Sub-system I. Derives Trade objects + metrics from either the legacy
``signal_log`` (debug-only, FIFO-capped) or the canonical
``closed_trades_log`` (C4 fix, no cap) on each BotRecord.

V1.1 changes:
* Side-aware PnL math via ``strategies.sizing.compute_pnl`` — long + short.
* ``compute_trades`` accepts a ``sizing_kind`` arg and computes qty via
  ``strategies.sizing.resolve_quantity`` so ``fixed_base`` no longer reports
  ``(exit-entry)*sizing/entry`` (which was off by 60000× for 2 BTC trades).
* ``compute_trades_from_closed`` reads the new ``closed_trades_log``
  directly so long-running bots whose ``signal_log`` overflowed still
  produce accurate aggregates.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Iterable

from showme.bots.record import ClosedTrade, SignalEntry
from showme.strategies.sizing import (
    Side,
    SizingKind,
    compute_pnl,
    compute_pnl_pct,
    resolve_quantity,
)


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
    *,
    sizing_kind: SizingKind = "fixed_quote",
    side: Side = "long",
    equity: float = 10_000.0,
) -> list[Trade]:
    """Walk a bot's signal_log and pair entries with subsequent exits (FIFO).

    Skips entries with action == "skipped" (those didn't actually fire).
    Open positions (entry without matching exit) are NOT emitted — we
    only count closed round-trips.

    H-SUP-3 fix: ``sizing_kind`` selects the qty formula via the shared
    sizing module. The legacy default (``fixed_quote``) reproduces the
    previous behaviour exactly: ``qty = sizing_value / entry_price`` so
    ``pnl = (exit - entry) * sizing_value / entry``. Other ``sizing_kind``
    values now produce the *correct* qty for that strategy.

    Defensive: invalid sizing inputs (e.g. ``sizing_value <= 0`` or
    ``risk_pct`` > 100) cause the pair to be silently skipped rather than
    fail the whole route. The runner-side guard in ``_dispatch_*`` is the
    real safety net.
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
            try:
                qty = resolve_quantity(
                    sizing_kind=sizing_kind,
                    sizing_value=sizing_value,
                    price=entry.price,
                    equity=equity,
                )
            except ValueError:
                # Skip a pair whose sizing inputs don't validate; the
                # runner-side guard should already have rejected this bot.
                continue
            pnl = compute_pnl(
                entry_price=entry.price,
                exit_price=s.price,
                side=side,
                entry_qty=qty,
            )
            pnl_pct = compute_pnl_pct(
                entry_price=entry.price,
                exit_price=s.price,
                side=side,
            )
            trades.append(Trade(
                entry_time=entry.bar_time or entry.timestamp or "",
                exit_time=s.bar_time or s.timestamp or "",
                entry_price=entry.price,
                exit_price=s.price,
                qty=qty,
                pnl=pnl,
                pnl_pct=pnl_pct,
            ))
    return trades


def compute_trades_from_closed(
    closed: Iterable[ClosedTrade],
) -> list[Trade]:
    """C4 fix: build Trade aggregates from the append-only closed-trades log.

    Use this in preference to ``compute_trades`` for any bot that has been
    running long enough for ``signal_log`` to overflow its 100-entry cap.
    The closed-trades log preserves every round-trip the runner has paired.
    """
    out: list[Trade] = []
    for ct in closed:
        pnl_pct = compute_pnl_pct(
            entry_price=ct.entry_price,
            exit_price=ct.exit_price,
            side=ct.side,
        )
        out.append(Trade(
            entry_time=ct.entry_timestamp,
            exit_time=ct.exit_timestamp,
            entry_price=ct.entry_price,
            exit_price=ct.exit_price,
            qty=ct.qty,
            pnl=ct.pnl,
            pnl_pct=pnl_pct,
        ))
    return out


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
