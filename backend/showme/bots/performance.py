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

Q4 audit 2026-05-24:
* ``compute_pnl`` callers now subtract commission via ``compute_commission``;
  ``Trade`` carries gross + net.
* ``compute_metrics`` adds Sharpe, Sortino, profit_factor, expectancy_R,
  max_consecutive_losses.
* ``compute_equity_curve`` compounds running equity (was a flat 10k).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Any, Iterable

import numpy as np

from showme.bots.record import ClosedTrade, SignalEntry
from showme.strategies.sizing import (
    DEFAULT_COMMISSION_RATE,
    Side,
    SizingKind,
    compute_commission,
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
    pnl: float                            # gross PnL (legacy)
    pnl_pct: float
    commission_paid: float = 0.0
    funding_paid: float = 0.0
    net_pnl: float | None = None
    side: str = "long"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_trades(
    signal_log: Iterable[SignalEntry],
    sizing_value: float = 100.0,
    *,
    sizing_kind: SizingKind = "fixed_quote",
    side: Side = "long",
    equity: float = 10_000.0,
    commission_rate: float = 0.0,
    leverage: float = 1.0,
    stop_loss_pct: float | None = None,
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
            # Q4 audit H17: prefer the entry's persisted qty over recompute.
            # Falls back to recompute only for legacy entries (qty is None)
            # so existing bots keep producing aggregates.
            qty: float
            if entry.qty is not None and entry.qty > 0:
                qty = float(entry.qty)
            else:
                try:
                    qty = resolve_quantity(
                        sizing_kind=sizing_kind,
                        sizing_value=sizing_value,
                        price=entry.price,
                        equity=equity,
                        leverage=leverage,
                        stop_loss_pct=stop_loss_pct,
                    )
                except (ValueError, TypeError):
                    # Skip a pair whose sizing inputs don't validate.
                    continue
            # Use fill price if both legs have one (broker-confirmed); else
            # signal price (last close at evaluate time).
            entry_px = float(entry.fill_price) if entry.fill_price else float(entry.price)
            exit_px = float(s.fill_price) if s.fill_price else float(s.price)
            pnl = compute_pnl(
                entry_price=entry_px,
                exit_price=exit_px,
                side=side,
                entry_qty=qty,
            )
            pnl_pct = compute_pnl_pct(
                entry_price=entry_px,
                exit_price=exit_px,
                side=side,
            )
            commission = compute_commission(
                entry_price=entry_px, exit_price=exit_px,
                qty=qty, commission_rate=commission_rate,
            )
            net = pnl - commission
            trades.append(Trade(
                entry_time=entry.bar_time or entry.timestamp or "",
                exit_time=s.bar_time or s.timestamp or "",
                entry_price=entry_px,
                exit_price=exit_px,
                qty=qty,
                pnl=pnl,
                pnl_pct=pnl_pct,
                commission_paid=commission,
                funding_paid=0.0,
                net_pnl=net,
                side=side,
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
        commission = float(ct.commission_paid or 0.0)
        funding = float(ct.funding_paid or 0.0)
        net = (
            float(ct.net_pnl) if ct.net_pnl is not None
            else float(ct.pnl) - commission - funding
        )
        out.append(Trade(
            entry_time=ct.entry_timestamp,
            exit_time=ct.exit_timestamp,
            entry_price=ct.entry_price,
            exit_price=ct.exit_price,
            qty=ct.qty,
            pnl=ct.pnl,
            pnl_pct=pnl_pct,
            commission_paid=commission,
            funding_paid=funding,
            net_pnl=net,
            side=ct.side,
        ))
    return out


def _safe_float(x: float) -> float | str:
    """JSON-serialisation safety for +/-inf in metric payloads."""
    if not math.isfinite(x):
        return "inf" if x > 0 else "-inf"
    return round(x, 6)


def compute_metrics(trades: list[Trade]) -> dict[str, Any]:
    """Aggregate metrics over a list of Trade. Empty input → zeros.

    Q4 audit H20 fix: now reports Sharpe, Sortino, profit_factor,
    expectancy, max_consecutive_losses, and net_pnl alongside the
    pre-existing total_pnl / win_rate / max_drawdown.
    """
    n = len(trades)
    if n == 0:
        return {
            "total_pnl": 0.0,
            "net_pnl": 0.0,
            "win_rate": 0.0,
            "trade_count": 0,
            "avg_pnl": 0.0,
            "max_drawdown": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "max_consecutive_losses": 0,
        }
    # Use net_pnl (commission-adjusted) when present; fall back to gross pnl
    # so legacy callers still get sensible numbers.
    net_pnls = [
        float(t.net_pnl) if t.net_pnl is not None else float(t.pnl)
        for t in trades
    ]
    gross_pnls = [float(t.pnl) for t in trades]
    total = sum(gross_pnls)
    total_net = sum(net_pnls)
    wins_count = sum(1 for p in net_pnls if p > 0)
    losses_arr = [p for p in net_pnls if p < 0]
    wins_arr = [p for p in net_pnls if p > 0]
    win_rate = wins_count / n
    avg = total_net / n

    # Max drawdown over cumulative NET pnl (running equity is what users see).
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in net_pnls:
        cum += p
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd

    # Profit factor: sum(wins)/abs(sum(losses)).
    gross_wins = sum(wins_arr) if wins_arr else 0.0
    gross_losses = abs(sum(losses_arr)) if losses_arr else 0.0
    profit_factor = (
        gross_wins / gross_losses if gross_losses > 0
        else (float("inf") if gross_wins > 0 else 0.0)
    )

    # Sharpe / Sortino on per-trade pnl.
    if n > 1:
        mean_r = float(np.mean(net_pnls))
        std_r = float(np.std(net_pnls, ddof=1))
        sharpe = (mean_r / std_r * math.sqrt(n)) if std_r > 0 else 0.0
        if losses_arr:
            down_std = (
                float(np.std(losses_arr, ddof=1)) if len(losses_arr) > 1
                else abs(losses_arr[0])
            )
            sortino = (mean_r / down_std * math.sqrt(n)) if down_std > 0 else 0.0
        else:
            sortino = float("inf") if mean_r > 0 else 0.0
    else:
        sharpe = 0.0
        sortino = 0.0

    # Expectancy.
    avg_win = (gross_wins / len(wins_arr)) if wins_arr else 0.0
    avg_loss = (gross_losses / len(losses_arr)) if losses_arr else 0.0
    expectancy = avg_win * win_rate - avg_loss * (1 - win_rate)

    # Max consecutive losses.
    max_cons = 0
    cur_cons = 0
    for p in net_pnls:
        if p < 0:
            cur_cons += 1
            max_cons = max(max_cons, cur_cons)
        else:
            cur_cons = 0

    return {
        "total_pnl": round(total, 4),
        "net_pnl": round(total_net, 4),
        "win_rate": round(win_rate, 4),
        "trade_count": n,
        "avg_pnl": round(avg, 4),
        "max_drawdown": round(max_dd, 4),
        "sharpe": _safe_float(sharpe),
        "sortino": _safe_float(sortino),
        "profit_factor": _safe_float(profit_factor),
        "expectancy": round(expectancy, 4),
        "max_consecutive_losses": int(max_cons),
    }


def compute_equity_curve(
    trades: list[Trade],
    starting_equity: float = 10_000.0,
) -> list[dict[str, Any]]:
    """Cumulative equity after each closed trade.

    Q4 audit H19 fix: the running equity now compounds — previous version
    seeded a fixed 10k and never updated past the cap. We use ``net_pnl``
    when present (commission-adjusted) so the curve reflects what the user
    actually keeps.
    """
    out: list[dict[str, Any]] = [{"t": "start", "equity": starting_equity}]
    equity = starting_equity
    for t in trades:
        delta = float(t.net_pnl) if t.net_pnl is not None else float(t.pnl)
        equity += delta
        out.append({"t": t.exit_time, "equity": round(equity, 4)})
    return out
