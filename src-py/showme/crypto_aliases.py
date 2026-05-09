"""Crypto symbol/name normalization helpers for user-facing inputs.

The function engine expects exchange-style symbols such as ``ETHUSDT``. Users
often type natural coin names instead, so the native shell and sidecar share
this resolver before an input is routed into ANR, CN, WATCH, or quote streams.
"""
from __future__ import annotations

from functools import lru_cache
import os
import re
import time

import requests


CRYPTO_QUOTE_SUFFIXES = ("USDT", "USDC", "FDUSD", "USD", "BTC", "ETH", "EUR")

CRYPTO_DISPLAY_NAMES: dict[str, str] = {
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "SOL": "Solana",
    "BNB": "BNB",
    "XRP": "XRP",
    "ADA": "Cardano",
    "DOGE": "Dogecoin",
    "AVAX": "Avalanche",
    "DOT": "Polkadot",
    "LINK": "Chainlink",
    "MATIC": "Polygon",
    "TRX": "TRON",
    "LTC": "Litecoin",
    "BCH": "Bitcoin Cash",
    "UNI": "Uniswap",
    "ATOM": "Cosmos",
    "ETC": "Ethereum Classic",
    "NEAR": "NEAR Protocol",
    "FIL": "Filecoin",
    "ICP": "Internet Computer",
    "APT": "Aptos",
    "ARB": "Arbitrum",
    "OP": "Optimism",
    "SUI": "Sui",
    "SEI": "Sei",
    "TIA": "Celestia",
    "INJ": "Injective",
    "AAVE": "Aave",
    "MKR": "Maker",
    "LDO": "Lido DAO",
    "RUNE": "THORChain",
    "FTM": "Fantom",
    "FET": "Fetch.ai",
    "WLD": "Worldcoin",
    "RENDER": "Render",
    "RNDR": "Render",
    "TON": "Toncoin",
    "SHIB": "Shiba Inu",
    "PEPE": "Pepe",
    "WIF": "dogwifhat",
    "FLOKI": "FLOKI",
    "BONK": "Bonk",
    "FLOCK": "FLock.io",
    "LUNC": "Terra Classic",
    "GALA": "Gala",
    "SAND": "The Sandbox",
    "MANA": "Decentraland",
    "AXS": "Axie Infinity",
    "CHZ": "Chiliz",
    "ENJ": "Enjin Coin",
    "JASMY": "JasmyCoin",
    "PYTH": "Pyth Network",
    "JUP": "Jupiter",
    "BOME": "Book of Meme",
    "ORDI": "Ordinals",
    "STX": "Stacks",
    "ENS": "Ethereum Name Service",
    "DYDX": "dYdX",
    "IMX": "Immutable",
    "ALGO": "Algorand",
    "VET": "VeChain",
    "HBAR": "Hedera",
    "QNT": "Quant",
    "XLM": "Stellar",
    "XMR": "Monero",
    "ZEC": "Zcash",
    "EOS": "EOS",
    "KAVA": "Kava",
    "FLOW": "Flow",
    "CRV": "Curve DAO Token",
    "COMP": "Compound",
    "SNX": "Synthetix",
    "CAKE": "PancakeSwap",
    "1INCH": "1inch",
    "GRT": "The Graph",
    "LRC": "Loopring",
    "ZIL": "Zilliqa",
}

CRYPTO_BASES = set(CRYPTO_DISPLAY_NAMES)

BASE_PAIR_OVERRIDES = {
    "RNDR": "RENDERUSDT",
}

EXTRA_ALIASES: dict[str, str] = {
    "ether": "ETH",
    "ethcoin": "ETH",
    "binancecoin": "BNB",
    "binance": "BNB",
    "ripple": "XRP",
    "avalanche2": "AVAX",
    "polygonpos": "MATIC",
    "polygonmatic": "MATIC",
    "maticnetwork": "MATIC",
    "cosmoshub": "ATOM",
    "nearprotocol": "NEAR",
    "internetcomputer": "ICP",
    "ethereumclassic": "ETC",
    "bitcoinabc": "BCH",
    "bitcoincash": "BCH",
    "lidao": "LDO",
    "lidodao": "LDO",
    "thorchain": "RUNE",
    "fetchai": "FET",
    "artificialsuperintelligencealliance": "FET",
    "worldcoin": "WLD",
    "rendernetwork": "RENDER",
    "ton": "TON",
    "theopennetwork": "TON",
    "shibainu": "SHIB",
    "dogwifhat": "WIF",
    "terra classic": "LUNC",
    "terraclassic": "LUNC",
    "thesandbox": "SAND",
    "axieinfinity": "AXS",
    "enjincoin": "ENJ",
    "pythnetwork": "PYTH",
    "bookofmeme": "BOME",
    "ethereumname": "ENS",
    "ethereumname service": "ENS",
    "immutablex": "IMX",
    "vechain": "VET",
    "hedera": "HBAR",
    "quantnetwork": "QNT",
    "stellar": "XLM",
    "monero": "XMR",
    "zcash": "ZEC",
    "curvedao": "CRV",
    "curvedaotoken": "CRV",
    "compoundfinance": "COMP",
    "pancakeswap": "CAKE",
    "thegraph": "GRT",
}

_DYNAMIC_CACHE_TTL_SECONDS = 24 * 60 * 60
_DYNAMIC_ALIAS_CACHE: dict[str, tuple[float, str | None]] = {}


def crypto_alias_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").strip().lower())


def compact_symbol(value: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9=^./-]", "", str(value or "").strip()).upper()


def canonical_crypto_pair(base: str) -> str:
    clean_base = compact_symbol(base).replace("/", "").replace("-", "")
    return BASE_PAIR_OVERRIDES.get(clean_base, f"{clean_base}USDT")


def _build_static_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for base, name in CRYPTO_DISPLAY_NAMES.items():
        pair = canonical_crypto_pair(base)
        aliases[crypto_alias_key(base)] = pair
        aliases[crypto_alias_key(name)] = pair
    for alias, base in EXTRA_ALIASES.items():
        aliases[crypto_alias_key(alias)] = canonical_crypto_pair(base)
    return aliases


CRYPTO_ALIAS_TO_PAIR = _build_static_aliases()


def split_crypto_symbol(symbol: str | None) -> tuple[str, str]:
    value = compact_symbol(symbol).replace("/", "").replace("-", "")
    for quote in sorted(CRYPTO_QUOTE_SUFFIXES, key=len, reverse=True):
        if value.endswith(quote) and len(value) > len(quote):
            return value[: -len(quote)], quote
    return value, "USD"


def is_crypto_symbol(symbol: str | None) -> bool:
    value = compact_symbol(symbol).replace("/", "").replace("-", "")
    if not value:
        return False
    if value in CRYPTO_BASES:
        return True
    if _looks_like_universal_stable_pair(value):
        return True
    return any(
        value.endswith(suffix)
        and value[: -len(suffix)] in CRYPTO_BASES
        and len(value) > len(suffix)
        for suffix in CRYPTO_QUOTE_SUFFIXES
    )


def resolve_crypto_symbol_alias(symbol: str | None, *, allow_network: bool = True) -> str:
    """Return a canonical crypto pair when ``symbol`` is a known coin name.

    Unknown equities/indices are returned as ordinary uppercase symbols. Network
    lookup is intentionally limited to natural-looking names so common equity
    tickers such as ``AAPL`` are never sent through crypto discovery.
    """
    raw = str(symbol or "").strip()
    if not raw:
        return ""
    upper = compact_symbol(raw)
    compact = upper.replace("/", "").replace("-", "")
    key = crypto_alias_key(raw)
    if key in CRYPTO_ALIAS_TO_PAIR:
        return CRYPTO_ALIAS_TO_PAIR[key]
    if _looks_like_crypto_pair(compact):
        return compact
    if compact in CRYPTO_BASES and _should_treat_base_as_crypto(raw):
        return canonical_crypto_pair(compact)
    if allow_network and _looks_like_natural_coin_name(raw):
        dynamic = _dynamic_crypto_alias(raw)
        if dynamic:
            return dynamic
    return upper


def _looks_like_crypto_pair(compact: str) -> bool:
    if _looks_like_universal_stable_pair(compact):
        return True
    return any(
        compact.endswith(suffix)
        and compact[: -len(suffix)] in CRYPTO_BASES
        and len(compact) > len(suffix)
        for suffix in CRYPTO_QUOTE_SUFFIXES
    )


def _looks_like_universal_stable_pair(compact: str) -> bool:
    return any(
        compact.endswith(suffix)
        and re.fullmatch(r"[A-Z0-9]{1,20}", compact[: -len(suffix)] or "") is not None
        for suffix in ("USDT", "USDC", "FDUSD")
    )


def _should_treat_base_as_crypto(raw: str) -> bool:
    return raw.isupper() or raw.islower() or raw.strip().isalnum()


def _looks_like_natural_coin_name(raw: str) -> bool:
    text = raw.strip()
    if not text or any(ch in text for ch in "^=/"):
        return False
    if text.isupper() and len(text) <= 5:
        return False
    return bool(re.search(r"[A-Za-z]", text))


def _dynamic_crypto_alias(raw: str) -> str | None:
    if os.environ.get("SHOWME_CRYPTO_ALIAS_NETWORK") == "0":
        return None
    key = crypto_alias_key(raw)
    now = time.time()
    cached = _DYNAMIC_ALIAS_CACHE.get(key)
    if cached and now - cached[0] < _DYNAMIC_CACHE_TTL_SECONDS:
        return cached[1]
    candidates: list[str] = []
    mapped = _coingecko_symbol_for_key(key)
    if mapped:
        candidates.append(mapped)
    compact = crypto_alias_key(raw).upper()
    if 2 <= len(compact) <= 16:
        candidates.append(compact)
    for base in dict.fromkeys(candidates):
        pair = _binance_listed_pair_for_base(base)
        if pair:
            _DYNAMIC_ALIAS_CACHE[key] = (now, pair)
            return pair
    _DYNAMIC_ALIAS_CACHE[key] = (now, None)
    return None


def _coingecko_symbol_for_key(key: str) -> str | None:
    try:
        mapping = _coingecko_symbol_map()
    except Exception:
        return None
    return mapping.get(key)


@lru_cache(maxsize=1)
def _coingecko_symbol_map() -> dict[str, str]:
    response = requests.get(
        "https://api.coingecko.com/api/v3/coins/list",
        params={"include_platform": "false"},
        headers={"User-Agent": "showMe/1.0"},
        timeout=3.5,
    )
    response.raise_for_status()
    rows = response.json() or []
    mapping: dict[str, str] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        symbol = compact_symbol(item.get("symbol"))
        if not re.fullmatch(r"[A-Z0-9]{2,16}", symbol or ""):
            continue
        for raw_key in (item.get("id"), item.get("name")):
            item_key = crypto_alias_key(str(raw_key or ""))
            if item_key:
                mapping.setdefault(item_key, symbol)
    return mapping


@lru_cache(maxsize=1024)
def _binance_listed_pair_for_base(base: str) -> str | None:
    clean_base = compact_symbol(base).replace("/", "").replace("-", "")
    if not re.fullmatch(r"[A-Z0-9]{2,16}", clean_base or ""):
        return None
    for quote in ("USDT", "USDC", "FDUSD", "USD"):
        pair = f"{clean_base}{quote}"
        try:
            response = requests.get(
                "https://api.binance.com/api/v3/exchangeInfo",
                params={"symbol": pair},
                headers={"User-Agent": "showMe/1.0"},
                timeout=2.0,
            )
            if response.status_code != 200:
                continue
            payload = response.json() or {}
            listings = payload.get("symbols") or []
            if not listings:
                continue
            status = str(listings[0].get("status") or "").upper()
            if status in {"TRADING", "BREAK"}:
                return pair
        except Exception:
            pass
    try:
        response = requests.get(
            "https://fapi.binance.com/fapi/v1/exchangeInfo",
            headers={"User-Agent": "showMe/1.0"},
            timeout=2.5,
        )
        if response.status_code != 200:
            return None
        payload = response.json() or {}
        listings = payload.get("symbols") or []
    except Exception:
        return None
    for quote in ("USDT", "USDC", "FDUSD", "USD"):
        pair = f"{clean_base}{quote}"
        for item in listings:
            if str(item.get("symbol") or "").upper() != pair:
                continue
            status = str(item.get("status") or "").upper()
            if status in {"TRADING", "PENDING_TRADING"}:
                return pair
    return None


__all__ = [
    "CRYPTO_ALIAS_TO_PAIR",
    "CRYPTO_BASES",
    "CRYPTO_DISPLAY_NAMES",
    "CRYPTO_QUOTE_SUFFIXES",
    "compact_symbol",
    "crypto_alias_key",
    "is_crypto_symbol",
    "resolve_crypto_symbol_alias",
    "split_crypto_symbol",
]
