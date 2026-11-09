"""Polymarket adapter — public CLOB markets snapshot.

DATA PIPELINE:
    Source: https://gamma-api.polymarket.com/markets (public, anahtarsız)
    Latency: <1s
"""

from __future__ import annotations

from typing import Any
from datetime import datetime, timezone

import httpx

from showme.engine.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest,
)


class PolymarketAdapter(BaseDataSource):
    name = "polymarket"
    supported_kinds = (DataKind.OTHER, DataKind.EVENTS)
    rate_limit_rps = 2.0
    requires_api_key = False

    BASE = "https://gamma-api.polymarket.com"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.BASE, timeout=15)
        return self._client

    async def search(self, query: str | None = None, *,
                     active: bool | None = True, closed: bool | None = False,
                     limit: int = 30, tag_id: int | None = None,
                     min_liquidity: float = 0) -> list[dict[str, Any]]:
        client = await self._client_()
        return await fetch_markets(client, query, limit=limit, active=active,
                                   closed=closed, tag_id=tag_id,
                                   min_liquidity=min_liquidity)

    async def market(self, slug: str) -> dict[str, Any]:
        client = await self._client_()
        r = await client.get(f"/markets/slug/{slug}")
        r.raise_for_status()
        return r.json() or {}

    async def fetch(self, request: DataRequest) -> Any:
        q = (request.extra or {}).get("query") or (
            request.symbols[0] if request.symbols else None
        )
        return await self.search(q, limit=request.limit or 30)


PUBLIC_SEARCH_URL = "https://gamma-api.polymarket.com/public-search"


async def search_markets_by_topic(client: httpx.AsyncClient, query: str, *,
                                  target: int = 100, active: bool | None = None,
                                  closed: bool | None = None) -> list[dict[str, Any]]:
    """Topic search through Polymarket's public-search endpoint.

    Gamma's ``/markets`` endpoint ignores its ``search`` parameter (every topic
    returns the same top-volume markets), so topic queries go to
    ``/public-search``, which ranks events by relevance. Each event's nested
    markets are flattened and de-duplicated.

    public-search does not apply Gamma's ``active``/``closed`` flags, so they
    are enforced here: ``active=True`` drops markets reporting ``active=false``,
    and a boolean ``closed`` keeps only markets with that closed state. ``None``
    applies no filter for that flag. The caller still applies the liquidity
    and end-date filters, as it does for the browse path.
    """
    r = await client.get(PUBLIC_SEARCH_URL, params={
        "q": query.strip(),
        "limit_per_type": min(max(target, 10), 100),
    })
    r.raise_for_status()
    payload = r.json() or {}
    events = payload.get("events") if isinstance(payload, dict) else payload
    if not isinstance(events, list):
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in events:
        if not isinstance(event, dict):
            continue
        for market in event.get("markets") or []:
            if not isinstance(market, dict):
                continue
            if active and market.get("active") is False:
                continue
            if closed is not None and market.get("closed") is not None and bool(market.get("closed")) != closed:
                continue
            key = str(market.get("id") or market.get("slug") or market.get("question"))
            if key in seen:
                continue
            seen.add(key)
            row = dict(market)
            if not row.get("endDate"):
                row["endDate"] = event.get("endDate")
            rows.append(row)
    return rows[:target]


async def fetch_markets(client: httpx.AsyncClient, query: str | None = None, *,
                        active: bool | None = True, closed: bool | None = False,
                        limit: int = 100, tag_id: int | None = None,
                        min_liquidity: float = 0) -> list[dict[str, Any]]:
    """Filter before the provider limit, and page through its 100-row windows.

    ``closed=None`` sends no ``closed`` flag at all (status=all); Gamma treats
    any explicit ``closed`` value as a hard filter. A non-empty ``query`` is a
    topic search and goes to ``/public-search`` (see search_markets_by_topic).
    """
    target = min(max(limit, 1), 400)
    if query and str(query).strip():
        return await search_markets_by_topic(client, str(query), target=target,
                                             active=active, closed=closed)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    offset = 0
    for _ in range(4):
        params: dict[str, Any] = {"limit": min(100, target - len(rows)),
                                 "offset": offset, "order": "volume24hr",
                                 "ascending": "false", "archived": "false",
                                 "liquidity_num_min": max(0, min_liquidity)}
        if closed is not None:
            params["closed"] = str(closed).lower()
        if active:
            params["active"] = "true"
        if active and not closed:
            params["end_date_min"] = datetime.now(timezone.utc).isoformat()
        if tag_id:
            params["tag_id"] = tag_id
        r = await client.get("https://gamma-api.polymarket.com/markets", params=params)
        r.raise_for_status()
        page = r.json() or []
        if isinstance(page, dict):
            page = page.get("data") or page.get("markets") or []
        if not isinstance(page, list) or not page:
            break
        offset += len(page)
        added = 0
        for row in page:
            if not isinstance(row, dict):
                continue
            key = str(row.get("id") or row.get("slug") or row.get("question"))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
            added += 1
        if len(rows) >= target or not added:
            break
    return rows[:target]
