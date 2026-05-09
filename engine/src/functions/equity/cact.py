"""CACT — Corporate Actions (8-K, splits, M&A, name change)."""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument
from src.functions.equity._common import FIELD_DICTIONARIES, date_label, finite, frame_rows, series_rows


@FunctionRegistry.register
class CACTFunction(BaseFunction):
    code = "CACT"
    name = "Corporate Actions"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF)
    category = "equity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        warnings: list[str] = []
        sec_filings = None
        events_8k: list[dict[str, Any]] = []
        try:
            if self.deps.sec_edgar:
                sec_timeout = max(1.0, min(float(params.get("sec_timeout", 3)), 5.0))
                sec_filings = await asyncio.wait_for(
                    self.deps.sec_edgar.fetch(DataRequest(
                        kind=DataKind.EVENTS, instrument=instrument
                    )),
                    timeout=sec_timeout,
                )
                # Categorize last N 8-K filings by Item code
                if hasattr(sec_filings, "to_dict") and "form" in sec_filings.columns:
                    max_documents = int(params.get("max_documents", 3))
                    eight_k_rows = sec_filings[
                        sec_filings["form"].astype(str).str.startswith("8-K")
                    ].head(max_documents)
                    for _, row in eight_k_rows.iterrows():
                        events_8k.append({
                            "category": "8-k",
                            "form": row.get("form"),
                            "filing_date": row.get("filingDate"),
                            "report_date": row.get("reportDate"),
                            "accession": row.get("accessionNumber"),
                            "document": row.get("primaryDocument"),
                        })
                    if params.get("fetch_documents") or params.get("deep"):
                        cik = await asyncio.wait_for(
                            self.deps.sec_edgar.cik_for(instrument.symbol),
                            timeout=sec_timeout,
                        )
                        if cik:
                            from src.core.sec_taxonomy import categorize_8k_text
                            for _, row in eight_k_rows.iterrows():
                                try:
                                    # Best-effort deep mode: fetch primary document text.
                                    doc = row.get("primaryDocument")
                                    acc = (row.get("accessionNumber") or "").replace("-", "")
                                    if not doc or not acc:
                                        continue
                                    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}"
                                    async with __import__("httpx").AsyncClient(
                                        timeout=sec_timeout,
                                        headers={"User-Agent": "ShowMe dev showme@example.com"},
                                    ) as cli:
                                        r = await cli.get(url)
                                        if r.status_code == 200:
                                            text = __import__("re").sub(r"<[^>]+>", " ", r.text)
                                            for cat in categorize_8k_text(text)[:5]:
                                                cat["filing_date"] = row.get("filingDate")
                                                events_8k.append(cat)
                                except Exception:
                                    continue
        except Exception as e:
            warnings.append(f"sec_edgar: {e}")
        yfin = {}
        try:
            if self.deps.yfinance:
                yfin = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.EVENTS, instrument=instrument
                    )),
                    timeout=max(1.0, min(float(params.get("yfinance_timeout", 3)), 5.0)),
                )
        except Exception as e:
            # Corporate actions still has SEC filings when Yahoo events are slow
            # or throttled; keep the pane usable instead of timing out.
            yfin = {"status": "unavailable", "reason": str(e) or type(e).__name__}
        rows = _corporate_action_rows(instrument.symbol, sec_filings, events_8k, yfin)
        if not rows:
            rows = [{
                "symbol": instrument.symbol,
                "action_type": "provider_unavailable",
                "event_date": None,
                "value": None,
                "source_mode": "corporate_actions_unavailable",
                "reason": "No dividend, split, or dated 8-K corporate-action rows were returned.",
            }]
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "status": "ok" if rows and rows[0].get("action_type") != "provider_unavailable" else "provider_unavailable",
                "rows": rows,
                "timeline": rows,
                "sec_filings": sec_filings if sec_filings is not None else [],
                "events_8k": events_8k or [{
                    "category": "corporate_actions",
                    "symbol": instrument.symbol,
                    "status": "provider_unavailable",
                }],
                "yfinance_events": yfin,
                "methodology": "CACT normalizes Yahoo dividends/splits/actions plus recent SEC 8-K filings into corporate-action rows. Event rows expose action type, date, value, source mode, and raw filing/action fields.",
                "field_dictionary": FIELD_DICTIONARIES["corporate_actions"],
            },
            sources=["sec_edgar", "yfinance"] if not warnings else ["corporate_actions_model", "yfinance"],
            metadata={"provider_errors": warnings} if warnings else {},
        )


def _corporate_action_rows(symbol: str, sec_filings: Any, events_8k: list[dict[str, Any]], yfin: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in series_rows((yfin or {}).get("dividends"), value_key="value", limit=40):
        rows.append({
            "symbol": symbol,
            "action_type": "dividend",
            "event_date": row.get("date"),
            "value": row.get("value"),
            "unit": "cash/share",
            "source_mode": "live_yfinance",
        })
    for row in series_rows((yfin or {}).get("splits"), value_key="value", limit=20):
        rows.append({
            "symbol": symbol,
            "action_type": "split",
            "event_date": row.get("date"),
            "value": row.get("value"),
            "unit": "split ratio",
            "source_mode": "live_yfinance",
        })
    for row in frame_rows((yfin or {}).get("actions"), limit=40):
        date = row.get("Date") or row.get("index") or row.get("date")
        div = finite(row.get("Dividends") or row.get("dividends"))
        split = finite(row.get("Stock Splits") or row.get("splits"))
        if div:
            rows.append({"symbol": symbol, "action_type": "dividend", "event_date": date_label(date), "value": div, "source_mode": "live_yfinance_actions"})
        if split:
            rows.append({"symbol": symbol, "action_type": "split", "event_date": date_label(date), "value": split, "source_mode": "live_yfinance_actions"})
    for item in events_8k[:20]:
        rows.append({
            "symbol": symbol,
            "action_type": item.get("category") or "8-k event",
            "event_date": item.get("filing_date") or item.get("report_date"),
            "value": item.get("code") or item.get("form"),
            "source_mode": "sec_edgar_8k",
            "accession": item.get("accession"),
            "document": item.get("document"),
        })
    if not rows and sec_filings is not None:
        for item in frame_rows(sec_filings, limit=10):
            if not str(item.get("form") or "").startswith(("8-K", "10-Q", "10-K")):
                continue
            rows.append({
                "symbol": symbol,
                "action_type": f"filing {item.get('form')}",
                "event_date": item.get("filingDate") or item.get("reportDate"),
                "value": item.get("form"),
                "source_mode": "sec_edgar_filing_metadata",
                "accession": item.get("accessionNumber"),
                "document": item.get("primaryDocument"),
            })
    rows.sort(key=lambda r: str(r.get("event_date") or ""), reverse=True)
    return rows[:80]
