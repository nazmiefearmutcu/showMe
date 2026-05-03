"""SPLC — Supply Chain (10-K text-mining stub).

Plan §7.7: ücretsiz iyi veri yok; 10-K text mining ile yaklaşımsal.
Bu sürüm sadece SEC EDGAR'dan son 10-K'yı çeker, customer/supplier extraction'ı
``agents/code.py`` Phase 7'de bağlanır. Şimdilik filing URL listesi döner.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


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
                df = await asyncio.wait_for(
                    self.deps.sec_edgar.fetch(DataRequest(
                        kind=DataKind.EVENTS, instrument=instrument
                    )),
                    timeout=float(params.get("sec_timeout", 8)),
                )
                if isinstance(df, pd.DataFrame) and "form" in df.columns:
                    filings = df[df["form"] == "10-K"].head(3)
                    if not filings.empty:
                        latest = filings.iloc[0]
                        cik = await asyncio.wait_for(
                            self.deps.sec_edgar.cik_for(instrument.symbol),
                            timeout=float(params.get("sec_timeout", 8)),
                        )
                        acc = (latest.get("accessionNumber") or "").replace("-", "")
                        doc = latest.get("primaryDocument")
                        if cik and acc and doc:
                            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}"
                            try:
                                import httpx
                                async with httpx.AsyncClient(
                                    timeout=20,
                                    headers={"User-Agent": "ShowMe dev showme@example.com"},
                                    follow_redirects=True,
                                ) as cli:
                                    r = await cli.get(url)
                                    if r.status_code == 200:
                                        import re as _re
                                        text = _re.sub(r"<[^>]+>", " ", r.text)
                                        from src.core.sec_taxonomy import (
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
            "filings": filings,
            "customers": customers,
            "suppliers": suppliers,
            "debt_maturity_section": (debt_section or "")[:1000],
        }
        sources = ["sec_edgar"]
        if (not isinstance(filings, pd.DataFrame) or filings.empty) and not customers and not suppliers:
            data = {
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
        return FunctionResult(
            code=self.code, instrument=instrument,
            data=data,
            sources=sources,
            metadata={
                "note": "Regex-based extraction; spaCy NER refinement next iter.",
                "provider_errors": warnings,
            },
        )
