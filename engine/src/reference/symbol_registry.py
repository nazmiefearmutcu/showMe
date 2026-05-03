"""Cross-asset symbol registry.

Resolves a user-typed string ("AAPL", "BTC", "EURUSD", "US10Y") to a typed
``Instrument``. Falls back through (1) local cache, (2) heuristic, (3)
OpenFIGI lookup. Stores resolved instruments in DuckDB ``symbols`` table.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from src.core.instrument import AssetClass, Instrument
from src.reference.exchange_registry import EXCHANGES, ExchangeRegistry

# ── Built-in seeds (offline lookup before hitting the network) ──
_CRYPTO_BASES = {
    "BTC", "ETH", "BNB", "SOL", "ADA", "XRP", "DOGE", "MATIC", "DOT",
    "AVAX", "LINK", "TRX", "TON", "SHIB", "LTC", "BCH", "UNI", "ATOM",
    "XLM", "FIL", "ETC", "ALGO", "VET", "EGLD", "ICP", "NEAR", "APT",
    "ARB", "OP", "INJ", "SUI", "PYTH", "TIA", "FTM", "AAVE", "GRT",
}
_CRYPTO_QUOTES = {"USDT", "USDC", "BUSD", "BTC", "ETH", "EUR", "TRY"}

_FX_MAJORS = {"EUR", "GBP", "USD", "JPY", "CHF", "AUD", "CAD", "NZD"}
_FX_OTHERS = {"TRY", "ZAR", "MXN", "BRL", "RUB", "CNY", "INR", "KRW", "SEK", "NOK"}
_FX_CCY = _FX_MAJORS | _FX_OTHERS

_FRED_SERIES_PREFIX = re.compile(r"^(DGS\d+|DFF|DFEDTAR|CPIAUCSL|UNRATE|GDPC1|UMCSENT|HOUST|PAYEMS|VIXCLS)$")
_US_TREASURY_PATTERN = re.compile(r"^(US\d+[YM])$", re.I)

# Common ETFs (we map ETF separately so functions distinguish from equity)
_KNOWN_ETFS = {
    "SPY","QQQ","IWM","DIA","EEM","EFA","VTI","VOO","VEA","VWO",
    "AGG","BND","TLT","IEF","SHY","HYG","LQD","TIP","GLD","SLV",
    "USO","UNG","XLF","XLE","XLK","XLV","XLI","XLY","XLP","XLU",
    "XLB","XLRE","ARKK","ARKW","ARKG","SOXX","SMH","XBI","KRE","KBE",
}

_KNOWN_INDICES = {
    "^GSPC": ("S&P 500", "US"),
    "^DJI": ("Dow Jones", "US"),
    "^IXIC": ("NASDAQ Composite", "US"),
    "^RUT": ("Russell 2000", "US"),
    "^FTSE": ("FTSE 100", "GB"),
    "^GDAXI": ("DAX", "DE"),
    "^FCHI": ("CAC 40", "FR"),
    "^N225": ("Nikkei 225", "JP"),
    "^HSI": ("Hang Seng", "HK"),
    "^STOXX50E": ("Euro Stoxx 50", "EU"),
    "^XU100": ("BIST 100", "TR"),
    "XU100.IS": ("BIST 100", "TR"),
}


class SymbolRegistry:
    """Resolves bare user input → typed Instrument.

    Caches resolutions to ``runtime/symbols.sqlite``.
    """

    def __init__(
        self,
        cache_path: Path | str = "runtime/symbols.sqlite",
        openfigi_adapter: Any | None = None,
    ) -> None:
        self.cache_path = Path(cache_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.cache_path)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS symbols("
            "key TEXT PRIMARY KEY, "
            "data TEXT NOT NULL, "
            "ts INTEGER NOT NULL)"
        )
        self._db.commit()
        self.openfigi = openfigi_adapter
        self.exchanges = ExchangeRegistry()

    # ───────── Public ─────────
    async def resolve(self, user_input: str) -> Instrument | None:
        """Best-effort: cache → heuristic → OpenFIGI."""
        key = user_input.strip().upper()
        if not key:
            return None
        cached = self._cache_get(key)
        if cached:
            return cached

        instrument = self._heuristic(key)
        if instrument:
            self._cache_set(key, instrument)
            return instrument

        if self.openfigi is not None:
            try:
                instrument = await self._lookup_openfigi(key)
                if instrument:
                    self._cache_set(key, instrument)
                    return instrument
            except Exception:
                pass

        return None

    def resolve_sync(self, user_input: str) -> Instrument | None:
        """Synchronous fast path: cache + heuristic only (no network)."""
        key = user_input.strip().upper()
        cached = self._cache_get(key)
        if cached:
            return cached
        return self._heuristic(key)

    def upsert(self, instrument: Instrument, *aliases: str) -> None:
        keys = [instrument.symbol.upper(), *(a.upper() for a in aliases)]
        for k in keys:
            self._cache_set(k, instrument)

    # ───────── Heuristic ─────────
    def _heuristic(self, key: str) -> Instrument | None:
        # 1) Indices
        if key in _KNOWN_INDICES:
            name, country = _KNOWN_INDICES[key]
            return Instrument(
                symbol=key, asset_class=AssetClass.INDEX,
                exchange=None, currency="USD", name=name,
                metadata={"country": country},
            )
        # 2) FRED-style macro series
        if _FRED_SERIES_PREFIX.match(key):
            return Instrument.macro_series(series_id=key, exchange="FRED",
                                           name=f"FRED {key}")
        # 3) US Treasury maturity ("US10Y")
        m = _US_TREASURY_PATTERN.match(key)
        if m:
            return Instrument(symbol=key, asset_class=AssetClass.BOND,
                              exchange="UST", currency="USD",
                              name=f"US Treasury {key[2:]}")
        # 4) FX ("EURUSD" or "EUR/USD")
        clean = key.replace("/", "")
        if len(clean) == 6 and clean[:3] in _FX_CCY and clean[3:] in _FX_CCY:
            return Instrument(
                symbol=clean, asset_class=AssetClass.FX,
                exchange="FX", currency=clean[3:],
                metadata={"base_currency": clean[:3], "quote_currency": clean[3:]},
                name=f"{clean[:3]}/{clean[3:]}",
            )
        # 5) Crypto pair ("BTCUSDT" / "BTC")
        for q in sorted(_CRYPTO_QUOTES, key=len, reverse=True):
            if key.endswith(q) and key[:-len(q)] in _CRYPTO_BASES:
                base = key[:-len(q)]
                return Instrument.crypto(
                    symbol=key, exchange="BINANCE", currency=q,
                    name=f"{base}/{q}",
                    metadata={"base": base, "quote": q, "contract_type": "PERPETUAL"},
                )
        if key in _CRYPTO_BASES:
            sym = f"{key}USDT"
            return Instrument.crypto(
                symbol=sym, exchange="BINANCE", currency="USDT",
                name=f"{key}/USDT",
                metadata={"base": key, "quote": "USDT", "contract_type": "PERPETUAL"},
            )
        # 6) ETFs (US-listed)
        if key in _KNOWN_ETFS:
            return Instrument(
                symbol=key, asset_class=AssetClass.ETF,
                exchange="NYSE", currency="USD", name=key,
            )
        # 7) Equity with explicit suffix (THYAO.IS, BP.L, 7203.T)
        if "." in key:
            suffix = "." + key.rsplit(".", 1)[1]
            ex = self.exchanges.by_suffix(suffix)
            if ex:
                return Instrument(
                    symbol=key, asset_class=AssetClass.EQUITY,
                    exchange=ex.code, currency=ex.currency, name=None,
                )
        # 8) Bare US ticker (3-5 letters, no dot/digits) → assume NASDAQ/NYSE
        if 1 <= len(key) <= 5 and key.isalpha():
            return Instrument(
                symbol=key, asset_class=AssetClass.EQUITY,
                exchange="NASDAQ", currency="USD",
            )
        return None

    # ───────── Cache I/O ─────────
    def _cache_get(self, key: str) -> Instrument | None:
        row = self._db.execute(
            "SELECT data FROM symbols WHERE key = ?", (key,)
        ).fetchone()
        if not row:
            return None
        import json
        return Instrument.from_dict(json.loads(row[0]))

    def _cache_set(self, key: str, instrument: Instrument) -> None:
        import json
        import time
        self._db.execute(
            "INSERT OR REPLACE INTO symbols(key, data, ts) VALUES (?, ?, ?)",
            (key, json.dumps(instrument.to_dict()), int(time.time())),
        )
        self._db.commit()

    async def _lookup_openfigi(self, key: str) -> Instrument | None:
        """Use the OpenFIGI adapter to resolve unknown tickers."""
        # Best-effort: call the adapter; if it returns FIGI metadata, build Instrument.
        if self.openfigi is None:
            return None
        try:
            r = await self.openfigi.lookup(key)
        except Exception:
            return None
        if not r:
            return None
        return Instrument(
            symbol=r.get("ticker", key),
            asset_class=_map_market_sec_des(r.get("marketSector", ""), r.get("securityType", "")),
            exchange=r.get("exchCode"),
            currency=r.get("currency", "USD"),
            figi=r.get("figi"),
            name=r.get("name"),
            metadata={"raw": r},
        )


def _map_market_sec_des(market_sector: str, security_type: str) -> AssetClass:
    s = (market_sector or "").lower()
    t = (security_type or "").lower()
    if "equity" in s or "common stock" in t:
        return AssetClass.EQUITY
    if "fund" in t or "etf" in t:
        return AssetClass.ETF if "etf" in t else AssetClass.FUND
    if "govt" in s or "muni" in s or "corp" in s or "bond" in t or "note" in t:
        return AssetClass.BOND
    if "curncy" in s:
        return AssetClass.FX
    if "comdty" in s:
        return AssetClass.COMMODITY
    if "index" in s or "index" in t:
        return AssetClass.INDEX
    if "option" in t or "future" in t or "warrant" in t:
        return AssetClass.DERIVATIVE
    return AssetClass.EQUITY
