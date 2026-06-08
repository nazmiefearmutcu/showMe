"""Bot record models — pydantic v2.

Sub-system D. A bot binds a strategy + credential + symbol + tick interval
and emits/places orders based on E's evaluate() events.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


SIGNAL_LOG_CAP = 100


# C7 fix: timeframe → default tick interval (seconds). Quarter-of-bar
# default keeps an active bar from getting more than ~4 tick checks while
# never falling under the global 5s floor / 3600s ceiling.
_TF_SECONDS: dict[str, int] = {
    "1m": 60, "5m": 300, "15m": 900, "1h": 3600,
    "4h": 14400, "1d": 86400,
}


def default_tick_interval(timeframe: str) -> int:
    """Return a sensible per-timeframe default tick interval.

    Used both as a fallback when the user doesn't pass an explicit value
    and as a basis for the ``BotRecord`` validator that clamps wildly
    decoupled (TF, tick_interval) pairs.

    * 1m  →   60s / 4 = 15s
    * 5m  →  300s / 4 = 75s
    * 15m →  900s / 4 = 225s
    * 1h  → 3600s / 4 = 900s
    * 4h  → 14400s / 4 → clamped to 3600s ceiling
    * 1d  → 86400s / 4 → clamped to 3600s ceiling
    """
    tf_s = _TF_SECONDS.get(timeframe, 60)
    return max(5, min(3600, tf_s // 4))


class SignalEntry(BaseModel):
    bar_index: int
    bar_time: str
    kind: Literal["entry", "exit"]
    price: float                       # signal price (last close at evaluate time)
    action: Literal["placed", "shadow", "skipped"]
    order_id: str | None = None
    error: str | None = None
    timestamp: str = Field(default_factory=_now_iso)
    # Q4 audit C2 fix: thread broker-confirmed fill price so pairing PnL
    # can compute against the *actual* execution price (not the signal
    # bar close which doesn't reflect slippage / partial fills).
    fill_price: float | None = None
    # Q4 audit H17 fix: persist the qty computed at entry-time. Exit
    # pairing reads this so a strategy whose equity drifted between
    # entry and exit doesn't silently re-size the round-trip.
    qty: float | None = None
    # Q4 audit H11 fix: bar's close-time (OHLCV ts is OPEN-time). Surfaces
    # in PERF / UI so users know whether the "entry at 09:00" applies to
    # the bar that opened at 09:00 (closed at 10:00) or vice versa.
    bar_close_time: str | None = None
    # Q4 audit C9 fix: SL/TP intrabar hit reason ("sl_hit" / "tp_hit").
    reason: str | None = None
    # H13 honesty: provenance of the equity used to size a LIVE order.
    # ``"broker"`` = real broker.account() equity; ``"fallback_10k"`` = the
    # documented $10k floor when the broker exposed no usable equity. ``None``
    # for shadow entries (no real order sized) and for persisted records that
    # pre-date this field. The UI flags ``fallback_10k`` so a user knows a
    # live order was sized on the fallback, not real broker equity.
    equity_source: str | None = None


class ClosedTrade(BaseModel):
    """C4 fix: append-only round-trip record.

    The runner appends one ``ClosedTrade`` whenever it pairs an exit with
    an open entry. Unlike ``signal_log`` (capped at 100, debug-flavoured),
    this list has no cap and is the canonical source of truth for PnL /
    PERF leaderboards. Pairing happens inside the runner so this list is
    immune to ``signal_log`` FIFO drops over long-running bots.

    Q4 audit additions (all optional for backward compat):
    * ``commission_paid`` — round-trip fees deducted from gross PnL.
    * ``funding_paid`` — cumulative funding rate cost (perps only).
    * ``net_pnl`` — gross - commission - funding (preferred reporting field).
    * ``exit_reason`` — "exit_rule" | "sl_hit" | "tp_hit" | "manual".
    """
    entry_timestamp: str
    exit_timestamp: str
    entry_price: float
    exit_price: float
    qty: float
    side: Literal["long", "short"] = "long"
    pnl: float                              # gross PnL (legacy field, no fees)
    bar_index_entry: int
    bar_index_exit: int
    commission_paid: float = 0.0
    funding_paid: float = 0.0
    net_pnl: float | None = None
    exit_reason: str | None = None


class BotRecord(BaseModel):
    id: str = Field(default_factory=_new_id)
    strategy_id: str
    credential_id: str
    exchange_id: str
    symbol: str = Field(..., min_length=1)
    timeframe: Literal["1m", "5m", "15m", "1h", "4h", "1d"] = "1h"
    tick_interval_seconds: int = Field(default=60, ge=5, le=3600)
    mode: Literal["shadow", "live"] = "shadow"
    enabled: bool = False
    last_processed_event: SignalEntry | None = None
    signal_log: list[SignalEntry] = Field(default_factory=list)
    # C4 fix: separate append-only closed-trades list (no cap). Existing
    # bot files on disk that pre-date this field get an empty default.
    closed_trades_log: list[ClosedTrade] = Field(default_factory=list)
    # Q4 audit C3 fix: per-bot commission rate override. Defaults to 8bp
    # (Binance taker). Strategy UI can override on creation; aggregator
    # / PERF route uses this when reporting net_pnl.
    commission_rate: float = Field(default=0.0008, ge=0.0, le=0.05)
    # Q4 audit C5 fix: per-bot leverage. Live runners apply this to risk_pct
    # sizing (notional = equity * pct * leverage). Defaults to 1× spot.
    leverage: float = Field(default=1.0, ge=1.0, le=125.0)
    # Q4 audit C4 fix: running funding-rate accrual (perp / futures only).
    # Updated each tick by ``runner._accrue_funding``; deducted from PnL
    # at close-time.
    cumulative_funding_pnl: float = 0.0
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)

    @field_validator("symbol")
    @classmethod
    def _validate_symbol(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("symbol must be a string")
        if re.search(r"[\x00-\x1f\x7f-\x9f]", v):
            raise ValueError("symbol must not contain control characters or newlines")
        trimmed = v.strip().upper()
        if not trimmed:
            raise ValueError("symbol must not be empty or whitespace-only")
        if not re.match(r"^[A-Z0-9]+(?:/[A-Z0-9]+)?$", trimmed):
            raise ValueError("symbol must be alphanumeric, optionally separated by a slash (e.g. BTC/USDT or AAPL)")
        return trimmed

    @field_validator("signal_log")
    @classmethod
    def _cap_log(cls, v: list[SignalEntry]) -> list[SignalEntry]:
        return v[-SIGNAL_LOG_CAP:] if len(v) > SIGNAL_LOG_CAP else v

    @model_validator(mode="before")
    @classmethod
    def _set_default_tick_interval(cls, data: Any) -> Any:
        if isinstance(data, dict):
            timeframe = data.get("timeframe", "1h")
            if "tick_interval_seconds" not in data or data["tick_interval_seconds"] is None:
                data["tick_interval_seconds"] = default_tick_interval(timeframe)
        return data

    @model_validator(mode="after")
    def _check_tick_interval_vs_timeframe(self) -> "BotRecord":
        """C-RUNTIME-1 fix: refuse pairs that would create extreme tick rates.

        We only reject the most pathological combinations the audit
        identified — the runner already de-dupes sub-bar ticks so
        moderate over-polling is harmless.

        * ``tick_interval_seconds`` more than 4× *slower* than the bar
          (e.g. tick=3600s on a 1m timeframe → 60 bars per tick, signal
          skip risk). Bars whose 4× length exceeds the global tick
          ceiling (3600s) are exempt because the field already caps the
          tick at 3600s.
        * For 4h+ timeframes, reject sub-30s ticks (e.g. ``(1d, 5s)``
          generates 17,280 ticks/day — rate-limit-ban risk that the
          audit cited explicitly). Sub-hour timeframes accept the
          global 5s floor unchanged.

        Reasonable defaults like (1h, 60s), (1h, 10s), and (15m, 5s)
        remain accepted.
        """
        tf_s = _TF_SECONDS.get(self.timeframe, 60)
        # Reject "too slow": tick more than 4× the bar period. Skip the
        # check for 4h/1d where the 3600s global ceiling already caps
        # tick faster than 4× bar period.
        ceiling_cap = tf_s * 4
        if ceiling_cap <= 3600 and self.tick_interval_seconds > ceiling_cap:
            raise ValueError(
                f"tick_interval_seconds={self.tick_interval_seconds} too slow "
                f"for timeframe={self.timeframe}; would skip bars. "
                f"Maximum recommended is {ceiling_cap}s."
            )
        # Reject "too aggressive" only on 4h+ where the bar is so long
        # that aggressive polling is pure rate-limit waste. The audit's
        # example of ``(1d, 5s)`` falls here. ``(1d, 30s)`` is still 2880
        # ticks/day per bot — generous but allowed.
        if tf_s >= 14400 and self.tick_interval_seconds < 30:
            raise ValueError(
                f"tick_interval_seconds={self.tick_interval_seconds} too aggressive "
                f"for timeframe={self.timeframe}; rate-limit-ban risk. "
                f"Minimum recommended is 30s on 4h+ timeframes."
            )
        return self

    def append_signal(self, entry: SignalEntry) -> "BotRecord":
        """Return a new record with the entry appended (FIFO-capped)."""
        new_log = (self.signal_log + [entry])[-SIGNAL_LOG_CAP:]
        return self.model_copy(update={
            "signal_log": new_log,
            "last_processed_event": entry,
            "updated_at": _now_iso(),
        })

    def append_closed_trade(self, trade: ClosedTrade) -> "BotRecord":
        """C4 fix: append a closed round-trip. Caller computes the PnL.

        The closed-trade list has no cap; PERF route reads from here
        directly and is immune to ``signal_log`` FIFO drops.
        """
        return self.model_copy(update={
            "closed_trades_log": self.closed_trades_log + [trade],
            "updated_at": _now_iso(),
        })

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, s: str) -> "BotRecord":
        return cls.model_validate_json(s)
