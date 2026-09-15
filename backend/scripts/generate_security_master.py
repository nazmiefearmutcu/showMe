#!/usr/bin/env python3
"""Regenerate ``showme/engine/reference/data/security_master.json`` for SECF.

The generated JSON is committed to the repo tree; SECF loads it with a
memoized loader and falls back to its bundled 13-row reference list when the
file is missing or unreadable. Re-run only when the bundled master is stale:

    python scripts/generate_security_master.py

Dev-time sources (network):
  * ``ui/src/data/sp500.json`` — in-repo S&P 500 constituent snapshot (truth
    for index membership).
  * ``datasets/s-and-p-500-companies`` constituents.csv — company names and
    GICS sector/sub-industry (current snapshot + the 2025-05 revision so
    members that have since left the index keep their identity).
  * ``rreichel3/US-Stock-Symbols`` nasdaq/nyse/amex ticker lists — primary
    exchange guess; symbols absent from all three fall back to ``US``.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import re
import sys
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
SP500_PATH = REPO_ROOT / "ui" / "src" / "data" / "sp500.json"
OUT_PATH = REPO_ROOT / "backend" / "showme" / "engine" / "reference" / "data" / "security_master.json"

CONSTITUENTS_CSV = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
CONSTITUENTS_CSV_2025Q2 = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/"
    "28bac5b428772da287bd087e04c616712acaeade/data/constituents.csv"
)
TICKER_LISTS = {
    market: f"https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/{market}/{market}_tickers.json"
    for market in ("nasdaq", "nyse", "amex")
}

# Members that dropped out of both CSV snapshots (index changes between the
# 2025-Q2 snapshot and today) — identity curated by hand.
_SECTOR_OVERRIDES: dict[str, tuple[str, str, str]] = {
    "TFX": ("Teleflex", "Health Care", "Health Care Equipment & Supplies"),
    "DFS": ("Discover Financial Services", "Financials", "Consumer Finance"),
}

# Exchange guesses for symbols missing from the ticker lists (dot-class shares
# and index members that have since been delisted).
_EXCHANGE_OVERRIDES: dict[str, str] = {
    "ANSS": "NASDAQ", "AVB": "NYSE", "BF.B": "NYSE", "BK": "NYSE",
    "BRK.B": "NYSE", "CBOE": "CBOE", "CTRA": "NYSE", "DAY": "NYSE",
    "DFS": "NYSE", "EA": "NASDAQ", "EQR": "NYSE", "FI": "NYSE",
    "HES": "NYSE", "HOLX": "NASDAQ", "IPG": "NYSE", "JNPR": "NYSE",
    "K": "NYSE", "MMC": "NYSE", "TFX": "NYSE", "WBA": "NASDAQ",
}

_TAG_STOPWORDS = {"and", "of", "the", "for", "to"}

_ETF_ROWS = [
    ("SPY", "SPDR S&P 500 ETF Trust", "NYSE Arca", "Broad Market", ["etf", "index fund", "s&p 500", "large cap"]),
    ("QQQ", "Invesco QQQ Trust", "NASDAQ", "Broad Market", ["etf", "index fund", "nasdaq 100", "large cap"]),
    ("IWM", "iShares Russell 2000 ETF", "NYSE Arca", "Broad Market", ["etf", "index fund", "russell 2000", "small cap"]),
    ("DIA", "SPDR Dow Jones Industrial Average ETF Trust", "NYSE Arca", "Broad Market", ["etf", "index fund", "dow jones", "large cap"]),
    ("TLT", "iShares 20+ Year Treasury Bond ETF", "NASDAQ", "Fixed Income", ["etf", "treasury", "duration", "bond"]),
    ("GLD", "SPDR Gold Shares", "NYSE Arca", "Commodity Precious Metals", ["etf", "gold", "precious metals"]),
    ("SLV", "iShares Silver Trust", "NYSE Arca", "Commodity Precious Metals", ["etf", "silver", "precious metals"]),
    ("XLE", "Energy Select Sector SPDR Fund", "NYSE Arca", "Sector Equity", ["etf", "energy", "oil", "gas"]),
    ("XLF", "Financial Select Sector SPDR Fund", "NYSE Arca", "Sector Equity", ["etf", "financials", "banks"]),
    ("XLK", "Technology Select Sector SPDR Fund", "NYSE Arca", "Sector Equity", ["etf", "technology", "software", "hardware"]),
    ("XLV", "Health Care Select Sector SPDR Fund", "NYSE Arca", "Sector Equity", ["etf", "health care", "biotechnology", "pharmaceuticals"]),
    ("XLI", "Industrial Select Sector SPDR Fund", "NYSE Arca", "Sector Equity", ["etf", "industrials", "machinery"]),
    ("XLY", "Consumer Discretionary Select Sector SPDR Fund", "NYSE Arca", "Sector Equity", ["etf", "consumer discretionary", "retail"]),
    ("XLP", "Consumer Staples Select Sector SPDR Fund", "NYSE Arca", "Sector Equity", ["etf", "consumer staples", "food"]),
    ("XLU", "Utilities Select Sector SPDR Fund", "NYSE Arca", "Sector Equity", ["etf", "utilities", "power"]),
    ("XLB", "Materials Select Sector SPDR Fund", "NYSE Arca", "Sector Equity", ["etf", "materials", "chemicals"]),
    ("XLRE", "Real Estate Select Sector SPDR Fund", "NYSE Arca", "Sector Equity", ["etf", "real estate", "reit"]),
    ("XLC", "Communication Services Select Sector SPDR Fund", "NYSE Arca", "Sector Equity", ["etf", "communication services", "media"]),
]

_CRYPTO_ROWS = [
    ("BTCUSDT", "Bitcoin / Tether", ["bitcoin", "btc", "crypto", "digital assets", "spot"]),
    ("ETHUSDT", "Ethereum / Tether", ["ethereum", "eth", "crypto", "digital assets", "smart contracts", "spot"]),
    ("SOLUSDT", "Solana / Tether", ["solana", "sol", "crypto", "digital assets", "spot"]),
    ("BNBUSDT", "BNB / Tether", ["bnb", "binance coin", "crypto", "digital assets", "spot"]),
    ("XRPUSDT", "XRP / Tether", ["xrp", "ripple", "crypto", "digital assets", "spot"]),
    ("ADAUSDT", "Cardano / Tether", ["cardano", "ada", "crypto", "digital assets", "spot"]),
    ("DOGEUSDT", "Dogecoin / Tether", ["dogecoin", "doge", "crypto", "digital assets", "spot"]),
    ("AVAXUSDT", "Avalanche / Tether", ["avalanche", "avax", "crypto", "digital assets", "spot"]),
    ("LINKUSDT", "Chainlink / Tether", ["chainlink", "link", "crypto", "digital assets", "oracle", "spot"]),
    ("LTCUSDT", "Litecoin / Tether", ["litecoin", "ltc", "crypto", "digital assets", "spot"]),
    ("DOTUSDT", "Polkadot / Tether", ["polkadot", "dot", "crypto", "digital assets", "spot"]),
    ("UNIUSDT", "Uniswap / Tether", ["uniswap", "uni", "crypto", "digital assets", "defi", "spot"]),
]

_FX_ROWS = [
    ("EURUSD", "Euro / US Dollar", ["euro", "us dollar", "fx", "foreign exchange", "g10"]),
    ("GBPUSD", "British Pound / US Dollar", ["british pound", "sterling", "us dollar", "fx", "g10"]),
    ("USDJPY", "US Dollar / Japanese Yen", ["us dollar", "japanese yen", "fx", "g10"]),
    ("AUDUSD", "Australian Dollar / US Dollar", ["australian dollar", "us dollar", "fx", "g10"]),
    ("USDCAD", "US Dollar / Canadian Dollar", ["us dollar", "canadian dollar", "fx", "g10"]),
    ("USDCHF", "US Dollar / Swiss Franc", ["us dollar", "swiss franc", "fx", "g10"]),
    ("NZDUSD", "New Zealand Dollar / US Dollar", ["new zealand dollar", "us dollar", "fx", "g10"]),
    ("EURGBP", "Euro / British Pound", ["euro", "british pound", "fx", "g10"]),
    ("EURJPY", "Euro / Japanese Yen", ["euro", "japanese yen", "fx", "g10"]),
]

_COMMODITY_ROWS = [
    ("GC=F", "Gold Futures", "COMEX", "Metals", ["gold", "precious metals", "futures", "commodity"]),
    ("SI=F", "Silver Futures", "COMEX", "Metals", ["silver", "precious metals", "futures", "commodity"]),
    ("CL=F", "WTI Crude Oil Futures", "NYMEX", "Energy", ["oil", "crude", "wti", "energy", "futures", "commodity"]),
    ("NG=F", "Natural Gas Futures", "NYMEX", "Energy", ["natural gas", "energy", "futures", "commodity"]),
    ("HG=F", "Copper Futures", "COMEX", "Metals", ["copper", "base metals", "futures", "commodity"]),
]

_INDEX_ROWS = [
    ("^GSPC", "S&P 500 Index", "S&P Dow Jones", ["s&p 500", "benchmark", "equity index", "large cap"]),
    ("^NDX", "Nasdaq 100 Index", "Nasdaq", ["nasdaq 100", "benchmark", "equity index", "large cap"]),
    ("^DJI", "Dow Jones Industrial Average", "S&P Dow Jones", ["dow jones", "benchmark", "equity index", "large cap"]),
    ("^RUT", "Russell 2000 Index", "FTSE Russell", ["russell 2000", "benchmark", "equity index", "small cap"]),
    ("^VIX", "Cboe Volatility Index", "CBOE", ["volatility", "vix", "fear index", "benchmark"]),
    ("^TNX", "Cboe 10-Year Treasury Note Yield Index", "CBOE", ["treasury", "yield", "rates", "benchmark"]),
]


def _fetch_text(url: str) -> str:
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.text


def _fetch_csv(url: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(_fetch_text(url))))


def _load_sector_map() -> dict[str, dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    for url in (CONSTITUENTS_CSV, CONSTITUENTS_CSV_2025Q2):
        for row in _fetch_csv(url):
            symbol = str(row.get("Symbol") or "").strip().upper()
            if symbol and symbol not in merged:
                merged[symbol] = row
    for symbol, (name, sector, sub_industry) in _SECTOR_OVERRIDES.items():
        merged.setdefault(
            symbol,
            {"Symbol": symbol, "Security": name, "GICS Sector": sector, "GICS Sub-Industry": sub_industry},
        )
    return merged


def _load_exchange_map() -> dict[str, str]:
    exchanges: dict[str, str] = {}
    for market, url in TICKER_LISTS.items():
        for symbol in json.loads(_fetch_text(url)):
            exchanges.setdefault(str(symbol).upper(), market.upper())
    for symbol, exchange in _EXCHANGE_OVERRIDES.items():
        exchanges.setdefault(symbol, exchange)
    return exchanges


def _tag_words(*phrases: str) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for phrase in phrases:
        if not phrase:
            continue
        low = phrase.strip().lower()
        for token in [low, *re.split(r"[^a-z0-9]+", low)]:
            token = token.strip()
            if not token or token in _TAG_STOPWORDS or token in seen:
                continue
            seen.add(token)
            tags.append(token)
    return tags


def _baseline_rows() -> list[dict[str, Any]]:
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    from showme.engine.functions.screen._funcs import _SECURITY_FALLBACK_ROWS

    return [dict(row) for row in _SECURITY_FALLBACK_ROWS]


def _sp500_rows(sectors: dict[str, dict[str, str]], exchanges: dict[str, str]) -> list[dict[str, Any]]:
    constituents = json.loads(SP500_PATH.read_text(encoding="utf-8"))["constituents"]
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for symbol in constituents:
        reference = sectors.get(str(symbol).upper())
        if not reference:
            missing.append(symbol)
            continue
        sector = str(reference.get("GICS Sector") or "").strip()
        sub_industry = str(reference.get("GICS Sub-Industry") or "").strip()
        rows.append({
            "symbol": symbol,
            "name": str(reference.get("Security") or "").strip() or symbol,
            "asset_class": "EQUITY",
            "exchange": exchanges.get(str(symbol).upper(), "US"),
            "country": "US",
            "sector": sector,
            "tags": _tag_words(sector, sub_industry, "s&p 500", "sp500", "equity", "stock", "large cap"),
        })
    if missing:
        raise SystemExit(f"No reference identity for: {', '.join(missing)}")
    return rows


def _extra_rows(
    spec: list[tuple[Any, ...]],
    *,
    asset_class: str,
    exchange: str,
    country: str,
    sector: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in spec:
        row_exchange: str | None = None
        row_sector: str | None = None
        if len(entry) == 3:
            symbol, name, tags = entry
        elif len(entry) == 4:
            symbol, name, row_exchange, tags = entry
        else:
            symbol, name, row_exchange, row_sector, tags = entry
        rows.append({
            "symbol": symbol,
            "name": name,
            "asset_class": asset_class,
            "exchange": row_exchange or exchange,
            "country": country,
            "sector": row_sector or sector,
            "tags": tags,
        })
    return rows


def build_master() -> list[dict[str, Any]]:
    sectors = _load_sector_map()
    exchanges = _load_exchange_map()
    groups: list[list[dict[str, Any]]] = [
        _baseline_rows(),
        _sp500_rows(sectors, exchanges),
        _extra_rows(_ETF_ROWS, asset_class="ETF", exchange="NYSE Arca", country="US", sector="ETF"),
        _extra_rows(_CRYPTO_ROWS, asset_class="CRYPTO", exchange="Binance", country="Global", sector="Digital Assets"),
        _extra_rows(_FX_ROWS, asset_class="FX", exchange="FX", country="Global", sector="G10 FX"),
        _extra_rows(_COMMODITY_ROWS, asset_class="COMMODITY", exchange="COMEX", country="US", sector="Commodities"),
        _extra_rows(_INDEX_ROWS, asset_class="INDEX", exchange="S&P Dow Jones", country="US", sector="Index"),
    ]
    master: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for row in group:
            symbol = str(row["symbol"]).upper()
            if symbol in seen:
                continue
            seen.add(symbol)
            master.append(row)
    return master


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(OUT_PATH))
    args = parser.parse_args()

    rows = build_master()
    payload = {
        "name": "ShowMe security reference master",
        "version": 1,
        "source": (
            "Generated by backend/scripts/generate_security_master.py from "
            "ui/src/data/sp500.json + datasets/s-and-p-500-companies + "
            "rreichel3/US-Stock-Symbols"
        ),
        "generated": dt.datetime.now(dt.UTC).date().isoformat(),
        "rows": rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} rows to {out}")


if __name__ == "__main__":
    main()
