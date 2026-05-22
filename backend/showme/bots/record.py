"""Bot record models — pydantic v2.

Sub-system D. A bot binds a strategy + credential + symbol + tick interval
and emits/places orders based on E's evaluate() events.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


SIGNAL_LOG_CAP = 100


class SignalEntry(BaseModel):
    bar_index: int
    bar_time: str
    kind: Literal["entry", "exit"]
    price: float
    action: Literal["placed", "shadow", "skipped"]
    order_id: str | None = None
    error: str | None = None
    timestamp: str = Field(default_factory=_now_iso)


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
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)

    @field_validator("signal_log")
    @classmethod
    def _cap_log(cls, v: list[SignalEntry]) -> list[SignalEntry]:
        return v[-SIGNAL_LOG_CAP:] if len(v) > SIGNAL_LOG_CAP else v

    def append_signal(self, entry: SignalEntry) -> "BotRecord":
        """Return a new record with the entry appended (FIFO-capped)."""
        new_log = (self.signal_log + [entry])[-SIGNAL_LOG_CAP:]
        return self.model_copy(update={
            "signal_log": new_log,
            "last_processed_event": entry,
            "updated_at": _now_iso(),
        })

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, s: str) -> "BotRecord":
        return cls.model_validate_json(s)
