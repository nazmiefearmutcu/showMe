"""SPLC — Supply Chain (10-K text-mining stub).

Plan §7.7: no good free relationship feed exists; this is approximate
10-K text mining. This version fetches the latest 10-K from SEC EDGAR
and mines customer/supplier concentration language plus the debt-maturity
section; reference rows are clearly labelled when extraction finds
nothing.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity._common import frame_rows, reference_profile


@FunctionRegistry.register
class SPLCFunction(BaseFunction):
    code = "SPLC"
    name = "Supply Chain (approximate)"
    asset_classes = (AssetClass.EQUITY,)
    category = "equity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        warnings: list[str] = []
        filings = pd.DataFrame()
        customers: list[dict[str, Any]] = []
        suppliers: list[dict[str, Any]] = []
        debt_section: str | None = None
        filing_url: str | None = None
        try:
            if self.deps.sec_edgar:
                req_timeout = float(params.get("timeout", params.get("sec_timeout", 8.0)))
                sec_timeout = max(1.0, min(req_timeout - 1.0, 4.0))
                df = await asyncio.wait_for(
                    self.deps.sec_edgar.fetch(DataRequest(
                        kind=DataKind.EVENTS, instrument=instrument
                    )),
                    timeout=sec_timeout,
                )
                if isinstance(df, pd.DataFrame) and "form" in df.columns:
                    filings = df[df["form"] == "10-K"].head(3)
                    if not filings.empty:
                        latest = filings.iloc[0]
                        cik = await asyncio.wait_for(
                            self.deps.sec_edgar.cik_for(instrument.symbol),
                            timeout=sec_timeout,
                        )
                        acc = (latest.get("accessionNumber") or "").replace("-", "")
                        doc = latest.get("primaryDocument")
                        if cik and acc and doc:
                            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}"
                            filing_url = url
                            try:
                                import httpx
                                async with httpx.AsyncClient(
                                    timeout=sec_timeout,
                                    headers={"User-Agent": "ShowMe dev showme@example.com"},
                                    follow_redirects=True,
                                ) as cli:
                                    r = await cli.get(url)
                                    if r.status_code == 200:
                                        import re as _re
                                        text = _re.sub(r"<[^>]+>", " ", r.text)
                                        from showme.engine.core.sec_taxonomy import (
                                            TENK_CUSTOMER_PATTERNS,
                                            TENK_DEBT_MATURITY_PATTERNS,
                                            TENK_SUPPLIER_PATTERNS,
                                            extract_customer_concentration,
                                            find_section_window,
                                        )
                                        cust_section = find_section_window(text, TENK_CUSTOMER_PATTERNS)
                                        sup_section = find_section_window(text, TENK_SUPPLIER_PATTERNS)
                                        debt_section = find_section_window(text, TENK_DEBT_MATURITY_PATTERNS, window=2000)
                                        if cust_section:
                                            customers = extract_customer_concentration(cust_section)
                                        if sup_section:
                                            suppliers = extract_customer_concentration(sup_section)
                            except Exception as e:
                                warnings.append(f"10-K fetch: {e}")
        except Exception as e:
            warnings.append(f"sec_edgar: {e}")
        data: dict[str, Any] = {
            "status": "ok" if customers or suppliers else "reference_relationships",
            "filings": filings,
            "customers": customers,
            "suppliers": suppliers,
            "debt_maturity_section": (debt_section or "")[:1000],
        }
        reference_peers = [
            str(p) for p in (reference_profile(instrument.symbol).get("peers") or [])
        ]
        data["rows"] = _relationship_rows(
            instrument.symbol, customers, suppliers, filings,
            peers=reference_peers, filing_url=filing_url,
        )
        sources = ["sec_edgar"]
        if not customers and not suppliers:
            ref = reference_profile(instrument.symbol)
            ref_rows = [
                {"symbol": instrument.symbol, "source_url": None, **item, "disclosed_pct": None, "source_mode": "reference_supply_chain_10k_language"}
                for item in [*ref.get("customers", []), *ref.get("suppliers", [])]
            ]
            comp_rows = [
                {"symbol": instrument.symbol, "relationship": "competitor", "counterparty": str(p).strip().upper(), "ticker": str(p).strip().upper(), "confidence": 0.35, "disclosed_pct": None, "source_url": None, "source_mode": "reference_sector_peer_list"}
                for p in (ref.get("peers") or [])
            ]
            if ref_rows or comp_rows:
                data["rows"] = [*ref_rows, *comp_rows]
                data["customers"] = [r for r in ref_rows if "customer" in str(r.get("relationship", ""))]
                data["suppliers"] = [r for r in ref_rows if "supplier" in str(r.get("relationship", ""))]
                sources = ["sec_edgar", "supply_chain_reference"]
        if (not isinstance(filings, pd.DataFrame) or filings.empty) and not data.get("rows"):
            data = {
                "status": "provider_unavailable",
                "rows": [{
                    "symbol": instrument.symbol,
                    "relationship": "provider_unavailable",
                    "counterparty": None,
                    "confidence": None,
                    "source_mode": "supply_chain_unavailable",
                }],
                "filings": [{
                    "symbol": instrument.symbol,
                    "form": "10-K",
                    "status": "provider_unavailable",
                }],
                "customers": [],
                "suppliers": [],
                "debt_maturity_section": "",
            }
            sources = ["supply_chain_model"]
        if data.get("status") != "provider_unavailable":
            relationship = _relationship_param(params.get("relationship"))
            min_pct, pct_warning = _min_pct_param(params.get("min_pct"))
            if pct_warning:
                warnings.append(pct_warning)
            data["rows"] = _apply_filters(data.get("rows") or [], relationship, min_pct)
            data["customers"] = _apply_filters(data.get("customers") or [], "customer", min_pct)
            data["suppliers"] = _apply_filters(data.get("suppliers") or [], "supplier", min_pct)
            if relationship != "both" or min_pct > 0:
                data["filters_applied"] = {"relationship": relationship, "min_pct": min_pct}
        data["methodology"] = "SPLC approximates supply-chain relationships by scanning recent 10-K sections for customer/supplier concentration language. Reference rows are labelled when extraction finds no explicit counterparty rows. Rows with a disclosed share below min_pct, or without one when min_pct is set, are dropped."
        data["field_dictionary"] = {
            "relationship": "customer, supplier, competitor, filing-evidence, or unavailable state.",
            "counterparty": "Named or summarized relationship counterparty.",
            "confidence": "Extraction confidence; lower values indicate approximate/reference rows.",
            "disclosed_pct": "Share of revenue or inputs stated in the 10-K, in percent (22.0 = 22%); null when not disclosed.",
            "source_url": "EDGAR URL of the 10-K the row was extracted from; null for reference rows.",
            "source_mode": "SEC extraction or labelled reference fallback.",
        }
        return FunctionResult(
            code=self.code, instrument=instrument,
            data=data,
            sources=sources,
            metadata={
                "note": "Regex-based extraction; spaCy NER refinement next iter.",
                "provider_errors": warnings,
            },
        )


_RELATIONSHIP_CHOICES = ("both", "customer", "supplier")


def _relationship_param(value: Any) -> str:
    """Normalise the relationship input; unknown values fall back to ``both``."""
    text = str(value or "both").strip().lower()
    return text if text in _RELATIONSHIP_CHOICES else "both"


def _min_pct_param(value: Any) -> tuple[float, str | None]:
    """Parse min_pct. Returns (threshold, warning). Invalid input is disclosed."""
    if value is None or str(value).strip() == "":
        return 0.0, None
    try:
        threshold = float(value)
    except (TypeError, ValueError):
        return 0.0, f"min_pct {value!r} is not a number; no share threshold applied."
    if threshold != threshold or threshold < 0:
        return 0.0, f"min_pct {value!r} is out of range; no share threshold applied."
    return threshold, None


def _classify(relationship: Any) -> str:
    text = str(relationship or "").lower()
    if "customer" in text:
        return "customer"
    if "supplier" in text:
        return "supplier"
    return "other"


def _apply_filters(
    rows: list[dict[str, Any]], relationship: str, min_pct: float
) -> list[dict[str, Any]]:
    """Apply the relationship and min_pct inputs server-side.

    Unavailable-state rows always pass through so the outage stays visible.
    A row with no disclosed share cannot prove it meets ``min_pct``, so it is
    dropped whenever a threshold above zero is requested.
    """
    kept: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("relationship") or "") == "provider_unavailable":
            kept.append(row)
            continue
        if relationship != "both" and _classify(row.get("relationship")) != relationship:
            continue
        if min_pct > 0:
            pct = row.get("disclosed_pct")
            if pct is None or float(pct) < min_pct:
                continue
        kept.append(row)
    return kept


def _relationship_rows(
    symbol: str,
    customers: list[dict[str, Any]],
    suppliers: list[dict[str, Any]],
    filings: pd.DataFrame,
    peers: list[str] | None = None,
    filing_url: str | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for item in customers:
        rows.append({"symbol": symbol, "relationship": "customer", "counterparty": item.get("name") or item.get("counterparty") or item.get("text"), "confidence": item.get("confidence", 0.55), "disclosed_pct": item.get("pct"), "source_url": filing_url, "source_mode": "sec_10k_customer_extraction"})
    for item in suppliers:
        rows.append({"symbol": symbol, "relationship": "supplier", "counterparty": item.get("name") or item.get("counterparty") or item.get("text"), "confidence": item.get("confidence", 0.55), "disclosed_pct": item.get("pct"), "source_url": filing_url, "source_mode": "sec_10k_supplier_extraction"})
    # Competitor rows come from the labelled reference sector peer list (ticker
    # when the peer entry is a ticker); 10-K concentration mining does not
    # extract competitors, so these rows stay explicitly reference-sourced.
    for peer in peers or []:
        ticker = str(peer).strip().upper()
        rows.append({"symbol": symbol, "relationship": "competitor", "counterparty": ticker, "ticker": ticker, "confidence": 0.35, "disclosed_pct": None, "source_url": None, "source_mode": "reference_sector_peer_list"})
    if not rows:
        for item in frame_rows(filings, limit=3):
            rows.append({"symbol": symbol, "relationship": "evidence_filing", "counterparty": item.get("form"), "filingDate": item.get("filingDate"), "confidence": 0.2, "disclosed_pct": None, "source_url": filing_url, "source_mode": "sec_10k_filing_evidence"})
    return rows
