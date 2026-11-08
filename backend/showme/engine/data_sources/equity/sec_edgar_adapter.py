"""SEC EDGAR — XBRL fundamentals, 13F holdings, 8-K filings.

DATA PIPELINE:
    Source: https://data.sec.gov (XBRL company facts, submissions),
            https://www.sec.gov/cgi-bin/browse-edgar (filing index)
    Cache:  L1 in-memory (24h), DuckDB ``fundamentals`` (Faz 2 sonu)
    Latency: <1s warm; CIK lookup adds 200ms cold.

Required: SEC asks for ``User-Agent: name email`` header.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pandas as pd

from showme.engine.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest, DataSourceError
)
from showme.engine.utils.throttle import throttle


_TICKER_TO_CIK_URL = "https://www.sec.gov/files/company_tickers.json"


class SECEdgarAdapter(BaseDataSource):
    name = "sec_edgar"
    supported_kinds = (
        DataKind.FUNDAMENTALS, DataKind.REFDATA, DataKind.EVENTS, DataKind.HOLDINGS
    )
    rate_limit_rps = 8.0
    requires_api_key = False  # but UA is required

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        ua = os.environ.get("SEC_EDGAR_USER_AGENT", "ShowMe dev showme@example.com")
        self.base_url = (config or {}).get("base_url", "https://data.sec.gov")
        self._headers = {
            "User-Agent": ua,
            "Accept": "application/json",
        }
        self._client: httpx.AsyncClient | None = None
        self._ticker_to_cik: dict[str, str] | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers=self._headers, timeout=self.timeout_seconds,
                follow_redirects=True,
            )
        return self._client

    async def _load_cik_table(self) -> dict[str, str]:
        if self._ticker_to_cik is not None:
            return self._ticker_to_cik
        data = await self._get_json(_TICKER_TO_CIK_URL)
        # values look like {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
        out: dict[str, str] = {}
        for v in data.values():
            out[v["ticker"].upper()] = str(v["cik_str"]).zfill(10)
        self._ticker_to_cik = out
        return out

    @throttle(rps=8.0)
    async def _get_json(self, url: str) -> dict[str, Any]:
        """Single shared throttle point for every EDGAR GET.

        Per-method ``@throttle`` decorators keep independent budgets, so
        concurrent submissions + company_facts calls could push ~32 rps
        against SEC's 10 rps fair-use limit. Funneling every request
        through this one helper caps the adapter at 8 rps total."""
        client = await self._client_()
        r = await client.get(url)
        r.raise_for_status()
        return r.json()

    async def cik_for(self, ticker: str) -> str | None:
        table = await self._load_cik_table()
        return table.get(ticker.upper())

    async def submissions(self, cik: str) -> dict[str, Any]:
        return await self._get_json(f"{self.base_url}/submissions/CIK{cik}.json")

    async def company_facts(self, cik: str) -> dict[str, Any]:
        return await self._get_json(f"{self.base_url}/api/xbrl/companyfacts/CIK{cik}.json")

    async def company_concept(
        self, cik: str, taxonomy: str, concept: str
    ) -> dict[str, Any]:
        return await self._get_json(
            f"{self.base_url}/api/xbrl/companyconcept/CIK{cik}/{taxonomy}/{concept}.json"
        )

    async def recent_filings(
        self, cik: str, *, form: str | None = None, limit: int = 40
    ) -> list[dict[str, Any]]:
        """Return the recent EDGAR filings list (filtered by form if given)."""
        sub = await self.submissions(cik)
        recent = (sub.get("filings") or {}).get("recent") or {}
        accs = recent.get("accessionNumber") or []

        def nth(key: str, i: int) -> Any:
            # Parallel arrays can be ragged on truncated payloads; the old
            # `or [None]` guard only covered a missing key, not a short list.
            lst = recent.get(key) or []
            return lst[i] if i < len(lst) else None

        out: list[dict[str, Any]] = []
        for i in range(len(accs)):
            row = {
                "accession": accs[i],
                "filingDate": nth("filingDate", i),
                "reportDate": nth("reportDate", i),
                "form": nth("form", i),
                "primaryDocument": nth("primaryDocument", i),
                "primaryDocDescription": nth("primaryDocDescription", i),
                "size": nth("size", i),
                "isXBRL": nth("isXBRL", i),
            }
            if form and (row["form"] or "").upper() != form.upper():
                continue
            out.append(row)
            if len(out) >= limit:
                break
        return out

    async def form4_filings(self, ticker: str, *, limit: int = 40) -> list[dict[str, Any]]:
        cik = await self.cik_for(ticker)
        if not cik:
            return []
        rows = await self.recent_filings(cik, form="4", limit=limit)
        # Construct viewer URLs. FORM4#5: Archives documents and the browse-edgar
        # index are served from www.sec.gov; data.sec.gov only serves the JSON APIs
        # (the old base_url-based URLs returned 404).
        web_base = "https://www.sec.gov"
        for r in rows:
            acc_no = (r.get("accession") or "").replace("-", "")
            r["url"] = (
                f"{web_base}/cgi-bin/browse-edgar?action=getcompany&"
                f"CIK={cik}&type=4&dateb=&owner=include&count=40"
            ) if not acc_no else (
                f"{web_base}/Archives/edgar/data/{int(cik)}/{acc_no}/"
                f"{r.get('primaryDocument') or ''}"
            )
        return rows

    async def standard_fundamentals(self, ticker: str) -> dict[str, pd.Series]:
        """Return canonical ShowMe fundamentals dict by canonical key."""
        cik = await self.cik_for(ticker)
        if not cik:
            raise DataSourceError(f"No CIK for {ticker}")
        facts = await self.company_facts(cik)
        from showme.engine.core.accounting_taxonomy import to_canonical
        canon: dict[str, pd.Series] = {}
        us_gaap = (facts.get("facts") or {}).get("us-gaap") or {}
        for tag, payload in us_gaap.items():
            key = to_canonical(tag)
            if key in canon:
                continue
            units = payload.get("units") or {}
            usd = units.get("USD") or units.get("USD/shares") or []
            if not usd:
                continue
            df = pd.DataFrame(usd)
            if df.empty:
                continue
            df["end"] = pd.to_datetime(df["end"])
            df = df.set_index("end").sort_index()
            canon[key] = df["val"]
        return canon

    async def fetch(self, request: DataRequest) -> Any:
        ticker = (request.instrument.symbol if request.instrument else None) or (
            request.symbols[0] if request.symbols else None
        )
        if not ticker:
            raise DataSourceError("SEC EDGAR requires a ticker")
        cik = await self.cik_for(ticker)
        if not cik:
            raise DataSourceError(f"No CIK for {ticker}")
        if request.kind == DataKind.FUNDAMENTALS:
            return await self.standard_fundamentals(ticker)
        if request.kind == DataKind.REFDATA:
            sub = await self.submissions(cik)
            from showme.engine.core.refdata import ReferenceData
            from showme.engine.core.quote import utcnow
            return ReferenceData(
                symbol=ticker,
                name=sub.get("name"),
                exchange=sub.get("exchanges", [None])[0] if sub.get("exchanges") else None,
                sector=sub.get("sicDescription"),
                cik=cik,
                country=sub.get("addresses", {}).get("business", {}).get("country"),
                source=self.name,
                fetched_at=utcnow(),
            )
        if request.kind == DataKind.EVENTS:
            sub = await self.submissions(cik)
            recent = (sub.get("filings", {}) or {}).get("recent", {}) or {}
            return pd.DataFrame(recent)
        if request.kind == DataKind.HOLDINGS:
            return {"note": "13F holdings — implement via /cgi-bin/browse-edgar in Phase 2"}
        raise DataSourceError(f"unsupported kind {request.kind}")
