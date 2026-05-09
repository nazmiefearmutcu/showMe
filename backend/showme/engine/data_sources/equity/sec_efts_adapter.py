"""SEC EDGAR full-text search (EFTS) adapter.

DATA PIPELINE:
    Source: https://efts.sec.gov/LATEST/search-index?q=...&dateRange=custom&...
    Free public; SEC asks for User-Agent.

Returns hits with accession + filing date + form type + cik + ticker.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from showme.engine.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest, DataSourceError
)


class SECFullTextSearch(BaseDataSource):
    name = "sec_efts"
    supported_kinds = (DataKind.EVENTS, DataKind.OTHER)
    rate_limit_rps = 8.0
    requires_api_key = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        ua = os.environ.get("SEC_EDGAR_USER_AGENT", "ShowMe dev showme@example.com")
        self.headers = {"User-Agent": ua, "Accept": "application/json"}
        self.base_url = (config or {}).get(
            "base_url", "https://efts.sec.gov/LATEST/search-index"
        )
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=20, headers=self.headers, follow_redirects=True,
            )
        return self._client

    async def search(self, query: str, *,
                     forms: list[str] | None = None,
                     start: str | None = None, end: str | None = None,
                     ciks: list[str] | None = None,
                     limit: int = 50) -> list[dict[str, Any]]:
        client = await self._client_()
        params: dict[str, Any] = {"q": query, "from": 0, "size": min(limit, 100)}
        if forms:
            params["forms"] = ",".join(forms)
        if start and end:
            params["dateRange"] = "custom"
            params["startdt"] = start
            params["enddt"] = end
        if ciks:
            params["ciks"] = ",".join(c.zfill(10) for c in ciks)
        try:
            r = await client.get(self.base_url, params=params)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise DataSourceError(f"SEC EFTS: {e}")
        hits = ((r.json() or {}).get("hits") or {}).get("hits") or []
        out: list[dict[str, Any]] = []
        for h in hits:
            src = h.get("_source") or {}
            adsh = (h.get("_id") or "").split(":")[0]
            out.append({
                "accession": adsh,
                "form": src.get("forms", [None])[0] if isinstance(src.get("forms"), list) else src.get("form"),
                "filing_date": src.get("file_date") or src.get("filing_date"),
                "company": src.get("display_names", [None])[0] if isinstance(src.get("display_names"), list) else None,
                "cik": (src.get("ciks") or [None])[0] if isinstance(src.get("ciks"), list) else None,
                "ticker": (src.get("tickers") or [None])[0] if isinstance(src.get("tickers"), list) else None,
                "score": h.get("_score"),
                "snippet": (h.get("_source") or {}).get("inc_states") or "",
            })
        return out

    async def fetch(self, request: DataRequest) -> Any:
        q = (request.extra or {}).get("query") or (
            request.symbols[0] if request.symbols else None
        )
        if not q:
            raise DataSourceError("EFTS requires query")
        forms = (request.extra or {}).get("forms")
        return await self.search(q, forms=forms,
                                  start=(request.extra or {}).get("start"),
                                  end=(request.extra or {}).get("end"),
                                  limit=request.limit or 50)
