"""SPLC — Supply Chain (10-K text-mining stub).

Plan §7.7: ücretsiz iyi veri yok; 10-K text mining ile yaklaşımsal.
Bu sürüm sadece SEC EDGAR'dan son 10-K'yı çeker, customer/supplier extraction'ı
``agents/code.py`` Phase 7'de bağlanır. Şimdilik filing URL listesi döner.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity._common import reference_profile, frame_rows


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
                                            TENK_CUSTOMER_PATTERNS, TENK_SUPPLIER_PATTERNS,
                                            TENK_DEBT_MATURITY_PATTERNS,
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
        data["rows"] = _relationship_rows(instrument.symbol, customers, suppliers, filings)
        sources = ["sec_edgar"]
        if not customers and not suppliers:
            ref = reference_profile(instrument.symbol)
            ref_rows = [
                {"symbol": instrument.symbol, **item, "source_mode": "reference_supply_chain_10k_language"}
                for item in [*ref.get("customers", []), *ref.get("suppliers", [])]
            ]
            if ref_rows:
                data["rows"] = ref_rows
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
        data["methodology"] = "SPLC approximates supply-chain relationships by scanning recent 10-K sections for customer/supplier concentration language. Reference rows are labelled when extraction finds no explicit counterparty rows."
        data["field_dictionary"] = {
            "relationship": "customer, supplier, partner, or unavailable state.",
            "counterparty": "Named or summarized relationship counterparty.",
            "confidence": "Extraction confidence; lower values indicate approximate/reference rows.",
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


def _relationship_rows(symbol: str, customers: list[dict[str, Any]], suppliers: list[dict[str, Any]], filings: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for item in customers:
        rows.append({"symbol": symbol, "relationship": "customer", "counterparty": item.get("name") or item.get("counterparty") or item.get("text"), "confidence": item.get("confidence", 0.55), "source_mode": "sec_10k_customer_extraction"})
    for item in suppliers:
        rows.append({"symbol": symbol, "relationship": "supplier", "counterparty": item.get("name") or item.get("counterparty") or item.get("text"), "confidence": item.get("confidence", 0.55), "source_mode": "sec_10k_supplier_extraction"})
    if not rows:
        for item in frame_rows(filings, limit=3):
            rows.append({"symbol": symbol, "relationship": "evidence_filing", "counterparty": item.get("form"), "filingDate": item.get("filingDate"), "confidence": 0.2, "source_mode": "sec_10k_filing_evidence"})
    return rows
