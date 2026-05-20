"""TreasuryDirect.gov auctions feed.

Public JSON endpoint:
  https://www.treasurydirect.gov/TA_WS/securities/announced
  https://www.treasurydirect.gov/TA_WS/securities/auctioned

Returns upcoming and past auctions across Bills/Notes/Bonds/TIPS/FRN.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from showme.engine.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest,
)


class TreasuryAuctionsAdapter(BaseDataSource):
    """Public no-key adapter for US Treasury auctions."""

    name = "treasury_auctions"
    rate_limit_rps = 4.0
    supported_kinds = (DataKind.EVENTS,)

    BASE = "https://www.treasurydirect.gov/TA_WS/securities"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config or {})

    async def fetch(self, request: DataRequest) -> list[dict[str, Any]]:
        kind = (request.extra.get("kind") if request.extra else None) or "announced"
        url = f"{self.BASE}/{kind}"
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url, headers={"accept": "application/json"})
            r.raise_for_status()
            data = r.json()
        return [{
            "auction_date": d.get("auctionDate"),
            "issue_date": d.get("issueDate"),
            "maturity_date": d.get("maturityDate"),
            "security_type": d.get("securityType") or d.get("securityTermDayMonth"),
            "security_term": d.get("securityTerm"),
            "term": d.get("term"),
            "offering_amount": d.get("offeringAmount"),
            "high_yield": d.get("highYield"),
            "high_investment_rate": d.get("highInvestmentRate"),
            "high_discount_rate": d.get("highDiscountRate"),
            "high_price": d.get("highPrice"),
            "competitive_accepted": d.get("competitiveAccepted"),
            "non_competitive_accepted": d.get("nonCompetitiveAccepted"),
            "bid_to_cover": d.get("bidToCoverRatio"),
            "cusip": d.get("cusip"),
            "reopening": d.get("reopening"),
        } for d in (data or [])]

    async def upcoming(self, *, horizon_days: int = 30,
                        limit: int | None = None) -> list[dict[str, Any]]:
        cutoff = (datetime.now(timezone.utc) + timedelta(days=horizon_days)).date()
        today = datetime.now(timezone.utc).date()
        items_raw = await self.fetch(DataRequest(
            kind=DataKind.EVENTS, instrument=None,
            extra={"kind": "announced"}))
        items = []
        for d in items_raw:
            ad = d.get("auction_date")
            if not ad:
                continue
            try:
                date_obj = datetime.fromisoformat(str(ad)[:10]).date()
            except Exception:
                continue
            if today <= date_obj <= cutoff:
                items.append(d)
        items.sort(key=lambda x: x.get("auction_date") or "")
        return items if limit is None else items[:limit]

    async def recent(self, *, days: int = 30, limit: int | None = None) -> list[dict[str, Any]]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date()
        today = datetime.now(timezone.utc).date()
        items_raw = await self.fetch(DataRequest(
            kind=DataKind.EVENTS, instrument=None,
            extra={"kind": "auctioned"}))
        items = []
        for d in items_raw:
            ad = d.get("auction_date")
            if not ad:
                continue
            try:
                date_obj = datetime.fromisoformat(str(ad)[:10]).date()
            except Exception:
                continue
            if cutoff <= date_obj <= today:
                items.append(d)
        items.sort(key=lambda x: x.get("auction_date") or "", reverse=True)
        return items if limit is None else items[:limit]
