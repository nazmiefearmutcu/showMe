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

# Statement periods accepted by ``standard_fundamentals``.
_SEC_PERIODS = frozenset({"annual", "quarterly"})
# A line item whose latest period ends this many days before the newest line
# item in the same payload is treated as discontinued, not as current.
_SEC_STALE_DAYS = {"annual": 400, "quarterly": 200}
_SEC_ANNUAL_FORMS = frozenset({"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"})
_SEC_QUARTER_FORMS = frozenset({"10-Q", "10-Q/A"})
_SEC_QUARTER_FPS = frozenset({"Q1", "Q2", "Q3"})
# XBRL tags that name the same ShowMe line item under a different tag
# (companies moved from DepreciationAndAmortization to the depletion variant).
_SEC_CANONICAL_OVERRIDES = {
    "DepreciationAndAmortization": "depreciationAndAmortization",
    "DepreciationDepletionAndAmortization": "depreciationAndAmortization",
}


def _sec_days_between(start: Any, end: Any) -> int | None:
    from datetime import date

    try:
        return (date.fromisoformat(str(end)) - date.fromisoformat(str(start))).days
    except ValueError:
        return None


def _sec_fact_in_period(fact: dict[str, Any], period: str) -> bool:
    """True when an XBRL companyfacts row belongs to the requested statement period.

    Instant facts (balance sheet; no ``start``) are judged by form and fiscal
    period only. Flow facts (``start`` present) must also span the right length.
    """
    end = fact.get("end")
    if not end:
        return False
    form = str(fact.get("form") or "").upper()
    fp = str(fact.get("fp") or "").upper()
    start = fact.get("start")
    days = None if start is None else _sec_days_between(start, end)
    if start is not None and days is None:
        return False
    if period == "annual":
        if form not in _SEC_ANNUAL_FORMS or fp != "FY":
            return False
        return days is None or 350 <= days <= 380
    # quarterly
    if days is None:
        return (form in _SEC_QUARTER_FORMS and fp in _SEC_QUARTER_FPS) or (
            form in _SEC_ANNUAL_FORMS and fp == "FY"
        )
    return form in _SEC_QUARTER_FORMS and fp in _SEC_QUARTER_FPS and 80 <= days <= 100


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

    async def standard_fundamentals(
        self, ticker: str, period: str | None = None
    ) -> dict[str, pd.Series]:
        """Return canonical ShowMe fundamentals dict by canonical key.

        ``period=None`` (the default, used by the FUNDAMENTALS fetch path and
        other non-FA callers) keeps the legacy behaviour: the first XBRL tag per
        canonical key, built from every USD fact.

        ``period`` selects which XBRL facts are kept (FA passes it explicitly):
          * ``annual``    — 10-K/20-F fiscal-year (``fp == FY``) facts; flow
                            items must span ~12 months (a 10-K also carries
                            ~3-month quarterly rows).
          * ``quarterly`` — 10-Q Q1-Q3 facts; flow items must span ~3 months
                            (YTD 6/9-month facts are excluded). Balance-sheet
                            instants also take the FY year-end from the 10-K.

        Each canonical key is built from ONE XBRL tag: the tag whose latest
        matching period end is most recent (not the first tag met). Keys whose
        latest period is far older than the newest key are dropped rather than
        shown as current values. Each series carries
        ``attrs["filed_by_end"]`` (period end -> SEC ``filed`` date) so callers
        can report the real filing date.
        """
        if period is not None and period not in _SEC_PERIODS:
            raise DataSourceError(
                f"unsupported period {period!r}; expected one of {sorted(_SEC_PERIODS)}"
            )
        cik = await self.cik_for(ticker)
        if not cik:
            raise DataSourceError(f"No CIK for {ticker}")
        facts = await self.company_facts(cik)
        from showme.engine.core.accounting_taxonomy import to_canonical
        us_gaap = (facts.get("facts") or {}).get("us-gaap") or {}

        if period is None:
            # Legacy shared path: first XBRL tag per canonical key, every USD fact.
            legacy: dict[str, pd.Series] = {}
            for tag, payload in us_gaap.items():
                key = to_canonical(tag)
                if key in legacy:
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
                legacy[key] = df["val"]
            return legacy

        # canonical key -> [(tag, {period_end: (filed, value)})]
        candidates: dict[str, list[tuple[str, dict[str, tuple[str, float]]]]] = {}
        for tag, payload in us_gaap.items():
            key = _SEC_CANONICAL_OVERRIDES.get(tag) or to_canonical(tag)
            units = (payload or {}).get("units") or {}
            usd = units.get("USD") or units.get("USD/shares") or []
            by_end: dict[str, tuple[str, float]] = {}
            for fact in usd:
                if not _sec_fact_in_period(fact, period):
                    continue
                try:
                    value = float(fact["val"])
                except (KeyError, TypeError, ValueError):
                    continue
                end = str(fact["end"])
                filed = str(fact.get("filed") or "")
                prior = by_end.get(end)
                # Restatements / comparatives: the latest filing for a date wins.
                if prior is None or filed >= prior[0]:
                    by_end[end] = (filed, value)
            if by_end:
                candidates.setdefault(key, []).append((tag, by_end))

        canon: dict[str, pd.Series] = {}
        for key, options in candidates.items():
            _tag, by_end = max(options, key=lambda item: (max(item[1]), len(item[1])))
            ends = sorted(by_end)
            series = pd.Series(
                [by_end[e][1] for e in ends],
                index=pd.to_datetime(ends),
                dtype=float,
            )
            series.attrs["filed_by_end"] = {e: by_end[e][0] for e in ends}
            canon[key] = series

        if canon:
            newest = max(series.index.max() for series in canon.values())
            tolerance = pd.Timedelta(days=_SEC_STALE_DAYS[period])
            canon = {
                key: series
                for key, series in canon.items()
                if newest - series.index.max() <= tolerance
            }
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
