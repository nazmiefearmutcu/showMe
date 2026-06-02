"""Strategy spec models (pydantic v2).

Sub-system E. The spec is a JSON document that describes entry/exit
rules in terms of indicator signals. D's bot runner consumes this.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


RuleKind = Literal[
    "crosses_above", "crosses_below",
    "greater_than", "less_than",
    "equals_approximately",
]


class AssetFilter(BaseModel):
    exchanges: list[str] | None = None
    symbols: list[str] | None = None
    asset_classes: list[str] | None = None


class IndicatorRef(BaseModel):
    alias: str = Field(..., min_length=1, max_length=64)
    id: str = Field(..., min_length=1, max_length=64)  # indicator id from F's catalog
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("alias")
    @classmethod
    def _alias_alnum(cls, v: str) -> str:
        if not all(c.isalnum() or c == "_" for c in v):
            raise ValueError("alias must be alphanumeric/underscore")
        return v


class Rule(BaseModel):
    kind: RuleKind
    left: str = Field(..., min_length=1)
    right: str = Field(..., min_length=1)
    tolerance: float | None = None  # only for equals_approximately


class Position(BaseModel):
    side: Literal["long", "short"] = "long"
    # Q4 audit C5 fix: ``risk_per_trade`` enables Van Tharp R-multiple sizing
    # (notional = equity * risk_pct / stop_loss_pct). Requires ``stop_loss_pct``
    # to be set on this position; ``evaluate_quantity`` raises otherwise.
    sizing_kind: Literal[
        "fixed_quote", "fixed_base", "risk_pct", "risk_per_trade",
    ] = "fixed_quote"
    sizing_value: float = 100.0
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    # Q4 audit H10 fix: entry order type. Live runner consults this so a
    # strategy can opt out of MARKET+IOC. Limit orders default to spec's
    # ``limit_price_offset_pct`` away from the signal close (in the
    # protective direction for the side).
    entry_order_type: Literal["market", "limit", "stop_limit"] = "market"
    limit_price_offset_pct: float = 0.0  # for limit / stop_limit entries

    @model_validator(mode="after")
    def _validate_position(self) -> Position:
        import math
        if not math.isfinite(self.sizing_value) or self.sizing_value <= 0:
            raise ValueError("sizing_value must be a finite positive number")
        if self.sizing_kind in ("risk_pct", "risk_per_trade"):
            if not (0.0 < self.sizing_value <= 100.0):
                raise ValueError(f"{self.sizing_kind} sizing_value must be in (0, 100]")
        if self.sizing_kind == "risk_per_trade":
            if self.stop_loss_pct is None or self.stop_loss_pct <= 0 or not math.isfinite(self.stop_loss_pct):
                raise ValueError("risk_per_trade requires stop_loss_pct to be set and > 0")
        if self.stop_loss_pct is not None:
            if not math.isfinite(self.stop_loss_pct) or self.stop_loss_pct <= 0:
                raise ValueError("stop_loss_pct must be a finite positive number")
        if self.take_profit_pct is not None:
            if not math.isfinite(self.take_profit_pct) or self.take_profit_pct <= 0:
                raise ValueError("take_profit_pct must be a finite positive number")
        return self


class StrategySpec(BaseModel):
    id: str = Field(default_factory=_new_id)
    name: str = Field(..., min_length=1, max_length=128)
    description: str = ""
    version: int = 1
    asset_filter: AssetFilter = Field(default_factory=AssetFilter)
    timeframe: Literal["1m", "5m", "15m", "1h", "4h", "1d"] = "1h"
    indicators: list[IndicatorRef] = Field(default_factory=list)
    entry_rules: list[Rule] = Field(default_factory=list)
    entry_logic: Literal["all", "any"] = "all"
    exit_rules: list[Rule] = Field(default_factory=list)
    exit_logic: Literal["all", "any"] = "any"
    position: Position = Field(default_factory=Position)
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)

    @field_validator("indicators")
    @classmethod
    def _alias_unique(cls, v: list[IndicatorRef]) -> list[IndicatorRef]:
        aliases = [r.alias for r in v]
        if len(aliases) != len(set(aliases)):
            raise ValueError("indicator aliases must be unique within a strategy")
        return v

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, s: str) -> "StrategySpec":
        return cls.model_validate(json.loads(s))

    def validate_against_catalog(self, catalog_indicator_ids: set[str]) -> None:
        """Raise ValueError if any indicator.id is not in the catalog or if
        a rule operand references a non-existent alias."""
        for ref in self.indicators:
            if ref.id not in catalog_indicator_ids:
                raise ValueError(f"unknown indicator id: {ref.id}")
        aliases = {r.alias for r in self.indicators}
        price_fields = {"close", "open", "high", "low", "volume"}
        all_rules = self.entry_rules + self.exit_rules
        for rule in all_rules:
            for operand in (rule.left, rule.right):
                if operand.startswith("literal:"):
                    try:
                        float(operand.split(":", 1)[1])
                    except ValueError as exc:
                        raise ValueError(f"invalid literal: {operand}") from exc
                elif operand in price_fields:
                    continue
                elif operand not in aliases:
                    raise ValueError(f"unknown operand: {operand}")
        if any(r.kind == "equals_approximately" and r.tolerance is None
               for r in all_rules):
            raise ValueError("equals_approximately requires tolerance")
