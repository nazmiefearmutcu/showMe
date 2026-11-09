"""SEC EDGAR full-text search (EFTS) adapter.

DATA PIPELINE:
    Source: https://efts.sec.gov/LATEST/search-index?q=...&dateRange=custom&...
    Free public; SEC asks for User-Agent.

Returns hits with accession + filing date + form type + cik + ticker.
"""

from __future__ import annotations

import os
import re
from datetime import date
from typing import Any

import httpx

from showme.engine.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest, DataSourceError
)


_TICKER_IN_NAME = re.compile(r"\(([A-Z][A-Z0-9.\-]{0,9})\)")
_EFTS_FLOOR_DATE = "2001-01-01"


def _ticker_from_display_names(names: Any) -> str | None:
    """EFTS carries no ``tickers`` field; the issuer ticker sits in display_names
    as ``"NAME  (TICK)  (CIK 0000000000)"``. CIK parentheses contain a space so
    they do not match."""
    if not isinstance(names, list):
        return None
    for name in names:
        m = _TICKER_IN_NAME.search(str(name or ""))
        if m:
            return m.group(1)
    return None


class EftsHits(list):
    """Hit list that also carries the EFTS-reported total (``hits.total.value``).

    ``total`` is None when the provider response did not report one.
    ``total_relation`` is the EFTS ``hits.total.relation`` (``"eq"`` means the
    total is exact, ``"gte"`` means it is a lower bound). A bare-int total is
    treated as ``"eq"``, as in older responses; None when not reported.
    """

    total: int | None = None
    total_relation: str | None = None


def _filing_index_url(cik: Any, accession: str | None) -> str | None:
    """EDGAR filing index URL built from the filer CIK and accession number.

    Pattern: ``/Archives/edgar/data/<CIK without zeros>/<accession without
    dashes>/<accession>-index.htm`` (verified against live EFTS hits). Returns
    None when either part is missing, so no link is invented.
    """
    cik_digits = re.sub(r"\D", "", str(cik or ""))
    if not cik_digits or not accession or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
        return None
    return (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik_digits)}/"
        f"{accession.replace('-', '')}/{accession}-index.htm"
    )


def _total_hits(raw: Any) -> int | None:
    """EFTS reports ``hits.total`` as ``{"value": n, "relation": "eq"}`` (or a bare int in old responses)."""
    if isinstance(raw, dict):
        raw = raw.get("value")
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    return None


def _total_relation(raw: Any) -> str | None:
    """``hits.total.relation`` as reported (lower-cased). A bare int is exact (``"eq"``)."""
    if isinstance(raw, dict):
        rel = raw.get("relation")
        return rel.strip().lower() if isinstance(rel, str) and rel.strip() else None
    if isinstance(raw, int) and not isinstance(raw, bool):
        return "eq"
    return None


def _matched_text(source: dict[str, Any], highlight: Any) -> str | None:
    """Matched filing text only. ``inc_states`` is an incorporation state and is
    never filing text, so it is not used as a snippet."""
    if not isinstance(highlight, dict):
        return None
    parts: list[str] = []
    for values in highlight.values():
        for v in values if isinstance(values, list) else [values]:
            if isinstance(v, str) and v.strip():
                parts.append(v.strip())
    return " | ".join(parts[:2]) if parts else None


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
        if start or end:
            # EDGAR full-text search covers filings from 2001 onward; an open
            # side is bounded by that floor or by today, never by a guessed date.
            params["dateRange"] = "custom"
            params["startdt"] = start or _EFTS_FLOOR_DATE
            params["enddt"] = end or date.today().isoformat()
        if ciks:
            params["ciks"] = ",".join(c.zfill(10) for c in ciks)
        try:
            r = await client.get(self.base_url, params=params)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise DataSourceError(f"SEC EFTS: {str(e) or type(e).__name__}")
        body = r.json() or {}
        hits_block = body.get("hits") or {}
        hits = hits_block.get("hits") or []
        out = EftsHits()
        out.total = _total_hits(hits_block.get("total"))
        out.total_relation = _total_relation(hits_block.get("total"))
        for h in hits:
            src = h.get("_source") or {}
            adsh = (h.get("_id") or "").split(":")[0]
            cik = (src.get("ciks") or [None])[0] if isinstance(src.get("ciks"), list) else None
            out.append({
                "accession": adsh,
                "form": src.get("forms", [None])[0] if isinstance(src.get("forms"), list) else src.get("form"),
                "filing_date": src.get("file_date") or src.get("filing_date"),
                "company": src.get("display_names", [None])[0] if isinstance(src.get("display_names"), list) else None,
                "cik": cik,
                "ticker": ((src.get("tickers") or [None])[0] if isinstance(src.get("tickers"), list) else None)
                          or _ticker_from_display_names(src.get("display_names")),
                "url": _filing_index_url(cik, adsh),
                "score": h.get("_score"),
                "snippet": _matched_text(src, h.get("highlight")),
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
