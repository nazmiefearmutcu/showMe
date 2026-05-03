"""TAUC — US Treasury Auction Calendar."""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


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
        limit = params.get("limit")
        limit = int(limit) if limit else None
        if not _truthy(params.get("live_auctions") or params.get("live")):
            items = _template_auctions(action, limit)
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=_auction_payload(action, horizon, items),
                sources=["treasury_auction_model"],
                metadata={"live": False},
            )
        if not self.deps.treasury_auctions:
            return FunctionResult(code=self.code, instrument=None, data={},
                                  warnings=["no treasury_auctions adapter"])
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
            items = _template_auctions(action, limit)
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=_auction_payload(action, horizon, items),
                sources=["treasury_auction_fallback"],
                metadata={
                    "live": False,
                    "provider_errors": [f"treasurydirect: {type(exc).__name__}: {exc}"],
                },
            )
        return FunctionResult(
            code=self.code, instrument=None,
            data=_auction_payload(action, horizon, items),
            sources=["treasurydirect"],
        )


def _auction_payload(action: str, horizon: int, items: list[dict[str, Any]]) -> dict[str, Any]:
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
        tag: items,
        "n": len(items),
        "by_type": list(by_type.values()),
        "horizon_days": horizon,
    }


def _template_auctions(action: str, limit: int | None) -> list[dict[str, Any]]:
    rows = [
        {"security_type": "Bill", "term": "13-Week", "auction_date": "template+3d", "offering_amount": 70_000_000_000},
        {"security_type": "Bill", "term": "26-Week", "auction_date": "template+3d", "offering_amount": 75_000_000_000},
        {"security_type": "Note", "term": "2-Year", "auction_date": "template+7d", "offering_amount": 69_000_000_000},
        {"security_type": "Note", "term": "5-Year", "auction_date": "template+8d", "offering_amount": 70_000_000_000},
        {"security_type": "Bond", "term": "30-Year", "auction_date": "template+15d", "offering_amount": 25_000_000_000},
    ]
    if action == "recent":
        rows = [{**row, "auction_date": row["auction_date"].replace("+", "-")} for row in rows]
    return rows[:limit] if limit else rows


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
