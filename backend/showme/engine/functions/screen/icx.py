"""ICX — Industry / sector constituents explorer.

Bloomberg ``ICX<GO>`` analogue. Expands a GICS sector into its member
companies from a bundled S&P large-cap classification table (genuine reference
data — the same legitimacy class as SECT's SPDR ETF map) and attaches a
best-effort live quote snapshot (last price + day change) per name from the
keyless quote service (yfinance / public fallbacks).

Constituents are real, curated GICS memberships; prices are best-effort and
degrade to ``None`` (never fabricated) when the quote provider is unreachable.
The bundled universe is a hand-curated US large-cap set — not a complete index
— so the methodology says so. No HTML scraping.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from showme.engine.core.base_function import (
    BaseFunction,
    FunctionRegistry,
    FunctionResult,
)
from showme.engine.core.instrument import Instrument


# ── Bundled GICS sector → constituents (curated S&P large caps) ──────────────
# Each entry: (symbol, company, GICS sub-industry). This is real, static
# reference data — the canonical sector membership for these large caps — not a
# live scrape and not a placeholder. Mirrors how SECT ships its SPDR ETF map.
_SECTOR_CONSTITUENTS: dict[str, list[tuple[str, str, str]]] = {
    "Information Technology": [
        ("AAPL", "Apple Inc.", "Technology Hardware, Storage & Peripherals"),
        ("MSFT", "Microsoft Corporation", "Systems Software"),
        ("NVDA", "NVIDIA Corporation", "Semiconductors"),
        ("AVGO", "Broadcom Inc.", "Semiconductors"),
        ("ORCL", "Oracle Corporation", "Application Software"),
        ("CRM", "Salesforce, Inc.", "Application Software"),
        ("AMD", "Advanced Micro Devices, Inc.", "Semiconductors"),
        ("ADBE", "Adobe Inc.", "Application Software"),
        ("CSCO", "Cisco Systems, Inc.", "Communications Equipment"),
        ("ACN", "Accenture plc", "IT Consulting & Other Services"),
    ],
    "Health Care": [
        ("LLY", "Eli Lilly and Company", "Pharmaceuticals"),
        ("UNH", "UnitedHealth Group Incorporated", "Managed Health Care"),
        ("JNJ", "Johnson & Johnson", "Pharmaceuticals"),
        ("ABBV", "AbbVie Inc.", "Biotechnology"),
        ("MRK", "Merck & Co., Inc.", "Pharmaceuticals"),
        ("TMO", "Thermo Fisher Scientific Inc.", "Life Sciences Tools & Services"),
        ("ABT", "Abbott Laboratories", "Health Care Equipment"),
        ("PFE", "Pfizer Inc.", "Pharmaceuticals"),
        ("AMGN", "Amgen Inc.", "Biotechnology"),
        ("DHR", "Danaher Corporation", "Life Sciences Tools & Services"),
    ],
    "Financials": [
        ("BRK.B", "Berkshire Hathaway Inc.", "Multi-Sector Holdings"),
        ("JPM", "JPMorgan Chase & Co.", "Diversified Banks"),
        ("V", "Visa Inc.", "Transaction & Payment Processing"),
        ("MA", "Mastercard Incorporated", "Transaction & Payment Processing"),
        ("BAC", "Bank of America Corporation", "Diversified Banks"),
        ("WFC", "Wells Fargo & Company", "Diversified Banks"),
        ("GS", "The Goldman Sachs Group, Inc.", "Investment Banking & Brokerage"),
        ("MS", "Morgan Stanley", "Investment Banking & Brokerage"),
        ("BLK", "BlackRock, Inc.", "Asset Management & Custody Banks"),
        ("AXP", "American Express Company", "Consumer Finance"),
    ],
    "Consumer Discretionary": [
        ("AMZN", "Amazon.com, Inc.", "Broadline Retail"),
        ("TSLA", "Tesla, Inc.", "Automobile Manufacturers"),
        ("HD", "The Home Depot, Inc.", "Home Improvement Retail"),
        ("MCD", "McDonald's Corporation", "Restaurants"),
        ("NKE", "NIKE, Inc.", "Footwear"),
        ("LOW", "Lowe's Companies, Inc.", "Home Improvement Retail"),
        ("SBUX", "Starbucks Corporation", "Restaurants"),
        ("BKNG", "Booking Holdings Inc.", "Hotels, Resorts & Cruise Lines"),
    ],
    "Communication Services": [
        ("META", "Meta Platforms, Inc.", "Interactive Media & Services"),
        ("GOOGL", "Alphabet Inc. (Class A)", "Interactive Media & Services"),
        ("GOOG", "Alphabet Inc. (Class C)", "Interactive Media & Services"),
        ("NFLX", "Netflix, Inc.", "Movies & Entertainment"),
        ("DIS", "The Walt Disney Company", "Movies & Entertainment"),
        ("TMUS", "T-Mobile US, Inc.", "Wireless Telecommunication Services"),
        ("VZ", "Verizon Communications Inc.", "Integrated Telecommunication Services"),
        ("CMCSA", "Comcast Corporation", "Cable & Satellite"),
    ],
    "Consumer Staples": [
        ("WMT", "Walmart Inc.", "Consumer Staples Merchandise Retail"),
        ("COST", "Costco Wholesale Corporation", "Consumer Staples Merchandise Retail"),
        ("PG", "The Procter & Gamble Company", "Household Products"),
        ("KO", "The Coca-Cola Company", "Soft Drinks & Non-alcoholic Beverages"),
        ("PEP", "PepsiCo, Inc.", "Soft Drinks & Non-alcoholic Beverages"),
        ("PM", "Philip Morris International Inc.", "Tobacco"),
        ("MDLZ", "Mondelez International, Inc.", "Packaged Foods & Meats"),
    ],
    "Industrials": [
        ("GE", "GE Aerospace", "Aerospace & Defense"),
        ("CAT", "Caterpillar Inc.", "Construction Machinery & Heavy Transportation Equipment"),
        ("RTX", "RTX Corporation", "Aerospace & Defense"),
        ("HON", "Honeywell International Inc.", "Industrial Conglomerates"),
        ("UNP", "Union Pacific Corporation", "Rail Transportation"),
        ("BA", "The Boeing Company", "Aerospace & Defense"),
        ("DE", "Deere & Company", "Agricultural & Farm Machinery"),
        ("LMT", "Lockheed Martin Corporation", "Aerospace & Defense"),
    ],
    "Energy": [
        ("XOM", "Exxon Mobil Corporation", "Integrated Oil & Gas"),
        ("CVX", "Chevron Corporation", "Integrated Oil & Gas"),
        ("COP", "ConocoPhillips", "Oil & Gas Exploration & Production"),
        ("SLB", "Schlumberger Limited", "Oil & Gas Equipment & Services"),
        ("EOG", "EOG Resources, Inc.", "Oil & Gas Exploration & Production"),
        ("MPC", "Marathon Petroleum Corporation", "Oil & Gas Refining & Marketing"),
    ],
    "Materials": [
        ("LIN", "Linde plc", "Industrial Gases"),
        ("SHW", "The Sherwin-Williams Company", "Specialty Chemicals"),
        ("APD", "Air Products and Chemicals, Inc.", "Industrial Gases"),
        ("ECL", "Ecolab Inc.", "Specialty Chemicals"),
        ("FCX", "Freeport-McMoRan Inc.", "Copper"),
        ("NEM", "Newmont Corporation", "Gold"),
    ],
    "Utilities": [
        ("NEE", "NextEra Energy, Inc.", "Multi-Utilities"),
        ("SO", "The Southern Company", "Electric Utilities"),
        ("DUK", "Duke Energy Corporation", "Electric Utilities"),
        ("CEG", "Constellation Energy Corporation", "Independent Power Producers & Energy Traders"),
        ("AEP", "American Electric Power Company, Inc.", "Electric Utilities"),
    ],
    "Real Estate": [
        ("PLD", "Prologis, Inc.", "Industrial REITs"),
        ("AMT", "American Tower Corporation", "Telecom Tower REITs"),
        ("EQIX", "Equinix, Inc.", "Data Center REITs"),
        ("WELL", "Welltower Inc.", "Health Care REITs"),
        ("SPG", "Simon Property Group, Inc.", "Retail REITs"),
    ],
}

# Accept common aliases so the same input as SECT/EQS resolves here.
_SECTOR_ALIASES: dict[str, str] = {
    "tech": "Information Technology",
    "technology": "Information Technology",
    "it": "Information Technology",
    "information technology": "Information Technology",
    "health": "Health Care",
    "healthcare": "Health Care",
    "health care": "Health Care",
    "financial": "Financials",
    "financials": "Financials",
    "finance": "Financials",
    "consumer discretionary": "Consumer Discretionary",
    "discretionary": "Consumer Discretionary",
    "communication services": "Communication Services",
    "communications": "Communication Services",
    "comm services": "Communication Services",
    "consumer staples": "Consumer Staples",
    "staples": "Consumer Staples",
    "industrials": "Industrials",
    "industrial": "Industrials",
    "energy": "Energy",
    "materials": "Materials",
    "utilities": "Utilities",
    "real estate": "Real Estate",
    "realestate": "Real Estate",
}

_FIELD_DICTIONARY = {
    "symbol": "Ticker symbol of the constituent.",
    "company": "Registered company name.",
    "sub_industry": "GICS sub-industry classification.",
    "sector": "GICS sector the constituent belongs to.",
    "last": "Most recent trade price (best-effort; null when unavailable).",
    "change_pct": "Percentage change on the day (best-effort; null when unavailable).",
}

_METHODOLOGY = (
    "Resolve the requested GICS sector to its member tickers from a bundled "
    "curated classification table (canonical sector membership for these "
    "large caps), then attach a best-effort live quote snapshot (last price "
    "and day change) per name from the keyless quote service (yfinance and "
    "public fallbacks). S&P 500 membership ships as a bundled 503-name "
    "constituent list; the other index tables are curated reference subsets, "
    "not complete indexes. Prices are left null when the quote provider is "
    "unavailable rather than fabricated. No HTML scraping."
)


def _canonical_sector(raw: str) -> str | None:
    key = (raw or "").strip()
    if key in _SECTOR_CONSTITUENTS:
        return key
    return _SECTOR_ALIASES.get(key.lower())


# ── Curated index constituents (real members, region-correct tickers) ───────
# Used when ICX is addressed by an INDEX code (SPX/NDX/DAX/...) rather than a
# GICS sector. These are real, static, hand-curated index memberships — the
# same legitimacy class as the sector table — NOT a Wikipedia scrape and NOT a
# placeholder. Each row carries the region-correct yfinance suffix so a DAX
# query never leaks Apple/Microsoft (the historical SPX-substitution bug).
#
# SPX is special-cased: it resolves from the bundled 503-name constituent
# file (``reference/data/sp500.json``, the same snapshot the EQS pane ships)
# joined with the SECF security master for company names. The 12-name list
# below is only the fallback when that file is unreadable. NDX is a curated
# high-weight subset (29 names), NOT the complete 100 — the methodology text
# says so; DJIA is the full 30-member roster. NDX/DJIA members verified to
# return live Yahoo quotes on 2026-09-15 (batch probe: 29/29 and 30/30).
_INDEX_CONSTITUENTS: dict[str, list[tuple[str, str]]] = {
    "SPX": [
        ("AAPL", "Apple Inc."), ("MSFT", "Microsoft Corporation"),
        ("NVDA", "NVIDIA Corporation"), ("AMZN", "Amazon.com, Inc."),
        ("META", "Meta Platforms, Inc."), ("GOOGL", "Alphabet Inc. (Class A)"),
        ("BRK.B", "Berkshire Hathaway Inc."), ("AVGO", "Broadcom Inc."),
        ("TSLA", "Tesla, Inc."), ("JPM", "JPMorgan Chase & Co."),
        ("LLY", "Eli Lilly and Company"), ("V", "Visa Inc."),
    ],
    "NDX": [
        ("AAPL", "Apple Inc."), ("MSFT", "Microsoft Corporation"),
        ("NVDA", "NVIDIA Corporation"), ("AMZN", "Amazon.com, Inc."),
        ("AVGO", "Broadcom Inc."), ("META", "Meta Platforms, Inc."),
        ("TSLA", "Tesla, Inc."), ("GOOGL", "Alphabet Inc. (Class A)"),
        ("GOOG", "Alphabet Inc. (Class C)"),
        ("COST", "Costco Wholesale Corporation"), ("NFLX", "Netflix, Inc."),
        ("AMD", "Advanced Micro Devices, Inc."), ("PEP", "PepsiCo, Inc."),
        ("ADBE", "Adobe Inc."), ("CSCO", "Cisco Systems, Inc."),
        ("TMUS", "T-Mobile US, Inc."), ("INTU", "Intuit Inc."),
        ("QCOM", "QUALCOMM Incorporated"), ("TXN", "Texas Instruments Incorporated"),
        ("AMAT", "Applied Materials, Inc."),
        ("ISRG", "Intuitive Surgical, Inc."), ("BKNG", "Booking Holdings Inc."),
        ("HON", "Honeywell International Inc."), ("AMGN", "Amgen Inc."),
        ("PANW", "Palo Alto Networks, Inc."),
        ("PLTR", "Palantir Technologies Inc."),
        ("MSTR", "MicroStrategy Incorporated"),
        ("APP", "AppLovin Corporation"), ("AXON", "Axon Enterprise, Inc."),
    ],
    "DJIA": [
        ("AAPL", "Apple Inc."), ("AMGN", "Amgen Inc."),
        ("AMZN", "Amazon.com, Inc."), ("AXP", "American Express Company"),
        ("BA", "The Boeing Company"), ("CAT", "Caterpillar Inc."),
        ("CRM", "Salesforce, Inc."), ("CSCO", "Cisco Systems, Inc."),
        ("CVX", "Chevron Corporation"), ("DIS", "The Walt Disney Company"),
        ("GS", "The Goldman Sachs Group, Inc."), ("HD", "The Home Depot, Inc."),
        ("HON", "Honeywell International Inc."), ("IBM", "International Business Machines Corporation"),
        ("JNJ", "Johnson & Johnson"), ("JPM", "JPMorgan Chase & Co."),
        ("KO", "The Coca-Cola Company"), ("MCD", "McDonald's Corporation"),
        ("MMM", "3M Company"), ("MRK", "Merck & Co., Inc."),
        ("MSFT", "Microsoft Corporation"), ("NKE", "NIKE, Inc."),
        ("NVDA", "NVIDIA Corporation"), ("PG", "The Procter & Gamble Company"),
        ("SHW", "The Sherwin-Williams Company"), ("TRV", "The Travelers Companies, Inc."),
        ("UNH", "UnitedHealth Group Incorporated"), ("V", "Visa Inc."),
        ("VZ", "Verizon Communications Inc."), ("WMT", "Walmart Inc."),
    ],
    "DAX": [
        ("SAP.DE", "SAP SE"), ("SIE.DE", "Siemens AG"),
        ("ALV.DE", "Allianz SE"), ("DTE.DE", "Deutsche Telekom AG"),
        ("AIR.DE", "Airbus SE"), ("MBG.DE", "Mercedes-Benz Group AG"),
        ("BAS.DE", "BASF SE"), ("BMW.DE", "Bayerische Motoren Werke AG"),
        ("MUV2.DE", "Münchener Rück AG"), ("BAYN.DE", "Bayer AG"),
    ],
    "CAC": [
        ("MC.PA", "LVMH Moët Hennessy Louis Vuitton SE"), ("OR.PA", "L'Oréal S.A."),
        ("TTE.PA", "TotalEnergies SE"), ("SAN.PA", "Sanofi S.A."),
        ("AIR.PA", "Airbus SE"), ("SU.PA", "Schneider Electric S.E."),
        ("AI.PA", "Air Liquide S.A."), ("BNP.PA", "BNP Paribas S.A."),
        ("EL.PA", "EssilorLuxottica S.A."), ("CS.PA", "AXA S.A."),
    ],
    "FTSE": [
        ("AZN.L", "AstraZeneca PLC"), ("SHEL.L", "Shell plc"),
        ("HSBA.L", "HSBC Holdings plc"), ("ULVR.L", "Unilever PLC"),
        ("BP.L", "BP p.l.c."), ("RIO.L", "Rio Tinto Group"),
        ("GSK.L", "GSK plc"), ("DGE.L", "Diageo plc"),
        ("GLEN.L", "Glencore plc"), ("BATS.L", "British American Tobacco p.l.c."),
    ],
    "STOXX": [
        ("ASML.AS", "ASML Holding N.V."), ("MC.PA", "LVMH Moët Hennessy Louis Vuitton SE"),
        ("SAP.DE", "SAP SE"), ("TTE.PA", "TotalEnergies SE"),
        ("SIE.DE", "Siemens AG"), ("OR.PA", "L'Oréal S.A."),
        ("SAN.PA", "Sanofi S.A."), ("ALV.DE", "Allianz SE"),
        ("AIR.PA", "Airbus SE"), ("IBE.MC", "Iberdrola, S.A."),
    ],
    "BIST": [
        ("THYAO.IS", "Türk Hava Yolları A.O."), ("ASELS.IS", "Aselsan Elektronik Sanayi A.Ş."),
        ("KCHOL.IS", "Koç Holding A.Ş."), ("GARAN.IS", "Türkiye Garanti Bankası A.Ş."),
        ("AKBNK.IS", "Akbank T.A.Ş."), ("EREGL.IS", "Ereğli Demir ve Çelik Fabrikaları T.A.Ş."),
        ("BIMAS.IS", "BİM Birleşik Mağazalar A.Ş."), ("SISE.IS", "Türkiye Şişe ve Cam Fabrikaları A.Ş."),
        ("TUPRS.IS", "Tüpraş-Türkiye Petrol Rafinerileri A.Ş."), ("FROTO.IS", "Ford Otomotiv Sanayi A.Ş."),
    ],
}

# Common aliases for index codes so the same input as other panes resolves.
_INDEX_ALIASES: dict[str, str] = {
    "SPX": "SPX", "SP500": "SPX", "S&P500": "SPX", "S&P 500": "SPX", "^GSPC": "SPX",
    "GSPC": "SPX", "ES": "SPX",
    "NDX": "NDX", "NASDAQ100": "NDX", "NASDAQ 100": "NDX", "^NDX": "NDX", "NQ": "NDX",
    "DJIA": "DJIA", "DOW": "DJIA", "DOW JONES": "DJIA", "^DJI": "DJIA", "DJI": "DJIA",
    "DAX": "DAX", "^GDAXI": "DAX", "GDAXI": "DAX", "DAX40": "DAX",
    "CAC": "CAC", "CAC40": "CAC", "^FCHI": "CAC", "FCHI": "CAC",
    "FTSE": "FTSE", "FTSE100": "FTSE", "UKX": "FTSE", "^FTSE": "FTSE",
    "STOXX": "STOXX", "STOXX50": "STOXX", "SX5E": "STOXX", "ESTX50": "STOXX", "^STOXX50E": "STOXX",
    "BIST": "BIST", "BIST100": "BIST", "XU100": "BIST", "^XU100": "BIST",
}


def _canonical_index(raw: str) -> str | None:
    key = (raw or "").strip().upper()
    if key in _INDEX_CONSTITUENTS:
        return key
    return _INDEX_ALIASES.get(key)


# ── S&P 500 membership from the bundled constituent file ────────────────────
_SP500_PATH = (
    Path(__file__).resolve().parents[2] / "reference" / "data" / "sp500.json"
)
# Display order head: the largest names lead so the pane opens on recognisable
# tickers (AAPL first — pinned by the Session-08 regression test).
_SP500_HEAD = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "BRK.B", "AVGO",
    "TSLA", "JPM", "LLY", "V",
]
_INDEX_MEMBERS_CACHE: dict[str, list[tuple[str, str]]] = {}


def _load_sp500_symbols() -> list[str]:
    try:
        payload = json.loads(_SP500_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    symbols = payload.get("constituents") if isinstance(payload, dict) else payload
    if not isinstance(symbols, list):
        return []
    return [str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()]


def _security_master_names() -> dict[str, str]:
    """Company names from the bundled SECF master (same file SECF/EQS use)."""
    from showme.engine.functions.screen._funcs import _load_security_master

    return {
        str(row.get("symbol") or "").upper(): str(row.get("name") or "")
        for row in _load_security_master()
        if row.get("symbol")
    }


def _sp500_members() -> list[tuple[str, str]]:
    symbols = _load_sp500_symbols()
    if not symbols:
        # Bundled file unreadable — the curated 12-name fallback keeps the
        # endpoint honest and region-correct.
        return list(_INDEX_CONSTITUENTS["SPX"])
    names = _security_master_names()
    head = [symbol for symbol in _SP500_HEAD if symbol in symbols]
    rest = [symbol for symbol in symbols if symbol not in _SP500_HEAD]
    return [(symbol, names.get(symbol) or symbol) for symbol in [*head, *rest]]


def _index_members(code: str) -> list[tuple[str, str]]:
    """Members for an index code (SPX resolves the full 503-name list)."""
    members = _INDEX_MEMBERS_CACHE.get(code)
    if members is None:
        members = _sp500_members() if code == "SPX" else list(_INDEX_CONSTITUENTS[code])
        _INDEX_MEMBERS_CACHE[code] = members
    return members


def _template_constituents(index: str) -> "Any":
    """Return a real curated constituents table for an INDEX code.

    de-garbage 2026-06-01: this used to be the brittle Wikipedia-scrape fallback
    constant. It is now a real, region-correct membership table (SPX resolves
    the bundled 503-name constituent list; NDX/DJIA/DAX/CAC/FTSE/STOXX/BIST are
    curated reference memberships). Unknown codes return a single honest ``N/A``
    disclosure row (never fabricated index members) so callers can distinguish
    "no such index" from real data without inventing tickers. Returns a pandas
    DataFrame with ``symbol`` / ``company`` columns.
    """
    import pandas as pd

    code = _canonical_index(index)
    if code is None:
        return pd.DataFrame(
            [{"symbol": "N/A", "company": f"Unknown index code: {index}"}]
        )
    return pd.DataFrame(
        [{"symbol": sym, "company": name} for sym, name in _index_members(code)]
    )


async def _fetch_price(symbol: str, timeout: float = 2.0) -> dict[str, Any] | None:
    """Best-effort keyless quote snapshot for one symbol.

    Returns the snapshot dict on success, or ``None`` on any failure so the
    caller can leave the row's price fields null without fabricating values.
    """
    try:
        from showme.quotes import fetch_quote_snapshot

        return await asyncio.wait_for(fetch_quote_snapshot(symbol), timeout=timeout)
    except Exception:  # noqa: BLE001 — network/provider failure for this symbol
        return None


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


async def _per_symbol_price_snapshots(
    symbols: list[str],
    quote_timeout: float,
) -> dict[str, dict[str, Any]]:
    """Bounded per-symbol fan-out (fallback when the batch path is absent).

    503-member indexes used to fan out an unbounded ``gather``; the semaphore
    plus wall-clock budget keeps a live provider answer from hanging the pane,
    and unresolved symbols stay null instead of being fabricated.
    """
    semaphore = asyncio.Semaphore(8)

    async def _one(symbol: str):
        async with semaphore:
            snap = await _fetch_price(symbol, timeout=quote_timeout)
        if snap is None or snap.get("source") == "showme_quote_template":
            return symbol, None
        last = _number(snap.get("last"))
        change_pct = _number(snap.get("change_pct"))
        if last is None and change_pct is None:
            return symbol, None
        return symbol, {
            "last": last,
            "change_pct": change_pct,
            "source": str(snap.get("source") or "yfinance"),
        }

    tasks = [asyncio.create_task(_one(symbol)) for symbol in symbols]
    total_budget = max(1.0, min(8.0, quote_timeout + 0.5 + 0.05 * len(symbols)))
    done, pending = await asyncio.wait(tasks, timeout=total_budget)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    out: dict[str, dict[str, Any]] = {}
    for task in done:
        try:
            symbol, snapshot = task.result()
        except Exception:  # noqa: BLE001
            continue
        if snapshot is not None:
            out[symbol] = snapshot
    return out


async def _quote_snapshots(
    symbols: list[str],
    provider: Any,
    quote_timeout: float,
) -> dict[str, dict[str, Any]]:
    """Best-effort quote map for a member list.

    Prefers the provider's batched Yahoo quote endpoint (one call per ~250
    symbols — a 503-name index resolves in two calls instead of a 2 rps
    per-symbol crawl); falls back to the bounded per-symbol fan-out so a
    provider without batch support behaves exactly as before.
    """
    batch = getattr(provider, "fetch_refdata_batch", None) if provider is not None else None
    if callable(batch):
        try:
            payload = await batch(symbols)
        except Exception:  # noqa: BLE001 — fall back per symbol below
            payload = {}
        quotes: dict[str, dict[str, Any]] = {}
        for symbol, raw in (payload or {}).items():
            if not isinstance(raw, dict):
                continue
            last = _number(raw.get("regularMarketPrice"))
            change_pct = _number(raw.get("regularMarketChangePercent"))
            if last is None and change_pct is None:
                continue
            quotes[str(symbol).upper()] = {
                "last": last,
                "change_pct": change_pct,
                "source": "yfinance",
            }
        if quotes:
            return quotes
    return await _per_symbol_price_snapshots(symbols, quote_timeout)


@FunctionRegistry.register
class ICXFunction(BaseFunction):
    code = "ICX"
    name = "Index Constituents"
    category = "screen"
    asset_classes = ("equity", "etf")
    description = "GICS sector constituents with live keyless quotes."

    async def execute(
        self, instrument: Instrument | None = None, **params: Any
    ) -> FunctionResult:
        attach_quotes = str(
            params.get("quotes", params.get("live", "1"))
        ).strip().lower() not in {"0", "false", "no", "off"}

        req_timeout = float(params.get("quote_timeout", params.get("timeout", 2.0)))
        quote_timeout = max(0.5, min(req_timeout, 4.0))

        # INDEX path: when addressed by an index code (SPX/NDX/DAX/...), resolve
        # to the curated index-member table. This honours the agent router which
        # maps ICX's query to an ``index`` key, and keeps the region-correct
        # ticker contract (a DAX query never leaks SPX names).
        raw_index = params.get("index")
        if raw_index:
            return await self._execute_index(
                instrument, str(raw_index).strip(), attach_quotes, quote_timeout
            )

        # ``sector`` is the primary input; ``parent`` / ``query`` are aliases.
        raw_sector = str(
            params.get("sector")
            or params.get("parent")
            or params.get("query")
            or "Information Technology"
        ).strip()

        sector = _canonical_sector(raw_sector)
        if sector is None:
            available = list(_SECTOR_CONSTITUENTS.keys())
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "empty",
                    "rows": [],
                    "methodology": _METHODOLOGY,
                    "field_dictionary": _FIELD_DICTIONARY,
                    "summary": {
                        "sector": raw_sector,
                        "constituent_count": 0,
                        "source": "showme_gics_reference",
                    },
                    "available_sectors": available,
                    "next_actions": [
                        "Pick a GICS sector that exists, e.g. "
                        + ", ".join(available[:5]),
                    ],
                },
                sources=["showme_gics_reference"],
                warnings=[f"unknown sector {raw_sector!r}"],
            )

        members = _SECTOR_CONSTITUENTS[sector]

        # Best-effort live quote snapshot. Constituent rows are real regardless;
        # prices are attached when the quote provider answers, otherwise left
        # null (never fabricated).
        quotes_ok = False
        rows: list[dict[str, Any]] = []
        symbol_list = [symbol for symbol, _, _ in members]
        snapshots = (
            await _quote_snapshots(
                symbol_list, getattr(self.deps, "yfinance", None), quote_timeout
            )
            if attach_quotes
            else {}
        )

        for symbol, company, sub_industry in members:
            snap = snapshots.get(symbol)
            last: float | None = snap.get("last") if snap else None
            change_pct: float | None = snap.get("change_pct") if snap else None
            if last is not None:
                quotes_ok = True
            rows.append(
                {
                    "symbol": symbol,
                    "company": company,
                    "sub_industry": sub_industry,
                    "sector": sector,
                    "last": last,
                    "change_pct": change_pct,
                }
            )

        warnings: list[str] = []
        if attach_quotes and not quotes_ok:
            warnings.append(
                "live quote snapshot unavailable; showing constituents "
                "without prices"
            )
        elif not attach_quotes:
            warnings.append("live quotes disabled by request")

        sources = ["showme_gics_reference"]
        if quotes_ok:
            sources.append("yfinance")

        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": "ok",
                "rows": rows,
                "methodology": _METHODOLOGY,
                "field_dictionary": _FIELD_DICTIONARY,
                "summary": {
                    "sector": sector,
                    "constituent_count": len(rows),
                    "source": "showme_gics_reference"
                    + ("+yfinance" if quotes_ok else ""),
                },
            },
            sources=sources,
            warnings=warnings,
        )

    async def _execute_index(
        self,
        instrument: Instrument | None,
        raw_index: str,
        attach_quotes: bool,
        quote_timeout: float,
    ) -> FunctionResult:
        """Resolve an INDEX code to its curated, region-correct member table."""
        code = _canonical_index(raw_index)
        if code is None:
            # Honest "no such index" — a single disclosure row, never fabricated
            # constituents.
            df = _template_constituents(raw_index)
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "empty",
                    "index": raw_index.upper(),
                    "constituents": 0,
                    "rows": [],
                    "methodology": _METHODOLOGY,
                    "field_dictionary": _FIELD_DICTIONARY,
                    "summary": {
                        "index": raw_index.upper(),
                        "constituent_count": 0,
                        "source": "showme_index_reference",
                    },
                    "available_indexes": sorted(_INDEX_CONSTITUENTS.keys()),
                    "next_actions": [
                        "Pick a supported index code, e.g. "
                        + ", ".join(sorted(_INDEX_CONSTITUENTS.keys())[:5]),
                    ],
                    "note": str(df.iloc[0]["company"]),
                },
                sources=["showme_index_reference"],
                warnings=[f"unknown index code {raw_index!r}"],
            )

        members = _index_members(code)
        quotes_ok = False
        rows: list[dict[str, Any]] = []
        symbol_list = [symbol for symbol, _ in members]
        snapshots = (
            await _quote_snapshots(
                symbol_list, getattr(self.deps, "yfinance", None), quote_timeout
            )
            if attach_quotes
            else {}
        )

        for symbol, company in members:
            snap = snapshots.get(symbol)
            last: float | None = snap.get("last") if snap else None
            change_pct: float | None = snap.get("change_pct") if snap else None
            if last is not None:
                quotes_ok = True
            rows.append(
                {
                    "symbol": symbol,
                    "company": company,
                    "index": code,
                    "last": last,
                    "change_pct": change_pct,
                }
            )

        warnings: list[str] = []
        if attach_quotes and not quotes_ok:
            warnings.append(
                "live quote snapshot unavailable; showing constituents without prices"
            )
        elif not attach_quotes:
            warnings.append("live quotes disabled by request")

        sources = ["showme_index_reference"]
        if quotes_ok:
            sources.append("yfinance")

        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": "ok",
                "index": code,
                "constituents": len(rows),
                "rows": rows,
                "methodology": _METHODOLOGY,
                "field_dictionary": _FIELD_DICTIONARY,
                "summary": {
                    "index": code,
                    "constituent_count": len(rows),
                    "source": "showme_index_reference"
                    + ("+yfinance" if quotes_ok else ""),
                },
            },
            sources=sources,
            warnings=warnings,
        )
