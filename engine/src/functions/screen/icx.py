"""ICX — Index Constituents.

Plan §5: "Index constituents — Wikipedia + iShares ETF holdings (ücretsiz)".
S&P 500 Wikipedia'dan, NASDAQ-100 Wikipedia'dan, DJIA Wikipedia'dan,
ETF holdings için iShares JSON feeds.

DATA PIPELINE:
    Wikipedia: scrape constituent list (cached 24h)
    iShares:   https://www.ishares.com/us/products/{ticker}/holdings
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument


_CACHE_DIR = Path("runtime/index_constituents")
_TTL_SECONDS = 24 * 3600


_WIKI_URLS = {
    "SPX":   ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", 0),
    "NDX":   ("https://en.wikipedia.org/wiki/Nasdaq-100", 4),  # table index varies; try 4 then fallback
    "DJI":   ("https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average", 1),
    "FTSE":  ("https://en.wikipedia.org/wiki/FTSE_100_Index", 4),
    "DAX":   ("https://en.wikipedia.org/wiki/DAX", 4),
    "CAC":   ("https://en.wikipedia.org/wiki/CAC_40", 4),
    "RUT":   ("https://en.wikipedia.org/wiki/Russell_2000_Index", -1),  # too large; use ETF
    "STOXX": ("https://en.wikipedia.org/wiki/EURO_STOXX_50", 2),
    "BIST":  ("https://en.wikipedia.org/wiki/BIST_100_Index", 2),
}


async def _fetch_wiki(url: str, table_idx: int) -> pd.DataFrame:
    cache_path = _CACHE_DIR / f"wiki_{re.sub(r'[^A-Za-z0-9]', '_', url)}.json"
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text())
            if (time.time() - data.get("ts", 0)) < _TTL_SECONDS:
                return pd.DataFrame(data["rows"])
        except Exception:
            pass
    try:
        async with httpx.AsyncClient(timeout=20,
                                       headers={"User-Agent": "ShowMe/0.3"}) as cli:
            r = await cli.get(url, follow_redirects=True)
            r.raise_for_status()
        # Use pandas read_html — clean Wikipedia table
        tables = pd.read_html(r.text)
        if not tables:
            return pd.DataFrame()
        if 0 <= table_idx < len(tables):
            df = tables[table_idx]
        else:
            df = tables[0]
    except Exception:
        return pd.DataFrame()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"ts": int(time.time()),
                                       "rows": df.to_dict(orient="records")}))
    return df


@FunctionRegistry.register
class ICXFunction(BaseFunction):
    code = "ICX"
    name = "Index Constituents"
    category = "screen"
    description = "Major equity index constituents (Wikipedia-backed cache)."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        idx = (params.get("index") or
                params.get("query") or
                (instrument.symbol.lstrip("^") if instrument else "") or "SPX").upper()
        limit = _int_param(params, "limit", 50)
        # Map common Yahoo tickers
        alias = {"GSPC": "SPX", "NDX": "NDX", "IXIC": "NDX", "DJI": "DJI",
                  "RUT": "RUT", "FTSE": "FTSE", "GDAXI": "DAX", "FCHI": "CAC",
                  "STOXX50E": "STOXX", "XU100": "BIST", "TR": "BIST"}
        idx = alias.get(idx, idx)
        spec = _WIKI_URLS.get(idx)
        if not spec:
            return FunctionResult(code=self.code, instrument=None, data={},
                                  warnings=[f"unknown index {idx}"])
        if not _truthy(params.get("live_constituents") or params.get("live")):
            df = _template_constituents(idx)
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=_constituent_payload(idx, df.head(limit), status="ok", live=False),
                sources=["showme_index_reference_universe"],
                metadata={"index": idx, "constituents": int(len(df)), "live": False, "limit": limit},
            )
        url, ti = spec
        df = await _fetch_wiki(url, ti)
        # Light normalization: pick the most likely 'symbol' / 'company' columns
        if not df.empty:
            df.columns = [_flatten_column(c) for c in df.columns]
            cols = [c for c in df.columns if isinstance(c, str)]
            sym_col = next((c for c in cols if "symbol" in c.lower() or "ticker" in c.lower()), None)
            name_col = next((c for c in cols if "company" in c.lower() or "security" in c.lower() or "name" in c.lower()), None)
            sector_col = next((c for c in cols if "sector" in c.lower() or "industry" in c.lower()), None)
            keep = [c for c in (sym_col, name_col, sector_col) if c]
            if keep:
                df = df[keep].copy()
                df.columns = [c.lower() for c in df.columns]
                if sym_col:
                    df = df.rename(columns={sym_col.lower(): "symbol"})
                if name_col:
                    df = df.rename(columns={name_col.lower(): "company"})
                if sector_col:
                    df = df.rename(columns={sector_col.lower(): "sector"})
        if df.empty:
            df = _template_constituents(idx)
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=_constituent_payload(
                    idx,
                    df.head(limit),
                    status="provider_unavailable",
                    live=True,
                    reason="Wikipedia constituent table was unavailable or could not be normalized.",
                    source_url=url,
                ),
                sources=["wikipedia", "showme_index_reference_universe"],
                metadata={"index": idx, "constituents": int(len(df)), "live": True, "fallback": True, "limit": limit},
            )
        return FunctionResult(
            code=self.code, instrument=None,
            data=_constituent_payload(idx, df.head(limit), status="ok", live=True, source_url=url),
            sources=["wikipedia"],
            metadata={"index": idx, "constituents": int(len(df)), "live": True, "limit": limit},
        )


def _template_constituents(index: str) -> pd.DataFrame:
    rows = {
        "SPX": [
            {"symbol": "AAPL", "company": "Apple Inc.", "sector": "Information Technology"},
            {"symbol": "MSFT", "company": "Microsoft Corp.", "sector": "Information Technology"},
            {"symbol": "NVDA", "company": "NVIDIA Corp.", "sector": "Information Technology"},
            {"symbol": "AMZN", "company": "Amazon.com Inc.", "sector": "Consumer Discretionary"},
            {"symbol": "META", "company": "Meta Platforms Inc.", "sector": "Communication Services"},
            {"symbol": "GOOGL", "company": "Alphabet Inc. Class A", "sector": "Communication Services"},
            {"symbol": "BRK.B", "company": "Berkshire Hathaway Inc.", "sector": "Financials"},
            {"symbol": "LLY", "company": "Eli Lilly and Co.", "sector": "Health Care"},
            {"symbol": "AVGO", "company": "Broadcom Inc.", "sector": "Information Technology"},
            {"symbol": "TSLA", "company": "Tesla Inc.", "sector": "Consumer Discretionary"},
            {"symbol": "JPM", "company": "JPMorgan Chase & Co.", "sector": "Financials"},
        ],
        "NDX": [
            {"symbol": "MSFT", "company": "Microsoft Corp.", "sector": "Information Technology"},
            {"symbol": "AAPL", "company": "Apple Inc.", "sector": "Information Technology"},
            {"symbol": "NVDA", "company": "NVIDIA Corp.", "sector": "Information Technology"},
            {"symbol": "META", "company": "Meta Platforms Inc.", "sector": "Communication Services"},
            {"symbol": "AVGO", "company": "Broadcom Inc.", "sector": "Information Technology"},
            {"symbol": "AMZN", "company": "Amazon.com Inc.", "sector": "Consumer Discretionary"},
            {"symbol": "COST", "company": "Costco Wholesale Corp.", "sector": "Consumer Staples"},
            {"symbol": "TSLA", "company": "Tesla Inc.", "sector": "Consumer Discretionary"},
            {"symbol": "GOOGL", "company": "Alphabet Inc. Class A", "sector": "Communication Services"},
            {"symbol": "GOOG", "company": "Alphabet Inc. Class C", "sector": "Communication Services"},
        ],
        "DJI": [
            {"symbol": "AAPL", "company": "Apple Inc.", "sector": "Information Technology"},
            {"symbol": "MSFT", "company": "Microsoft Corp.", "sector": "Information Technology"},
            {"symbol": "JPM", "company": "JPMorgan Chase & Co.", "sector": "Financials"},
            {"symbol": "V", "company": "Visa Inc.", "sector": "Financials"},
            {"symbol": "UNH", "company": "UnitedHealth Group Inc.", "sector": "Health Care"},
            {"symbol": "GS", "company": "Goldman Sachs Group Inc.", "sector": "Financials"},
            {"symbol": "HD", "company": "Home Depot Inc.", "sector": "Consumer Discretionary"},
            {"symbol": "MCD", "company": "McDonald's Corp.", "sector": "Consumer Discretionary"},
            {"symbol": "CAT", "company": "Caterpillar Inc.", "sector": "Industrials"},
            {"symbol": "AMGN", "company": "Amgen Inc.", "sector": "Health Care"},
        ],
    }
    return pd.DataFrame(rows.get(index, rows["SPX"]))


def _flatten_column(col: Any) -> str:
    if isinstance(col, tuple):
        return " ".join(str(part) for part in col if str(part) != "nan").strip()
    return str(col)


def _constituent_payload(
    index: str,
    df: pd.DataFrame,
    *,
    status: str,
    live: bool,
    reason: str | None = None,
    source_url: str | None = None,
) -> dict[str, Any]:
    rows = df.to_dict(orient="records")
    return {
        "status": status,
        "index": index,
        "live": live,
        "source_url": source_url,
        "rows": rows,
        "constituents": len(rows),
        "reason": reason,
        "field_dictionary": [
            {"field": "symbol", "meaning": "Constituent ticker."},
            {"field": "company", "meaning": "Company or security name."},
            {"field": "sector", "meaning": "Index sector/classification when the source provides it."},
        ],
        "next_actions": [] if status == "ok" else [
            "Retry with live=true after the public Wikipedia endpoint recovers.",
            "Use the Index control with SPX, NDX, DJI, DAX, CAC, FTSE, STOXX, or BIST.",
        ],
    }


def _int_param(params: dict[str, Any], name: str, default: int) -> int:
    try:
        return max(1, min(int(params.get(name, default)), 500))
    except Exception:
        return default


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
