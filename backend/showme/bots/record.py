"""Bot record models — pydantic v2.

Sub-system D. A bot binds a strategy + credential + symbol + tick interval
and emits/places orders based on E's evaluate() events.
"""
from __future__ import annotations

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
    price: float
    action: Literal["placed", "shadow", "skipped"]
    order_id: str | None = None
    error: str | None = None
    timestamp: str = Field(default_factory=_now_iso)


class ClosedTrade(BaseModel):
    """C4 fix: append-only round-trip record.

    The runner appends one ``ClosedTrade`` whenever it pairs an exit with
    an open entry. Unlike ``signal_log`` (capped at 100, debug-flavoured),
    this list has no cap and is the canonical source of truth for PnL /
    PERF leaderboards. Pairing happens inside the runner so this list is
    immune to ``signal_log`` FIFO drops over long-running bots.
    """
    entry_timestamp: str
    exit_timestamp: str
    entry_price: float
    exit_price: float
    qty: float
    side: Literal["long", "short"] = "long"
    pnl: float
    bar_index_entry: int
    bar_index_exit: int


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
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)

    @field_validator("signal_log")
    @classmethod
    def _cap_log(cls, v: list[SignalEntry]) -> list[SignalEntry]:
        return v[-SIGNAL_LOG_CAP:] if len(v) > SIGNAL_LOG_CAP else v

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
