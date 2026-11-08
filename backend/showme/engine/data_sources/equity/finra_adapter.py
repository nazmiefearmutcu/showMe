"""FINRA OTC Transparency adapter (Dark Pool / ATS volumes).

DATA PIPELINE:
    Source: https://api.finra.org/data/group/otcMarket
    Free, T+1 reporting; ATS_W_SMBL (per-symbol weekly ATS aggregate) and ATS_NMS files.
    Auth: optional OAuth client credentials via FINRA_API_KEY/SECRET.

QUERY SEMANTICS (verified against the live weeklySummary endpoint):
    * Rows come back OLDEST-FIRST and a bare ``limit`` returns the oldest rows
      of the symbol's history, not the newest. Every pull therefore carries a
      ``dateRangeFilters`` window on ``weekStartDate`` ending today.
    * ``sortFields`` is rejected (HTTP 400) unless the partition keys
      (``weekStartDate`` and ``tierIdentifier``) are pinned with EQUAL filters,
      so the newest weeks are selected by window, not by sort.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pandas as pd

from showme.engine.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest, DataSourceError
)

# FINRA OTC Transparency updates weekly. Cache successful pulls briefly so
# several panes (DARK/DPF) hitting the same symbol in a minute do not each
# send an anonymous POST; a failed pull backs off for a minute so a degraded
# endpoint is not hammered at the adapter's 1 rps budget.
_CACHE_TTL_S = 900.0
_FAILURE_COOLDOWN_S = 60.0

FINRA_WEEKLY_URL = "https://api.finra.org/data/group/otcMarket/name/weeklySummary"
ATS_WEEKLY_TYPE = "ATS_W_SMBL"
# Page size requested from FINRA; a short page means the window is exhausted.
ATS_PAGE_LIMIT = 5000
# FINRA publishes with a lag of a few weeks; the window keeps this many extra
# days beyond the requested weeks so the newest published weeks always fall
# inside it.
_PUBLICATION_SLACK_DAYS = 42
_MAX_PAGES = 4


def ats_window_days(weeks: int) -> int:
    """Length of the lookback window that holds ``weeks`` published weeks."""
    return max(1, int(weeks)) * 7 + _PUBLICATION_SLACK_DAYS


def ats_weekly_body(symbol: str | None, *, weeks: int, today: Any,
                    offset: int = 0) -> dict[str, Any]:
    """Build the POST body for one page of the ATS weekly summary."""
    start = today - timedelta(days=ats_window_days(weeks))
    compare: list[dict[str, Any]] = [
        {"fieldName": "summaryTypeCode", "fieldValue": ATS_WEEKLY_TYPE, "compareType": "EQUAL"},
    ]
    if symbol:
        compare.append({"fieldName": "issueSymbolIdentifier",
                        "fieldValue": symbol.upper(), "compareType": "EQUAL"})
    body: dict[str, Any] = {
        "compareFilters": compare,
        "dateRangeFilters": [{
            "fieldName": "weekStartDate",
            "startDate": start.isoformat(),
            "endDate": today.isoformat(),
        }],
        "limit": ATS_PAGE_LIMIT,
    }
    if offset:
        body["offset"] = int(offset)
    return body


def newest_weeks(rows: list[dict[str, Any]], weeks: int) -> list[dict[str, Any]]:
    """Keep every row of the ``weeks`` most recent weeks (never a partial week)."""
    dated = [r for r in rows if r.get("weekStartDate")]
    keep = set(sorted({str(r["weekStartDate"])[:10] for r in dated}, reverse=True)[: max(1, int(weeks))])
    return [r for r in dated if str(r["weekStartDate"])[:10] in keep]


async def fetch_ats_weekly_pages(client: Any, symbol: str | None, *, weeks: int,
                                 headers: dict[str, str] | None = None,
                                 timeout: float = 8.0,
                                 today: Any = None) -> list[dict[str, Any]]:
    """Fetch every raw ATS row inside the window, following offset paging.

    Raises when the window does not fit the paging budget so a caller never
    sums an incomplete set of weeks.
    """
    day = today or datetime.now(timezone.utc).date()
    rows: list[dict[str, Any]] = []
    offset = 0
    for _ in range(_MAX_PAGES):
        resp = await client.post(
            FINRA_WEEKLY_URL,
            json=ats_weekly_body(symbol, weeks=weeks, today=day, offset=offset),
            headers=headers or {"Accept": "application/json"},
            timeout=timeout,
        )
        if resp.status_code == 401:
            raise DataSourceError("FINRA auth required for this dataset")
        resp.raise_for_status()
        body = resp.json()
        if isinstance(body, list):
            page = body
        elif isinstance(body, dict):
            page = body.get("data") or body.get("rows") or []
        else:
            page = []
        rows.extend(r for r in page if isinstance(r, dict))
        if len(page) < ATS_PAGE_LIMIT:
            return rows
        offset += len(page)
    raise DataSourceError(
        f"finra: ATS window for {symbol or '*'} exceeds {_MAX_PAGES} pages; refusing a partial read"
    )


class FINRAAdapter(BaseDataSource):
    name = "finra"
    supported_kinds = (DataKind.TRADES, DataKind.OTHER)
    rate_limit_rps = 1.0
    requires_api_key = False  # public dataset works without auth (rate-limited)

    BASE = "https://api.finra.org/data/group/otcMarket"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.api_key = os.environ.get("FINRA_API_KEY", "")
        self.api_secret = os.environ.get("FINRA_API_SECRET", "")
        self._token: str | None = None
        self._client: httpx.AsyncClient | None = None
        self._cache: dict[tuple[str, int], tuple[float, pd.DataFrame]] = {}
        self._cooldown_until: float = 0.0

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=20)
        return self._client

    async def _maybe_auth(self) -> None:
        if not self.api_key or not self.api_secret:
            return
        if self._token:
            return
        try:
            client = await self._client_()
            r = await client.post(
                "https://ews.fip.finra.org/fip/rest/ews/oauth2/access_token",
                data={"grant_type": "client_credentials"},
                auth=(self.api_key, self.api_secret),
            )
            if r.status_code == 200:
                self._token = (r.json() or {}).get("access_token")
        except Exception:
            self._token = None

    async def ats_weekly(self, symbol: str | None = None,
                         limit: int = 26) -> pd.DataFrame:
        """The newest ``limit`` published weeks of FINRA ATS (Alternative Trading System) volume.

        ``limit`` is a count of WEEKS, not rows: every row of each returned week
        is kept so a week's ATS volume is never summed from a partial set.
        The request is bounded to a lookback window ending today (see
        ``ats_weekly_body``) because the endpoint returns the oldest history
        first when unbounded.

        Columns follow the FINRA record: weekStartDate, summaryTypeCode,
        issueSymbolIdentifier, tierIdentifier, totalWeeklyShareQuantity,
        totalWeeklyTradeCount, ...
        """
        await self._maybe_auth()
        # TTL cache + failure backoff (L9): a repeated pull for the same
        # symbol inside the TTL is served from memory (copy-out so callers
        # cannot mutate the cached frame); after a failed pull the adapter
        # refuses to retry until the cooldown expires instead of hammering
        # the anonymous endpoint.
        weeks = max(1, int(limit))
        cache_key = (symbol.upper() if symbol else "*", weeks)
        now = time.monotonic()
        cached = self._cache.get(cache_key)
        if cached is not None and (now - cached[0]) < _CACHE_TTL_S:
            return cached[1].copy()
        if now < self._cooldown_until:
            remaining = self._cooldown_until - now
            raise DataSourceError(
                f"finra: cooling down after a failed pull ({remaining:.0f}s left)"
            )
        client = await self._client_()
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            raw = await fetch_ats_weekly_pages(
                client, symbol.upper() if symbol else None,
                weeks=weeks, headers=headers,
            )
        except DataSourceError:
            raise
        except httpx.HTTPError as e:
            self._cooldown_until = time.monotonic() + _FAILURE_COOLDOWN_S
            raise DataSourceError(f"finra: {e}")
        frame = pd.DataFrame(newest_weeks(raw, weeks))
        self._cache[cache_key] = (time.monotonic(), frame)
        self._cooldown_until = 0.0
        return frame.copy()

    async def fetch(self, request: DataRequest) -> Any:
        sym = (request.instrument.symbol if request.instrument else None) or (
            request.symbols[0] if request.symbols else None
        )
        return await self.ats_weekly(sym, limit=request.limit or 26)
