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
    """Validated body for POST /api/broker/orders.

    SEC-09 — A02-2026-05-24: ``confirmation_token`` is REQUIRED for every
    submit. The route compares it server-side against the broker's
    account label (or the broker name for ``paper``) so a stray
    ``curl`` cannot drop an order even with a valid auth token. This
    mirrors the typed-account-label gate the UI's ``OrderTicket.tsx``
    confirmation modal already enforces — it just makes the contract
    binding at the route layer as well (defense in depth).
    """

    model_config = ConfigDict(extra="ignore")

    # Dynamic credential brokers register as
    # ``{exchange_id}:{credential_id}`` (exchange ~16 chars, UUID-style
    # credential id 32 chars). The old ``max_length=32`` rejected every
    # such name with HTTP 422 before the route even ran — silently
    # forcing the caller back to the default ``paper`` broker. Widen to
    # 96 to fit the longest catalog entry id + credential id pair.
    broker: str | None = Field(default=None, max_length=96)
    symbol: str = Field(..., min_length=1, max_length=32)
    side: str = Field(default="buy", max_length=8)
    quantity: float = Field(..., gt=0, le=1e9)
    order_type: str = Field(default="market", max_length=16)
    time_in_force: str = Field(default="day", max_length=8)
    limit_price: float | None = Field(default=None, ge=0, le=1e12)
    stop_price: float | None = Field(default=None, ge=0, le=1e12)
    notes: str = Field(default="", max_length=512)
    leverage: float | None = Field(default=None, ge=0, le=125)
    # Required typed-confirmation. Backwards-compat alias
    # ``confirm_account_label`` accepted so callers that already use the
    # bots-route field name keep working (see bots.py:349/426).
    confirmation_token: str | None = Field(default=None, max_length=64)
    confirm_account_label: str | None = Field(default=None, max_length=64)

    def resolved_confirmation(self) -> str:
        """Return whichever confirmation field the caller supplied
        (``confirmation_token`` wins) with whitespace trimmed.
        Empty string when neither was provided."""
        token = self.confirmation_token or self.confirm_account_label or ""
        return token.strip()


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
    # Legacy: older UI builds (and `ui/src/lib/xai.ts:analyzeXTopic`) send
    # ``{"query": "..."}`` instead of {symbol|topic}. Without this field the
    # ConfigDict(extra="ignore") setting silently swallowed it and every call
    # raised HTTP 400 "query or symbol is required". The handler in
    # ``server_routes/xai.py`` promotes ``query`` → ``symbol``/``topic`` so
    # both old and new clients work. See SHOWME_BUGHUNT 2026-05-24 Bug #10b.
    query: str | None = Field(default=None, max_length=200)
    limit: int | None = Field(default=None, ge=1, le=500)
    since: str | None = Field(default=None, max_length=32)
    until: str | None = Field(default=None, max_length=32)
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
