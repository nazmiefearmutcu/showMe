"""Shared Pydantic request models used by the route family modules.

Per SEC-05: every POST/PUT endpoint that takes a body validates it through
one of these models so a stray oversized field can't reach the worker pool.
``ConfigDict(extra="ignore")`` keeps older clients (that send extra
fields) from breaking.

These are reexported from ``showme.server`` so existing callers keep
working — the server module wires the index entry models too.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FunctionIndexEntry(BaseModel):
    code: str
    name: str
    category: str
    description: str = ""
    asset_classes: list[str] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)


class VeryfinderBatchRequest(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)
    symbol: str | None = Field(default=None, max_length=32)
    topic: str | None = Field(default=None, max_length=120)
    sample: int = Field(default=25, ge=1, le=500)
    source: str = Field(default="auto", max_length=24)
    engine: str = Field(default="rules", max_length=24)
    limit: int = Field(default=50, ge=1, le=500)


class OrderRequest(BaseModel):
    """Validated body for POST /api/broker/orders."""

    model_config = ConfigDict(extra="ignore")

    broker: str | None = Field(default=None, max_length=32)
    symbol: str = Field(..., min_length=1, max_length=32)
    side: str = Field(default="buy", max_length=8)
    quantity: float = Field(..., gt=0, le=1e9)
    order_type: str = Field(default="market", max_length=16)
    time_in_force: str = Field(default="day", max_length=8)
    limit_price: float | None = Field(default=None, ge=0, le=1e12)
    stop_price: float | None = Field(default=None, ge=0, le=1e12)
    notes: str = Field(default="", max_length=512)
    leverage: float | None = Field(default=None, ge=0, le=125)


class AskBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query: str = Field(default="", max_length=2048)
    plan: dict[str, Any] | None = None
    profile: dict[str, Any] | None = None


class XAnalyzeBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    posts: list[dict[str, Any]] = Field(default_factory=list, max_length=2048)
    symbol: str | None = Field(default=None, max_length=32)
    topic: str | None = Field(default=None, max_length=200)
    lang: str | None = Field(default=None, max_length=8)


class XClassifyBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    texts: list[str] = Field(..., min_length=1, max_length=512)
    lang: str | None = Field(default=None, max_length=8)


class ScannerRunBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    universe: str | None = Field(default=None, max_length=64)
    phases: str | list[str] | None = Field(default=None)
    intent: str | None = Field(default=None, max_length=200)
    symbols: list[str] | None = Field(default=None, max_length=500)


class InstantBackfillBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    days: int = Field(default=14, ge=1, le=365)
    symbols: list[str] | None = Field(default=None, max_length=500)


class BestSymbolBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    candidates: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    profile: dict[str, Any] | None = None


class WatchlistBody(BaseModel):
    """Validated body for PUT /api/watchlists/{name}."""

    model_config = ConfigDict(extra="ignore")

    symbols: list[str] = Field(default_factory=list, max_length=200)


__all__ = [
    "AskBody",
    "BestSymbolBody",
    "FunctionIndexEntry",
    "InstantBackfillBody",
    "OrderRequest",
    "ScannerRunBody",
    "VeryfinderBatchRequest",
    "WatchlistBody",
    "XAnalyzeBody",
    "XClassifyBody",
]
