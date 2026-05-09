"""TAUC — US Treasury Auction Calendar."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


@FunctionRegistry.register
class TAUCFunction(BaseFunction):
    code = "TAUC"
    name = "Treasury Auction Calendar"
    asset_classes = (AssetClass.BOND,)
    category = "bond"
    description = "Upcoming + recent Treasury auctions (Bills/Notes/Bonds/TIPS/FRN)."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        action = (params.get("action") or "upcoming").lower()
        horizon = int(params.get("horizon_days", 30))
        security_filter = str(params.get("security_type") or params.get("type") or "").strip().lower()
        limit = params.get("limit")
        limit = int(limit) if limit else None
        if not _truthy(params.get("live_auctions") or params.get("live")):
            items = _filter_security_type(_template_auctions(action, limit), security_filter)
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=_auction_payload(action, horizon, items, "treasury_auction_model", security_filter),
                sources=["treasury_auction_model"],
                metadata={"live": False},
            )
        if not self.deps.treasury_auctions:
            items = _filter_security_type(_template_auctions(action, limit), security_filter)
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=_auction_payload(action, horizon, items, "treasury_auction_model", security_filter),
                sources=["treasury_auction_model"],
                warnings=["no treasury_auctions adapter"],
            )
        timeout = float(params.get("auction_timeout", params.get("timeout", 6)))
        try:
            if action == "recent":
                items = await asyncio.wait_for(
                    self.deps.treasury_auctions.recent(days=horizon, limit=limit),
                    timeout=timeout,
                )
            else:
                items = await asyncio.wait_for(
                    self.deps.treasury_auctions.upcoming(horizon_days=horizon, limit=limit),
                    timeout=timeout,
                )
        except Exception as exc:
            items = _filter_security_type(_template_auctions(action, limit), security_filter)
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=_auction_payload(action, horizon, items, "treasury_auction_fallback", security_filter),
                sources=["treasury_auction_fallback"],
                metadata={
                    "live": False,
                    "provider_errors": [f"treasurydirect: {type(exc).__name__}: {exc}"],
                },
            )
        items = _filter_security_type(items, security_filter)
        return FunctionResult(
            code=self.code, instrument=None,
            data=_auction_payload(action, horizon, items, "treasurydirect", security_filter),
            sources=["treasurydirect"],
        )


def _auction_payload(action: str, horizon: int, items: list[dict[str, Any]], source_mode: str, security_filter: str = "") -> dict[str, Any]:
    tag = "recent" if action == "recent" else "upcoming"
    by_type: dict[str, dict[str, Any]] = {}
    for it in items:
        t = it.get("security_type") or "Unknown"
        slot = by_type.setdefault(t, {"security_type": t, "count": 0, "total_offering": 0.0})
        slot["count"] += 1
        try:
            amt = float(it.get("offering_amount") or 0)
        except Exception:
            amt = 0.0
        slot["total_offering"] += amt
    return {
        "rows": items,
        tag: items,
        "n": len(items),
        "by_type": list(by_type.values()),
        "horizon_days": horizon,
        "summary": {"action": tag, "horizon_days": horizon, "auctions": len(items), "source_mode": source_mode, "security_filter": security_filter or "all"},
        "methodology": "TAUC lists Treasury auction rows with actual calendar-style dates. Live TreasuryDirect rows are used when available; fallback rows use current-date-relative dates and are labelled by source_mode rather than template placeholders.",
        "field_dictionary": {
            "security_type": "Bill, Note, Bond, TIPS, or FRN.",
            "term": "Auction security term.",
            "auction_date": "Calendar auction date.",
            "offering_amount": "Offering amount in USD.",
        },
    }


def _template_auctions(action: str, limit: int | None) -> list[dict[str, Any]]:
    today = datetime.now(timezone.utc).date()
    sign = -1 if action == "recent" else 1
    rows = [
        {"security_type": "Bill", "term": "13-Week", "auction_date": (today + timedelta(days=sign * 3)).isoformat(), "offering_amount": 70_000_000_000},
        {"security_type": "Bill", "term": "26-Week", "auction_date": (today + timedelta(days=sign * 4)).isoformat(), "offering_amount": 75_000_000_000},
        {"security_type": "Note", "term": "2-Year", "auction_date": (today + timedelta(days=sign * 7)).isoformat(), "offering_amount": 69_000_000_000},
        {"security_type": "Note", "term": "5-Year", "auction_date": (today + timedelta(days=sign * 8)).isoformat(), "offering_amount": 70_000_000_000},
        {"security_type": "Bond", "term": "30-Year", "auction_date": (today + timedelta(days=sign * 15)).isoformat(), "offering_amount": 25_000_000_000},
    ]
    return rows[:limit] if limit else rows


def _filter_security_type(rows: list[dict[str, Any]], security_filter: str) -> list[dict[str, Any]]:
    if not security_filter:
        return rows
    return [row for row in rows if security_filter in str(row.get("security_type", "")).lower() or security_filter in str(row.get("term", "")).lower()]


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
