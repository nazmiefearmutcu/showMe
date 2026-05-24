"""MIS — Multi Indicator Scan.

Runs the full 23-indicator weighted consensus from
``showme.engine.consensus.engine.ConsensusEngine`` over an explicit
multi-market universe so the cockpit can surface the highest-conviction
symbols across crypto, equities, FX, commodities, ETFs and bonds in a
single sweep.

MIS is intentionally separate from ``showme.scanner`` (Round-17 ZAK
agent):

* ``showme.scanner`` runs a 3-indicator coarse pass weighted by a
  ZAK timeframe matrix — fast, multi-timeframe, intent-driven.
* MIS runs every indicator the engine exposes on a single configurable
  timeframe per scan with per-market calibration. The trade-off goes
  the other way: more confirmation, narrower TF range.

Calibration lives at ``cache_path("mis_config.json")``. The file is
written via ``atomic_write_json(secure=True)`` so a crash mid-save
cannot corrupt user thresholds. Missing markets fall back to the
defaults baked into this module.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from showme.app_paths import cache_path
from showme.persistence_helpers import atomic_write_json

LOG = logging.getLogger("showme.mis")


# ── Live scan progress ──────────────────────────────────────────────────
# A single, module-level snapshot the route layer reads on every poll. We
# only ever have one MIS scan in flight at a time (the UI gates the
# button), so a global dict is sufficient — no per-scan ID handshake. If
# concurrent scans ever become a thing, swap this for a dict keyed by
# ``scan_id`` and have the POST return the id.
#
# State machine:
#   idle    → no scan has run yet (or last one was cleared)
#   running → scan is mid-flight; ``completed`` ticks up as each symbol
#             finishes all of its TFs
#   done    → scan finished; rows have been returned. UI polls one last
#             time, sees done, stops polling.
#
# All updates flow through ``_progress_update`` so the dict is rebuilt
# atomically (Python's GIL makes dict-replacement effectively atomic for
# read-then-copy from another thread / asyncio task).
_SCAN_PROGRESS: dict[str, Any] = {
    "status": "idle",         # idle | running | done | error
    "total": 0,               # symbols × markets in the active scan
    "completed": 0,           # symbols that finished all their TFs
    "in_flight": 0,           # tasks currently running
    "skipped": 0,             # symbols that errored / hit insufficient bars
    "markets": [],            # markets in this scan
    "started_at": "",         # ISO timestamp when scan kicked off
    "elapsed_ms": 0.0,        # 0 while running, set on done
    "current_symbol": "",     # most recently completed symbol (display)
    "current_market": "",     # market of most recently completed symbol
}

# C12 fix: every read AND every write of ``_SCAN_PROGRESS`` now serialises
# on this lock. Previously ``_progress_update`` mutated the dict without
# the per-scan ``progress_lock``, so an interleaved progress-poll could
# observe a snapshot mid-update (e.g. ``in_flight`` already decremented
# but ``completed`` not yet bumped). Threading.RLock so a single update
# can re-enter from the same thread if needed.
_PROGRESS_LOCK = threading.RLock()


def _progress_update(**fields: Any) -> None:
    """Atomically overlay fields onto the global progress snapshot."""
    with _PROGRESS_LOCK:
        _SCAN_PROGRESS.update(fields)


def get_scan_progress() -> dict[str, Any]:
    """Return a shallow copy of the current progress snapshot — what the
    ``GET /api/mis/scan/progress`` endpoint serves."""
    with _PROGRESS_LOCK:
        snap = dict(_SCAN_PROGRESS)
    total = snap.get("total") or 0
    done = snap.get("completed") or 0
    snap["percent"] = round(100.0 * done / total, 2) if total else 0.0
    return snap

# ── Supported markets ────────────────────────────────────────────────────

MIS_MARKETS: tuple[str, ...] = ("CRYPTO", "EQUITY", "ETF", "FX", "COMMODITY", "BOND")

# ── ZAK (Zaman Dilimi Ağırlık Katsayısı) matrix ─────────────────────────
# Single, unified 12-TF set across ALL markets — same TFs, same ZAK weights.
# Mirrors TBV3 ``bot_service.py`` (see TBV3/src/services/bot_service.py:
# 140-150). Why uniform? Cross-market ranking only stays fair when every
# market has the same upper bound on |weighted_score| and the same TF
# resolution for the consensus. A symbol's final MIS score is the
# weight-normalised sum of its per-TF contributions; if one market gets
# 12 TFs and another only 4, the 12-TF market wins the raw-sum sort
# every time. That's the bug we explicitly fix here.
#
# yfinance (used for EQUITY/ETF/FX/COMMODITY/BOND) natively supports
# 1m, 2m, 5m, 15m, 30m, 1h, 1d, 1wk, 1mo. The five sub-daily TFs that
# CCXT serves natively for crypto — 3m, 4h, 6h, 8h, 12h — are built by
# resampling a coarser supported TF in ``_fetch_ohlcv``. Bonds (^IRX
# etc.) only have daily data through yfinance, so sub-daily TFs will
# resolve to ``insufficient bars`` and contribute zero weight — the
# aggregator already handles that path.
_BASE_TF_WEIGHTS: dict[str, int] = {
    "1m": 8, "3m": 15, "5m": 25, "15m": 38, "30m": 48,
    "1h": 58, "2h": 65, "4h": 75, "6h": 80, "8h": 85,
    "12h": 90, "1d": 95,
}

MARKET_TF_WEIGHTS: dict[str, dict[str, int]] = {
    "CRYPTO": dict(_BASE_TF_WEIGHTS),
    "EQUITY": dict(_BASE_TF_WEIGHTS),
    "ETF": dict(_BASE_TF_WEIGHTS),
    "FX": dict(_BASE_TF_WEIGHTS),
    "COMMODITY": dict(_BASE_TF_WEIGHTS),
    "BOND": dict(_BASE_TF_WEIGHTS),
}

# Resampling rules — for non-crypto markets, these TFs aren't yfinance
# native, so we fetch a coarser supported source TF and downsample via
# pandas. Key = target TF, Value = (source_tf, pandas_resample_rule).
_RESAMPLE_RULES: dict[str, tuple[str, str]] = {
    "3m": ("1m", "3min"),
    "2h": ("1h", "2h"),
    "4h": ("1h", "4h"),
    "6h": ("1h", "6h"),
    "8h": ("1h", "8h"),
    "12h": ("1h", "12h"),
}

# The active TF set per market — same keys, used to control which TFs
# actually fire on each scan. Users can prune in Settings without
# losing the ZAK weights.
MARKET_DEFAULT_TFS: dict[str, list[str]] = {
    m: list(weights.keys()) for m, weights in MARKET_TF_WEIGHTS.items()
}

# Back-compat alias — kept only so older callers / saved presets that
# still send ``timeframes: {market: "4h"}`` work as a single-TF override.
MIS_DEFAULT_TIMEFRAMES: dict[str, str] = {
    "CRYPTO": "4h",
    "EQUITY": "1d",
    "ETF": "1d",
    "FX": "1d",
    "COMMODITY": "1d",
    "BOND": "1d",
}

# Asset-class strings expected by the engine adapters.
_ASSET_CLASS_MAP: dict[str, str] = {
    "CRYPTO": "CRYPTO",
    "EQUITY": "EQUITY",
    "ETF": "ETF",
    "FX": "FX",
    "COMMODITY": "COMMODITY",
    "BOND": "BOND",
}


# ── Universes (curated, expandable via config overrides) ─────────────────
#
# Sizing target: ≥1000 unique symbols across all markets so MIS can act as
# a credible cross-asset breadth scanner. Symbols are deliberately listed
# explicitly (no exchange API call at import time) — keeps boot
# offline-friendly and the universe diffable in PRs. Users can still
# narrow or extend a market via ``universe_override`` in MIS settings.
#
# For CRYPTO the rule is strict: only USDT-quoted spot pairs, and no
# stablecoin bases (filtered in ``_filter_crypto_universe`` so user
# overrides cannot accidentally include them either).

# Tokens that are themselves USD/EUR/gold-pegged stable assets — quoting
# them against USDT is just a flat line, useless for a TA scan. Kept as a
# set of *bases* (the token in front of ``USDT``).
STABLECOIN_BASES: frozenset[str] = frozenset({
    "USDC", "BUSD", "DAI", "TUSD", "FDUSD", "USDP", "GUSD", "FRAX",
    "LUSD", "USDD", "PYUSD", "USDN", "SUSD", "UST", "USTC", "EUR",
    "EURT", "EURS", "EURI", "AEUR", "USDE", "USDS", "USDX", "USDK",
    "USDJ", "USDB", "USDR", "MIM", "OUSD", "ALUSD", "GHO", "CRVUSD",
    "RUSD", "FEI", "TRIBE", "VAI", "DUSD", "MUSD", "XSGD", "BIDR",
    "BVND", "IDRT", "NGN", "TRY", "BRL", "RUB", "UAH", "ZAR", "ARS",
    "VAI", "USTC", "AGEUR", "USDEX", "USDM", "USDF", "USDH", "USDQ",
    "BUIDL", "USYC", "USDY", "PYUSD", "USDO",
})


def _filter_crypto_universe(symbols: list[str]) -> list[str]:
    """Apply MIS crypto rules: USDT-quoted only, no stablecoin bases.

    Deduplicates while preserving first-seen order so the curated list's
    ordering (≈ market-cap rank) survives.
    """
    seen: set[str] = set()
    out: list[str] = []
    for raw in symbols:
        if not isinstance(raw, str):
            continue
        sym = raw.strip().upper()
        if not sym or sym in seen:
            continue
        if not sym.endswith("USDT"):
            continue
        base = sym[:-4]
        if not base or base in STABLECOIN_BASES:
            continue
        seen.add(sym)
        out.append(sym)
    return out


# Top USDT-quoted spot pairs by market-cap / liquidity. Ordered roughly
# by mcap so a ``max_symbols_per_market`` cap keeps the biggest names.
_CRYPTO_RAW: list[str] = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT",
    "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "MATICUSDT", "TONUSDT",
    "TRXUSDT", "LTCUSDT", "BCHUSDT", "SHIBUSDT", "ATOMUSDT", "UNIUSDT",
    "ETCUSDT", "FILUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "NEARUSDT",
    "ICPUSDT", "INJUSDT", "STXUSDT", "VETUSDT", "ALGOUSDT", "HBARUSDT",
    "FTMUSDT", "GRTUSDT", "AAVEUSDT", "SANDUSDT", "MANAUSDT", "AXSUSDT",
    "EGLDUSDT", "THETAUSDT", "EOSUSDT", "XLMUSDT", "RUNEUSDT", "FLOWUSDT",
    "XTZUSDT", "ZECUSDT", "DASHUSDT", "KAVAUSDT", "CHZUSDT", "CRVUSDT",
    "ENJUSDT", "GALAUSDT", "1INCHUSDT", "COMPUSDT", "SNXUSDT", "YFIUSDT",
    "SUSHIUSDT", "BATUSDT", "ZILUSDT", "OMGUSDT", "QTUMUSDT", "ANKRUSDT",
    "IOTAUSDT", "WAVESUSDT", "ICXUSDT", "NEOUSDT", "ZENUSDT", "ONTUSDT",
    "RVNUSDT", "STORJUSDT", "DENTUSDT", "CELRUSDT", "HOTUSDT", "REEFUSDT",
    "CTSIUSDT", "RENUSDT", "BNTUSDT", "DYDXUSDT", "GMTUSDT", "APEUSDT",
    "ENSUSDT", "LDOUSDT", "ROSEUSDT", "WLDUSDT", "PENDLEUSDT", "BLURUSDT",
    "JUPUSDT", "PYTHUSDT", "ORDIUSDT", "SUIUSDT", "SEIUSDT", "TIAUSDT",
    "RNDRUSDT", "FETUSDT", "AGIXUSDT", "OCEANUSDT", "GMXUSDT", "MASKUSDT",
    "CFXUSDT", "FLOKIUSDT", "PEPEUSDT", "BONKUSDT", "WIFUSDT", "JTOUSDT",
    # Layer-1 / Layer-2 extensions
    "KASUSDT", "MNTUSDT", "STRKUSDT", "BLASTUSDT", "MANTAUSDT", "METISUSDT",
    "SCROLLUSDT", "ZKUSDT", "BASEUSDT", "ASTRUSDT", "AURORAUSDT", "GLMRUSDT",
    "MOVRUSDT", "KLAYUSDT", "CELOUSDT", "RONUSDT", "RONINUSDT", "OSMOUSDT",
    "JUNOUSDT", "EVMOSUSDT", "SCRTUSDT", "STARSUSDT", "AKTUSDT", "DYMUSDT",
    "POLYXUSDT", "MINAUSDT", "BEAMUSDT", "TAOUSDT", "TRACUSDT", "LSKUSDT",
    "WAXPUSDT", "ARDRUSDT", "NULSUSDT", "VICUSDT", "TFUELUSDT", "ONEUSDT",
    # DeFi blue chips
    "MKRUSDT", "LRCUSDT", "BALUSDT", "BNTUSDT", "KNCUSDT", "ZRXUSDT",
    "BANDUSDT", "OXTUSDT", "REPUSDT", "UMAUSDT", "RPLUSDT", "FXSUSDT",
    "CVXUSDT", "SPELLUSDT", "PERPUSDT", "ALCXUSDT", "TRUUSDT", "GMXUSDT",
    "JOEUSDT", "QUICKUSDT", "RAYUSDT", "STGUSDT", "BICOUSDT", "RDNTUSDT",
    "HFTUSDT", "EDUUSDT", "IDUSDT", "SSVUSDT", "ETHFIUSDT", "REZUSDT",
    "ZROUSDT", "LISTAUSDT", "OMNIUSDT", "ENAUSDT", "BBUSDT", "WUSDT",
    # NFT / Gaming / Metaverse
    "ILVUSDT", "MAGICUSDT", "PIXELUSDT", "GMRXUSDT", "BIGTIMEUSDT", "ACEUSDT",
    "NFPUSDT", "PORTALUSDT", "AGLDUSDT", "RAREUSDT", "LOOKSUSDT", "DEGOUSDT",
    "DARUSDT", "ALICEUSDT", "TLMUSDT", "HIGHUSDT", "VANRYUSDT", "VOXELUSDT",
    "GHSTUSDT", "MBOXUSDT", "GFTUSDT", "MOBUSDT", "GASUSDT", "BURGERUSDT",
    "RACAUSDT", "SLPUSDT", "YGGUSDT", "ATAUSDT", "REVUUSDT", "LOKAUSDT",
    "MAVUSDT", "HOOKUSDT", "STEEMUSDT", "HIVEUSDT", "TRBUSDT", "DODOUSDT",
    "C98USDT", "CAKEUSDT", "BAKEUSDT", "ALPACAUSDT", "BSWUSDT", "TWTUSDT",
    "JSTUSDT", "SUNUSDT",
    # AI / Data / DePIN
    "RNDRUSDT", "WLDUSDT", "AGIXUSDT", "FETUSDT", "OCEANUSDT", "AIUSDT",
    "ARKMUSDT", "NMRUSDT", "GRTUSDT", "IOTXUSDT", "POWRUSDT", "PHAUSDT",
    "AKROUSDT", "REQUSDT", "TRACUSDT", "TAOUSDT", "VANAUSDT", "TURBOUSDT",
    "MYROUSDT", "BOMEUSDT", "MEMEUSDT", "PEOPLEUSDT", "CTKUSDT", "CTXCUSDT",
    "PROMUSDT", "PHBUSDT", "OAXUSDT", "ORNUSDT", "LITUSDT", "MDTUSDT",
    "DOCKUSDT", "FRONTUSDT", "QIUSDT", "QKCUSDT", "QNTUSDT", "ELFUSDT",
    "ALPHAUSDT", "BETAUSDT", "EPSUSDT", "EPSILONUSDT", "DEXEUSDT", "DFUSDT",
    "DIAUSDT", "DUSKUSDT", "EOTUSDT", "ERNUSDT", "FARMUSDT", "FIDAUSDT",
    "FIROUSDT", "FISUSDT", "FLMUSDT", "FLUXUSDT", "FORTHUSDT", "FUNUSDT",
    "GLMUSDT", "GTCUSDT", "HARDUSDT", "HIFIUSDT", "IDEXUSDT", "IOSTUSDT",
    "IQUSDT", "IRISUSDT", "JASMYUSDT", "KEYUSDT", "KMDUSDT", "KP3RUSDT",
    "KSMUSDT", "LAZIOUSDT", "LEVERUSDT", "LINAUSDT", "LOOMUSDT", "LPTUSDT",
    "LQTYUSDT", "MBLUSDT", "MLNUSDT", "MTLUSDT", "NEXOUSDT", "NKNUSDT",
    "NTRNUSDT", "OGNUSDT", "OMUSDT", "ONGUSDT", "OPUSDT", "OXTUSDT",
    "PAXGUSDT", "PERPUSDT", "PIVXUSDT", "PNTUSDT", "POLSUSDT", "PONDUSDT",
    "PORTOUSDT", "PROSUSDT", "PSGUSDT", "PUNDIXUSDT", "PYRUSDT", "RADUSDT",
    "RIFUSDT", "RLCUSDT", "SANTOSUSDT", "SCUSDT", "SFPUSDT", "SKLUSDT",
    "SPELLUSDT", "STMXUSDT", "STPTUSDT", "STRAXUSDT", "SUPERUSDT", "SXPUSDT",
    "SYNUSDT", "SYSUSDT", "TKOUSDT", "TNSRUSDT", "TROYUSDT", "TVKUSDT",
    "UFTUSDT", "UNFIUSDT", "UTKUSDT", "VGXUSDT", "VIBUSDT", "VIDTUSDT",
    "VITEUSDT", "VTHOUSDT", "WANUSDT", "WINUSDT", "WNXMUSDT", "WRXUSDT",
    "WTCUSDT", "XECUSDT", "XEMUSDT", "XMRUSDT", "XNOUSDT", "XVGUSDT",
    "XVSUSDT", "XYMUSDT", "ACMUSDT", "ADXUSDT", "AERGOUSDT", "AMBUSDT",
    "AMPUSDT", "ARKUSDT", "ARPAUSDT", "ASRUSDT", "ATMUSDT", "AUCTIONUSDT",
    "AUDIOUSDT", "AVAUSDT", "BELUSDT", "BIFIUSDT", "BLZUSDT", "BNXUSDT",
    "CHESSUSDT", "CHRUSDT", "CITYUSDT", "CLVUSDT", "COSUSDT", "COTIUSDT",
    "CREAMUSDT", "CVCUSDT", "CVPUSDT", "CYBERUSDT", "DATAUSDT",
    # Memecoin majors (filtered to keep only liquid USDT pairs)
    "BRETTUSDT", "POPCATUSDT", "MEWUSDT", "WIFUSDT", "BOMEUSDT", "TURBOUSDT",
    "MOGUSDT", "GIGAUSDT", "BANANAUSDT", "BABYDOGEUSDT", "NEIROUSDT",
    "DOGSUSDT", "CATIUSDT", "HMSTRUSDT", "NOTUSDT", "PEIPEIUSDT", "PEPECOINUSDT",
    "DOGUSDT", "PUFFERUSDT", "TONUSDT",
]

# S&P 500 + Nasdaq 100 + key liquid mid-caps & ADRs — deduped at filter
# time. Ordering: mega-caps first so any cap takes the top.
_EQUITY_RAW: list[str] = [
    # Mega caps
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA", "AVGO",
    "BRK-B", "JPM", "JNJ", "V", "MA", "UNH", "WMT", "PG", "HD", "XOM",
    "CVX", "ABBV", "BAC", "KO", "PEP", "MRK", "LLY", "TMO", "COST", "ORCL",
    "ADBE", "CSCO", "ACN", "PFE", "NFLX", "INTC", "AMD", "QCOM", "WFC",
    "DIS", "NKE", "MCD", "DHR", "TXN", "VZ", "T", "INTU", "AMGN", "CRM",
    # Industrials / Defense / Transport
    "PM", "UPS", "RTX", "HON", "BA", "LOW", "IBM", "CAT", "GS", "AXP",
    "SCHW", "MS", "BLK", "C", "USB", "PNC", "TFC", "SPGI", "MMM", "DE",
    "GE", "F", "GM", "FDX", "TGT", "BKNG", "ABT", "MDT", "LIN", "GILD",
    "LMT", "NOC", "GD", "HII", "TDG", "TXT", "LHX", "HEI", "AVAV", "KTOS",
    "ETN", "EMR", "PH", "ITW", "ROK", "DOV", "SWK", "FAST", "PCAR", "CMI",
    "URI", "WAB", "OSK", "PWR", "GNRC", "AOS", "SNA", "RBC", "JCI", "TT",
    # Healthcare / Biotech
    "BMY", "ELV", "CI", "CVS", "HUM", "ZTS", "REGN", "VRTX", "BIIB",
    "ISRG", "SYK", "BSX", "MDLZ", "MO", "PYPL", "SBUX", "EBAY", "ETSY",
    "MCK", "CAH", "ABC", "HCA", "DGX", "LH", "IDXX", "ALGN", "EXAS",
    "TDOC", "BAX", "BDX", "BMRN", "INCY", "ALNY", "MRNA", "BNTX", "GILD",
    "CRSP", "EDIT", "NTLA", "BEAM", "ARWR", "IONS", "EXEL", "ILMN", "RGEN",
    "VTRS", "TEVA", "PRGO", "JAZZ", "HRMY", "MASI", "GH", "NTRA", "ARGX",
    "VFC", "GH", "DXCM", "PODD", "TMDX", "DOC", "WELL", "VTR", "OHI",
    "HOLX", "WAT", "MTD", "ICLR", "IQV", "CRL", "A", "TFX", "RVTY", "BIO",
    # Tech / Software
    "ROKU", "SHOP", "SQ", "ZM", "DOCU", "TWLO", "CRWD", "PANW", "NET",
    "DDOG", "SNOW", "PLTR", "DELL", "HPQ", "STX", "WDC", "MU", "ADSK",
    "LRCX", "AMAT", "KLAC", "SNPS", "CDNS", "MRVL", "ON", "MCHP", "ASML",
    "TSM", "JD", "BABA", "BIDU", "NIO", "XPEV", "LI", "PDD", "BILI",
    "TCOM", "GRAB", "SE", "MELI", "GLOB", "MSCI", "ICE", "CME", "NDAQ",
    "ADYEY", "SPLK", "NOW", "WDAY", "ZS", "OKTA", "MDB", "TEAM", "ATLR",
    "TYL", "PCTY", "PAYC", "EPAM", "GTLB", "ESTC", "MNDY", "ZI", "CFLT",
    "S", "AI", "SOUN", "PATH", "BILL", "HUBS", "DOCN", "FROG", "DT", "VEEV",
    "ZBRA", "NTNX", "JNPR", "FFIV", "FTNT", "CHKP", "ANSS", "FICO", "PTC",
    "AKAM", "VRSN", "VRSK", "WTW", "MORN", "FIS", "FISV", "JKHY", "BR",
    "GPN", "ADP", "WEX", "EFX", "RHI", "PAYX", "MA", "V", "DFS", "COF",
    # Financial Services
    "MMC", "AON", "PRU", "MET", "ALL", "PGR", "TRV", "AIG", "AFL", "HIG",
    "WBA", "DVA", "WELL", "PEAK", "ARE", "AVB", "EQR", "ESS", "MAA", "UDR",
    "ALSN", "BIRD", "WTW", "BRO", "ERIE", "CINF", "GL", "WRB", "RGA",
    "PFG", "AMP", "CG", "OWL", "TROW", "BEN", "IVZ", "STT", "NTRS", "BK",
    "RJF", "LPLA", "JEF", "EVR", "MKTX", "TW", "VIRT", "CBOE", "MOH",
    # Pharma / Medical Devices
    "ABT", "TMO", "DHR", "EW", "PODD", "DXCM", "RMD", "ZBH", "HOLX", "ALGN",
    "BAX", "BDX", "COO", "WAT", "TFX", "ICUI", "STE", "MTD", "RHHBY", "NVS",
    # Consumer (Disc + Staples)
    "NKE", "LULU", "TPR", "CPRI", "DECK", "RL", "LEVI", "GAP", "URBN", "ANF",
    "ROST", "TJX", "BURL", "DLTR", "DG", "FIVE", "OLLI", "WSM", "RH", "Z",
    "LEN", "DHI", "PHM", "NVR", "TOL", "KBH", "MTH", "TMHC", "TPH", "MDC",
    "HRB", "INTU", "PYPL", "AFRM", "SQ", "MGM", "WYNN", "LVS", "CZR", "DKNG",
    "PENN", "CHDN", "RCL", "CCL", "NCLH", "UAL", "DAL", "LUV", "AAL", "ALK",
    "ALGT", "JBLU", "HA", "SKY", "EXPE", "ABNB", "TRIP", "BKNG", "TCOM",
    "MAR", "HLT", "H", "IHG", "WH", "CHH", "BEKE", "RDFN", "Z", "OPEN",
    "EL", "CL", "CHD", "CLX", "KMB", "GIS", "K", "POST", "SJM", "CAG",
    "CPB", "HRL", "HSY", "MKC", "MNST", "STZ", "TAP", "BUD", "DEO", "BTI",
    "MO", "PM", "KHC", "MDLZ", "TSN", "ADM", "BG", "ANDE", "DOLE", "PPC",
    "WMT", "TGT", "COST", "BJ", "ACI", "KR", "SFM", "SAM", "BREW",
    # Energy / Mining
    "RIVN", "LCID", "NIO", "FCEL", "PLUG", "FSLR", "ENPH", "SEDG", "RUN",
    "BE", "BLDP", "NEE", "DUK", "SO", "AEP", "EXC", "XEL", "SRE", "ED",
    "EIX", "PCG", "PEG", "WEC", "ES", "DTE", "ETR", "AEE", "FE", "CMS",
    "CNP", "AES", "NRG", "EOG", "PXD", "OXY", "FANG", "DVN", "MRO", "APA",
    "HES", "MPC", "VLO", "PSX", "TRGP", "KMI", "WMB", "OKE", "ENB", "TRP",
    "SLB", "HAL", "BKR", "NOV", "FTI", "CHX", "EQT", "AR", "CTRA", "MUR",
    "OVV", "PR", "MTDR", "RRC", "MGY", "CRC", "SM", "VNOM", "DINO", "DK",
    "HFC", "PBF", "DKL", "ENBL", "ENLC", "EPD", "ET", "PAA", "PAGP", "MMP",
    "FCX", "NEM", "GOLD", "AEM", "AU", "BTG", "EGO", "HMY", "KGC", "PAAS",
    "WPM", "FNV", "SCCO", "TECK", "RIO", "BHP", "VALE", "MOS", "NTR", "CF",
    # Materials / Chemicals
    "DOW", "DD", "LYB", "EMN", "ALB", "ASH", "SHW", "PPG", "RPM", "AXTA",
    "ECL", "VMC", "MLM", "USG", "FUL", "OLN", "WLK", "CE", "IFF", "NEM",
    "STLD", "NUE", "CMC", "MT", "X", "CLF", "AA", "RYI", "RS", "WOR",
    # Utilities / REITs
    "AMT", "PLD", "EQIX", "PSA", "CCI", "WELL", "DLR", "O", "SBAC", "VICI",
    "EQR", "AVB", "ESS", "MAA", "UDR", "INVH", "AMH", "EXR", "CUBE", "LSI",
    "PEAK", "VTR", "OHI", "DOC", "VTR", "MPW", "HR", "CTRE", "SBRA", "NHI",
    "IRM", "EXR", "PSA", "BXP", "VNO", "ARE", "KIM", "REG", "FRT", "MAC",
    # Communications / Media
    "TMUS", "VZ", "T", "CHTR", "CMCSA", "DIS", "PARA", "FOX", "FOXA", "WBD",
    "NWS", "NWSA", "NYT", "GCI", "SIRI", "LBRDA", "LBRDK", "DISH", "USM",
    "VTRS", "PG", "CHD", "CLX",
    # Defense / Aerospace
    "LMT", "NOC", "GD", "RTX", "BA", "HEI", "TDG", "TXT", "LHX", "HII",
    "AVAV", "KTOS", "MRCY", "BWXT", "VOR", "VLO", "WLK", "RKLB", "JOBY",
    # ADRs / International
    "TSM", "ASML", "NVO", "AZN", "GSK", "SAP", "TM", "HMC", "SONY", "STLA",
    "RACE", "BABA", "JD", "PDD", "NTES", "BIDU", "TME", "VIPS", "YUMC",
    "TCOM", "BILI", "WB", "IQ", "ZTO", "CYBR", "WIX", "MNDY", "GLOB",
    "BRBR", "CVA", "MELI", "AVGO", "TSEM", "NICE", "CHKP", "RNGR", "TLRY",
    "ACB", "CRON", "CGC", "HEXO", "OGI", "BHC", "MFC", "TD", "BMO", "BNS",
    "RY", "CNQ", "ENB", "TRP", "SU", "CVE", "MGA", "OTEX", "CSU", "ABX",
    "AEM", "GOLD", "BTG", "EGO", "KGC", "PAAS", "WPM", "FNV", "ABBV",
    # Renewable & EV
    "TSLA", "F", "GM", "STLA", "RACE", "RIVN", "LCID", "NIO", "XPEV", "LI",
    "PSNY", "BLNK", "EVGO", "CHPT", "QS", "BWXT", "ENPH", "SEDG", "RUN",
    "FSLR", "ARRY", "JKS", "CSIQ", "SOL", "DQ", "BE", "PLUG", "FCEL",
    "BLDP", "SHLS", "MAXN", "NOVA", "ALEN", "DTE", "NEE", "DUK", "AEP",
    # Misc / Diversified
    "AMZN", "META", "GOOGL", "GOOG", "NFLX", "DIS", "AAPL", "MSFT", "NVDA",
    "AMD", "TSLA", "ORCL", "CRM", "IBM", "INTC", "ADBE", "PYPL", "SHOP",
    "PLTR", "SNOW", "DDOG", "MDB", "NET", "CRWD", "ZS", "PANW", "OKTA",
    # Growth / Recent IPOs
    "ABNB", "DASH", "UBER", "LYFT", "DOORDASH", "RIVN", "COIN", "HOOD",
    "AFRM", "UPST", "SOFI", "MARA", "RIOT", "BITF", "HUT", "BTBT", "CIFR",
    "WULF", "CLSK", "IREN", "GREE", "ARBE", "MQ", "DLO", "PAGS", "STNE",
    # Active small-mid liquid names
    "MARA", "RIOT", "COIN", "HOOD", "SOFI", "AFRM", "UPST", "OPEN", "RDFN",
    "WISH", "BB", "GME", "AMC", "AMR", "CVNA", "FUBO", "ROKU", "MGNI",
    "DASH", "ABNB", "U", "NCNO", "ESTC", "GTLB", "MNDY", "DOCS", "PCOR",
    "SMAR", "ZI", "ZUO", "AYX", "DOCN", "FROG", "PATH", "AI", "BBAI",
    "RBLX", "SE", "MELI", "GLOB", "TASK", "DAVA", "DAVE", "JFIN", "EH",
    "DUOL", "GTLB", "ASAN", "OLO", "OLPX", "POSH", "PRCT", "SGHT", "INSP",
    "TENB", "RPD", "QLYS", "VRNS", "SPLK", "DT", "DDOG", "NEWR", "ESTC",
    "AUR", "EHC", "TXG", "ARGX", "VIR", "SAGE", "BLUE", "BHVN", "PRTA",
    "SRPT", "RARE", "ICPT", "DNLI", "PCRX", "AKRO", "VKTX", "MIRM",
    # ── Round 2 expansion ────────────────────────────────────────────────
    # S&P 500 fill-out (members not already listed above)
    "ABMD", "ACGL", "AEE", "AEP", "AES", "AFL", "AFRM", "AIZ", "AJG", "AKAM",
    "ALB", "ALK", "ALLE", "AMCR", "AME", "AMP", "ANET", "ANSS", "AOS", "APA",
    "APD", "APH", "APTV", "ARE", "ATO", "AVB", "AVY", "AWK", "AXP", "AZO",
    "BALL", "BAX", "BBWI", "BBY", "BEN", "BF-A", "BF-B", "BG", "BIO", "BKR",
    "BLDR", "BLL", "BR", "BRO", "BWA", "CAG", "CAH", "CARR", "CB", "CBOE",
    "CBRE", "CCI", "CCL", "CDAY", "CDW", "CE", "CEG", "CF", "CHRW", "CHTR",
    "CINF", "CLX", "CMA", "CMG", "CMS", "CNC", "CNP", "COF", "COO", "COP",
    "CPB", "CPRT", "CPT", "CRL", "CSGP", "CSX", "CTAS", "CTLT", "CTSH", "CTVA",
    "CZR", "D", "DAL", "DAY", "DECK", "DFS", "DGX", "DHI", "DLR", "DOV",
    "DPZ", "DRI", "DTE", "DUK", "DVA", "DVN", "EA", "EBAY", "ECL", "ED",
    "EFX", "EG", "EIX", "EL", "EMN", "EMR", "ENPH", "EOG", "EPAM", "EQT",
    "ES", "ESS", "ETN", "ETR", "ETSY", "EVRG", "EW", "EXC", "EXPD", "EXR",
    "FANG", "FAST", "FCX", "FDS", "FE", "FFIV", "FI", "FICO", "FITB", "FMC",
    "FOX", "FOXA", "FRT", "FSLR", "FTV", "GEHC", "GEN", "GEV", "GIS", "GL",
    "GLW", "GNRC", "GPC", "GPN", "GRMN", "GWW", "HAL", "HAS", "HBAN", "HCA",
    "HD", "HES", "HIG", "HII", "HOLX", "HPE", "HPQ", "HRL", "HSIC", "HST",
    "HSY", "HUBB", "HUM", "IDXX", "IEX", "IFF", "INVH", "IP", "IPG", "IQV",
    "IR", "IRM", "IT", "IVZ", "J", "JBHT", "JBL", "JCI", "JKHY", "JNPR",
    "K", "KDP", "KEY", "KEYS", "KHC", "KIM", "KLAC", "KMB", "KMI", "KMX",
    "KO", "KR", "KVUE", "L", "LDOS", "LEN", "LH", "LIN", "LKQ", "LMT",
    "LNT", "LULU", "LUV", "LVS", "LW", "LYV", "MAA", "MAS", "MCO", "MGM",
    "MHK", "MKC", "MLM", "MMC", "MNST", "MOH", "MOS", "MPC", "MPWR", "MRO",
    "MTB", "MTCH", "MTD", "NCLH", "NDSN", "NEE", "NEM", "NI", "NKE", "NOC",
    "NRG", "NSC", "NTAP", "NTRS", "NUE", "NVR", "NWL", "NWS", "NWSA", "NXPI",
    "O", "ODFL", "OMC", "OXY", "PARA", "PAYX", "PCAR", "PCG", "PEG", "PEP",
    "PFE", "PFG", "PG", "PGR", "PH", "PHM", "PKG", "PLD", "PNR", "PNW",
    "POOL", "PPG", "PPL", "PRU", "PSA", "PSX", "PTC", "PWR", "QRVO", "RCL",
    "RE", "REG", "RF", "RJF", "RL", "RMD", "ROK", "ROL", "ROP", "ROST",
    "RSG", "RTX", "SBAC", "SBUX", "SCHW", "SHW", "SJM", "SLG", "SMCI", "SNA",
    "SO", "SOLV", "SPG", "STE", "STLD", "STT", "STX", "STZ", "SWK", "SWKS",
    "SYF", "SYK", "SYY", "TAP", "TDG", "TDY", "TECH", "TEL", "TER", "TFC",
    "TFX", "TGT", "TJX", "TMUS", "TPR", "TRGP", "TRMB", "TROW", "TRV", "TSCO",
    "TSN", "TT", "TTWO", "TXN", "TXT", "TYL", "UAL", "UBER", "UDR", "UHS",
    "ULTA", "UNH", "UNP", "URI", "VICI", "VLO", "VMC", "VNO", "VRSN", "VRTX",
    "VTR", "VTRS", "WAB", "WAT", "WBA", "WBD", "WDC", "WEC", "WFC", "WHR",
    "WM", "WMB", "WMT", "WRB", "WRK", "WST", "WTW", "WY", "WYNN", "XEL",
    "XOM", "XYL", "YUM", "ZBH", "ZBRA", "ZTS",
    # Russell 1000 mid-caps (ex-S&P 500)
    "AAP", "AAOI", "ACA", "ACAD", "ACHC", "ACIW", "ACLS", "ACM", "ADC", "ADNT",
    "ADTN", "AEIS", "AGCO", "AGI", "AGIO", "AGNC", "AGO", "AIN", "AIR", "AIT",
    "AIV", "AKR", "AL", "ALE", "ALGM", "ALKS", "ALRM", "ALSN", "ALV", "AM",
    "AMBA", "AMCX", "AMG", "AMKR", "AMN", "AMRC", "AMSC", "AN", "ANDE", "ANIK",
    "AOSL", "APAM", "APLE", "APLS", "APOG", "APPF", "APPN", "AR", "ARCB", "ARCH",
    "ARES", "ARMK", "AROC", "ARRY", "ARW", "ASB", "ASGN", "ASIX", "ASO", "ASR",
    "ASTL", "ASUR", "ATEN", "ATGE", "ATI", "ATKR", "ATR", "ATRC", "ATSG", "AUB",
    "AVA", "AVNT", "AVNS", "AVNW", "AVPT", "AVT", "AX", "AXNX", "AXS", "AYI",
    "AYR", "AZN", "AZTA", "AZZ", "B", "BAH", "BANC", "BANR", "BBSI", "BC",
    "BCC", "BCO", "BCRX", "BDC", "BDN", "BE", "BECN", "BEEM", "BEKE", "BERY",
    "BFAM", "BFC", "BFH", "BFS", "BG", "BGS", "BH", "BHE", "BHF", "BHLB",
    "BIG", "BIPC", "BJ", "BJRI", "BKE", "BKH", "BKU", "BL", "BLBD", "BLD",
    "BLKB", "BLMN", "BLNK", "BMI", "BMRC", "BMRN", "BMTC", "BNL", "BOH", "BOOT",
    "BPMC", "BPOP", "BRC", "BRKL", "BRP", "BRX", "BSY", "BTU", "BUSE", "BV",
    "BVH", "BXMT", "BXP", "BY", "BYD", "CABO", "CADE", "CAKE", "CAL", "CALM",
    "CALX", "CAMP", "CARS", "CARG", "CASH", "CASS", "CASY", "CATY", "CBL", "CBT",
    "CBU", "CBZ", "CC", "CCBG", "CCK", "CCO", "CCOI", "CCS", "CDLX", "CDMO",
    "CDNA", "CDP", "CEIX", "CELC", "CENT", "CENTA", "CENX", "CERS", "CERT", "CEVA",
    "CFFI", "CFFN", "CGNX", "CHCO", "CHCT", "CHD", "CHE", "CHEF", "CHGG", "CHH",
    "CHX", "CIEN", "CIO", "CIR", "CIVB", "CIVI", "CLBK", "CLNE", "CMBM", "CMC",
    "CMCO", "CMP", "CMPR", "CMTL", "CNDT", "CNK", "CNM", "CNO", "CNOB", "CNS",
    "CNX", "CNXC", "COKE", "COLD", "COLM", "COMM", "CON", "COOP", "COR", "CORT",
    "COTY", "COUR", "CPA", "CPF", "CPK", "CPK", "CPNG", "CPRX", "CRBG", "CRC",
    "CRGY", "CRI", "CRK", "CRMT", "CRNC", "CROX", "CRS", "CRSR", "CRUS", "CRVL",
    "CRY", "CSGS", "CSII", "CSL", "CSR", "CSTM", "CSWI", "CTBI", "CTRE", "CTRN",
    "CTS", "CUBE", "CUBI", "CUZ", "CVBF", "CVCO", "CVI", "CWBC", "CWEN", "CWH",
    "CWST", "CWT", "CXM", "CXW", "CYH", "CYTK", "CZNC", "CZWI", "DAN", "DBI",
    "DBRG", "DCO", "DCOM", "DD", "DDS", "DEA", "DEI", "DEL", "DERM", "DGII",
    "DGICA", "DHC", "DHIL", "DHT", "DIN", "DIOD", "DJCO", "DK", "DKL", "DKS",
    "DLB", "DLX", "DM", "DNB", "DNN", "DNOW", "DOC", "DOLE", "DOMO", "DORM",
    "DOX", "DRH", "DRI", "DRQ", "DRRX", "DRVN", "DSGR", "DSP", "DTM", "DV",
    "DVAX", "DXC", "DXLG", "DXPE", "DY", "DYAI", "DYN", "EAF", "EAT", "EB",
    "EBC", "EBF", "EBIX", "EBR", "EBS", "ECPG", "ECVT", "EE", "EEFT", "EEX",
    "EFC", "EFSC", "EGBN", "EGHT", "EGP", "EHTH", "ELME", "ELS", "ELV", "EME",
    "ENDP", "ENS", "ENV", "ENVA", "EOLS", "EPC", "EPRT", "EQC", "ERIE", "ERII",
    "ESE", "ESGR", "ESI", "ESMT", "ESNT", "ESRT", "EVBG", "EVC", "EVH", "EVR",
    "EVRI", "EVTC", "EWBC", "EXLS", "EXP", "EXPI", "EXPO", "EXTR", "EYE", "EZPW",
    "FA", "FAF", "FATE", "FBNC", "FBP", "FBRT", "FCBC", "FCEL", "FCF", "FCFS",
    "FCN", "FDP", "FELE", "FFBC", "FFIN", "FG", "FHB", "FHN", "FIBK", "FIVN",
    "FIX", "FIZZ", "FL", "FLGT", "FLO", "FLOC", "FLS", "FLWS", "FLYW", "FMBH",
    "FMC", "FN", "FNB", "FOLD", "FOR", "FORM", "FORR", "FOXF", "FRBA", "FRG",
    "FRHC", "FRME", "FROG", "FRPT", "FRSH", "FSP", "FSR", "FSS", "FTAI", "FTDR",
    "FTI", "FTRE", "FUL", "FULT", "FUN", "FVRR", "FWRD", "FWRG", "FYBR", "G",
    "GBCI", "GBDC", "GBX", "GCO", "GDOT", "GEF", "GEO", "GERN", "GES", "GFF",
    "GFL", "GH", "GHC", "GIII", "GKOS", "GLOG", "GLP", "GLPI", "GLT", "GLW",
    "GMED", "GMRE", "GNK", "GNL", "GNTX", "GO", "GOGL", "GOGO", "GOOS", "GPI",
    "GPK", "GRBK", "GRC", "GS", "GSAT", "GSBC", "GSHD", "GT", "GTES", "GTLS",
    "GTY", "GVA", "GWRE", "GWW", "GXO", "H", "HA", "HAE", "HAFC", "HALO",
    "HAYW", "HBIO", "HBNC", "HCAT", "HCC", "HCKT", "HCSG", "HE", "HEAR", "HEES",
    "HEI", "HELE", "HFFG", "HFWA", "HGV", "HHC", "HI", "HIBB", "HIMS", "HIW",
    "HL", "HLI", "HLIT", "HLT", "HMN", "HNI", "HNST", "HOG", "HOMB", "HOPE",
    "HP", "HPP", "HQY", "HR", "HRMY", "HSDT", "HSII", "HSKA", "HSTM", "HTBI",
    "HTH", "HUBG", "HURN", "HWC", "HWKN", "HXL", "HZO", "I", "IART", "IBKR",
    "IBM", "IBOC", "IBP", "IBRX", "IBTX", "ICFI", "ICHR", "ICL", "ICUI", "IDA",
    "IDCC", "IDT", "IESC", "IGT", "IIIN", "IIIV", "INBK", "INDB", "INFN", "INGN",
    "INMD", "INO", "INSM", "INSW", "INT", "INVA", "INVE", "IOSP", "IOVA", "IPAR",
    "IPGP", "IPI", "IRDM", "IRT", "IRTC", "ISTR", "ITGR", "ITRI", "ITT", "IVR",
    "IVT", "JACK", "JAMF", "JAZZ", "JBLU", "JBSS", "JBT", "JEF", "JELD", "JJSF",
    "JMP", "JNCE", "JOE", "JOUT", "JWN", "JXN", "KAI", "KAR", "KBH", "KE",
    "KELYA", "KEX", "KFRC", "KFY", "KMPR", "KMT", "KN", "KNF", "KNL", "KNTK",
    "KOP", "KOS", "KPLT", "KRG", "KRO", "KRYS", "KSS", "KTB", "KTOS", "KTOS",
    "KURA", "KW", "KWR", "LADR", "LANC", "LAUR", "LAZ", "LAZR", "LBAI", "LBC",
    "LCII", "LCNB", "LEA", "LEG", "LFG", "LFST", "LGF-A", "LGF-B", "LGIH", "LGND",
    "LHX", "LILA", "LILAK", "LITE", "LIVN", "LKFN", "LL", "LMAT", "LMND", "LNC",
    "LNN", "LOB", "LOCO", "LOPE", "LPG", "LPLA", "LPRO", "LPSN", "LPX", "LRCX",
    "LRN", "LSEA", "LSXMA", "LSXMK", "LTC", "LTH", "LTRPA", "LU", "LUMN", "LXFR",
    "LXP", "LXU", "LYEL", "LYFT", "LYTS", "M", "MAIN", "MAN", "MANT", "MAR",
    "MATV", "MATW", "MATX", "MAXR", "MBC", "MBI", "MBIN", "MBUU", "MC", "MCB",
    "MCBC", "MCFT", "MCRI", "MCS", "MD", "MDC", "MDGL", "MDP", "MDU", "MDXG",
    "MED", "MEI", "MERC", "MERIT", "MFA", "MGEE", "MGNI", "MGRC", "MGY", "MHO",
    "MIDD", "MIN", "MIR", "MITK", "MKL", "MKSI", "MKTX", "MLAB", "MLI", "MLM",
    "MLR", "MMI", "MMS", "MMSI", "MNK", "MNRO", "MNST", "MOB", "MOG-A", "MOG-B",
    "MOV", "MP", "MPB", "MPLN", "MPLX", "MRCY", "MRTN", "MS", "MSA", "MSEX",
    "MSGE", "MSGS", "MSI", "MSM", "MTDR", "MTG", "MTH", "MTN", "MTOR", "MTRN",
    "MTSI", "MTUS", "MTX", "MTZ", "MUR", "MUSA", "MWA", "MX", "MXL", "MYE",
    "MYGN", "MYRG", "NAPA", "NARI", "NAT", "NATH", "NATI", "NATR", "NAVI", "NBHC",
    "NBN", "NBR", "NBTB", "NCI", "NCMI", "NCNO", "NCR", "NDLS", "NEO", "NEOG",
    "NEP", "NEU", "NEWT", "NFG", "NGD", "NGL", "NGVT", "NHC", "NHI", "NJR",
    "NKLA", "NL", "NMIH", "NMRK", "NN", "NNI", "NOG", "NOMD", "NP", "NPK",
    "NPO", "NR", "NSA", "NSIT", "NSP", "NTB", "NTCT", "NTGR", "NTLA", "NUS",
    "NUVA", "NVAX", "NVCR", "NVEC", "NVEE", "NWBI", "NWE", "NWN", "NX", "NXGN",
    "NXST", "NYCB", "NYMT", "NYT", "OAS", "OBE", "OBK", "OCFC", "OCN", "OCSL",
    "OCUL", "ODP", "OEC", "OFG", "OFIX", "OFLX", "OGE", "OGN", "OGS", "OI",
    "OII", "OIS", "OLED", "OLN", "OLPX", "OMI", "OMP", "ONB", "ONEW", "ONTF",
    "ONTO", "OPCH", "OPRT", "OPRX", "OPY", "ORA", "ORC", "ORCC", "ORI", "ORN",
    "ORRF", "OSCR", "OSIS", "OSK", "OSPN", "OTTR", "OUT", "OXM", "OZK", "PACB",
    "PACK", "PAG", "PAGS", "PAHC", "PAR", "PARR", "PATK", "PAYO", "PBA", "PBH",
    "PCH", "PCRX", "PCT", "PD", "PDCO", "PDFS", "PDM", "PEB", "PEN", "PFBC",
    "PFC", "PFGC", "PFS", "PFSI", "PGNY", "PGRE", "PHIN", "PHM", "PHR", "PI",
    "PII", "PINC", "PINS", "PIPR", "PJT", "PK", "PLAB", "PLAY", "PLBC", "PLCE",
    "PLMR", "PLNT", "PLOW", "PLPC", "PLRX", "PLSE", "PLTK", "PLUS", "PLXS",
    "PLYM", "PMT", "PNFP", "PNM", "PNTG", "PODD", "POOL", "POR", "POST", "POWI",
    "POWL", "PPBI", "PPC", "PR", "PRA", "PRAA", "PRDO", "PRFT", "PRG", "PRGO",
    "PRGS", "PRI", "PRIM", "PRK", "PRLB", "PRMW", "PRO", "PRPL", "PRTY", "PRVA",
    "PSB", "PSEC", "PSMT", "PSN", "PSTG", "PSTL", "PTCT", "PTGX", "PTON", "PTSI",
    "PTVE", "PUMP", "PVH", "PWP", "PWSC", "PWUP", "PX", "PYCR", "PZZA", "QCRH",
    "QDEL", "QGEN", "QLYS", "QNST", "QRTEA", "QRTEB", "QTRX", "QTWO", "QURE",
    "R", "RAMP", "RBA", "RBB", "RBC", "RBCAA", "RC", "RCKT", "RCM", "RCMT",
    "RCUS", "RDFN", "RDN", "RDWR", "REAL", "REI", "REPL", "REPX", "REX", "REXR",
    "REYN", "RGA", "RGEN", "RGLD", "RGNX", "RGP", "RGR", "RH", "RHI", "RICK",
    "RILY", "RIOT", "RKLB", "RKT", "RLAY", "RLI", "RLJ", "RLMD", "RLX", "RMAX",
    "RMBS", "RMD", "RMR", "RNG", "RNST", "ROCK", "ROG", "ROIC", "ROIV", "ROL",
    "RPAY", "RPD", "RPM", "RRBI", "RRGB", "RRR", "RRX", "RSI", "RTL", "RTLR",
    "RUSHA", "RUSHB", "RUTH", "RVMD", "RVT", "RWT", "RXO", "RXT", "RYAM", "RYAN",
    "RYI", "RYN", "S", "SABR", "SAFE", "SAFM", "SAFT", "SAH", "SAIA", "SAIC",
    "SAM", "SAMG", "SANA", "SANM", "SASR", "SATS", "SAVE", "SBCF", "SBGI", "SBH",
    "SBLK", "SBR", "SBSI", "SBT", "SCCO", "SCHL", "SCI", "SCL", "SCSC", "SCVL",
    "SDGR", "SEAS", "SEDG", "SEE", "SEM", "SEMR", "SERV", "SF", "SFBS", "SFE",
    "SFL", "SFM", "SFNC", "SGA", "SGH", "SGRY", "SHAK", "SHC", "SHEN", "SHO",
    "SHOO", "SHYF", "SIBN", "SIEB", "SIG", "SIGI", "SIRI", "SITC", "SITE", "SIX",
    "SJW", "SKT", "SKYW", "SLAB", "SLG", "SLGN", "SLM", "SLNO", "SLP", "SLVM",
    "SM", "SMBC", "SMBK", "SMG", "SMHI", "SMP", "SMPL", "SMRT", "SMTC", "SNBR",
    "SNCY", "SNDR", "SNDX", "SNFCA", "SNV", "SNX", "SOI", "SON", "SP", "SPB",
    "SPHR", "SPNT", "SPNS", "SPOK", "SPSC", "SPT", "SPTN", "SPWH", "SR", "SRCE",
    "SRDX", "SRE", "SRG", "SRPT", "SSB", "SSD", "SSP", "SSTI", "SSTK", "ST",
    "STAA", "STAG", "STBA", "STC", "STEL", "STEM", "STEP", "STER", "STGW", "STKL",
    "STN", "STNE", "STR", "STRA", "STRL", "STT", "SUM", "SUN", "SUPN", "SUPR",
    "SVC", "SVRA", "SWAV", "SWBI", "SWI", "SWIM", "SWX", "SXC", "SXI", "SXT",
    "SYBT", "SYNA", "SYRS", "TALO", "TARS", "TBBK", "TBI", "TBPH", "TCBI", "TCBK",
    "TCS", "TDC", "TDS", "TDW", "TENB", "TFIN", "TFSL", "TGEN", "TGI", "TGNA",
    "TGTX", "TH", "THC", "THFF", "THG", "THO", "THR", "THRM", "THRY", "THS",
    "TILE", "TIPT", "TISI", "TJX", "TK", "TKR", "TLS", "TMDX", "TMHC", "TMP",
    "TMUS", "TNC", "TNDM", "TNET", "TNK", "TNL", "TNXP", "TOL", "TPC", "TPG",
    "TPH", "TPIC", "TPR", "TPX", "TR", "TRC", "TREE", "TREX", "TRIP", "TRMB",
    "TRMK", "TRN", "TRNO", "TRNS", "TROX", "TRS", "TRTN", "TRTX", "TRUP", "TRV",
    "TSE", "TSEM", "TSLA", "TSLX", "TSN", "TSP", "TT", "TTEK", "TTI", "TTMI",
    "TTWO", "TUP", "TVTY", "TWI", "TWO", "TWST", "TXG", "TXMD", "TXRH", "TYL",
    "U", "UA", "UAA", "UBSI", "UCBI", "UCTT", "UDR", "UEC", "UEIC", "UFI",
    "UFPI", "UFPT", "UGI", "UHS", "UI", "UIS", "ULCC", "UMBF", "UMC", "UMH",
    "UNF", "UNFI", "UNIT", "UNM", "UPLD", "UPS", "URBN", "URGN", "URI", "USCB",
    "USFD", "USLM", "USM", "USNA", "USPH", "UTL", "UTMD", "UVE", "UVSP", "UWMC",
    "V", "VAC", "VBTX", "VC", "VCEL", "VCRA", "VCSA", "VECO", "VEEV", "VEL",
    "VERA", "VERV", "VERX", "VFC", "VG", "VGR", "VIAV", "VICR", "VIPS", "VIR",
    "VIST", "VITL", "VIVE", "VKTX", "VLY", "VMD", "VNDA", "VNT", "VOR", "VOYA",
    "VPG", "VRA", "VRCA", "VREX", "VRNS", "VRNT", "VRRM", "VRSK", "VRTS", "VSAT",
    "VSCO", "VSEC", "VSH", "VSTO", "VTLE", "VTOL", "VUZI", "VVI", "VVV", "VYX",
    "VYNE", "VZIO", "W", "WAB", "WABC", "WAFD", "WASH", "WB", "WBS", "WBX",
    "WCC", "WD", "WDAY", "WDC", "WDFC", "WDH", "WEN", "WERN", "WES", "WEX",
    "WGS", "WH", "WHD", "WHR", "WINA", "WING", "WIRE", "WIT", "WIX", "WK",
    "WKHS", "WKME", "WLDN", "WLY", "WMG", "WMK", "WMS", "WNC", "WOLF", "WOR",
    "WOW", "WPC", "WPM", "WRBY", "WRLD", "WRN", "WSBC", "WSC", "WSFS", "WSM",
    "WSO", "WSR", "WT", "WTBA", "WTI", "WTM", "WTRG", "WTS", "WTTR", "WU",
    "WULF", "WW", "WWD", "WWE", "WWW", "X", "XENE", "XERS", "XHR", "XMTR",
    "XNCR", "XOMA", "XP", "XPER", "XPO", "XPRO", "XRAY", "XRX", "XYL", "Y",
    "YELP", "YETI", "YEXT", "YORW", "YOU", "Z", "ZBH", "ZD", "ZEUS", "ZGN",
    "ZH", "ZIM", "ZION", "ZIP", "ZIVO", "ZNTL", "ZS", "ZUMZ", "ZUO", "ZWS",
    "ZYME", "ZYNE",
    # International ADRs — broad coverage
    "ABEV", "ARM", "ASND", "ASR", "ASX", "AVAL", "AZUL", "BAESY", "BAK", "BAP",
    "BBD", "BBDO", "BCH", "BCS", "BG", "BIDU", "BIIB", "BMA", "BNTX", "BP",
    "BRFS", "BSAC", "BSBR", "BTI", "BUD", "BVN", "CAR", "CCI", "CCJ", "CEA",
    "CHA", "CHL", "CHT", "CIB", "CIG", "CMCM", "CMRE", "CNH", "CNOOC", "COE",
    "CRH", "CSAN", "CSIQ", "CTRP", "CVA", "CVCO", "CX", "DANG", "DEO", "DESP",
    "DOOO", "E", "EBR", "EC", "EDU", "ELP", "ENI", "EPC", "ERIC", "ERJ",
    "FERG", "FMS", "FMX", "FUNAY", "GFI", "GGB", "GLPG", "GMAB", "GME", "GOL",
    "GOLD", "GRFS", "GROY", "GRVY", "GS", "HDB", "HIHO", "HMC", "HMY", "HOG",
    "HPP", "HRC", "HRZN", "HTHT", "HUYA", "IBN", "IDA", "INFY", "ING", "ITUB",
    "JKS", "JMIA", "KB", "KEP", "KGC", "KOF", "LFC", "LHCG", "LI", "LIN",
    "LPL", "LX", "LYG", "MBT", "MDXG", "MFG", "MGA", "MIME", "MMRP", "MNDO",
    "MOMO", "MUFG", "NAFTOGAZ", "NBIS", "NDAQ", "NESN", "NICE", "NIO", "NMR",
    "NOMD", "NOVN", "NTES", "NTL", "NVS", "OPRA", "ORAN", "OTEX", "PAGS", "PBR",
    "PBR-A", "PCAR", "PDD", "PG", "PHG", "PKX", "PLNT", "PRSP", "PTR", "QFIN",
    "RACE", "RAIL", "RBLX", "RDS-A", "RDS-B", "RDY", "RELX", "RIO", "RNR", "ROG",
    "RTL", "RY", "SAN", "SAP", "SAVE", "SBS", "SCCO", "SE", "SHEL", "SHOP",
    "SID", "SIGI", "SINA", "SLP", "SNN", "SNP", "SONO", "SONY", "SQM", "STM",
    "STN", "SUI", "SUZ", "SVNDY", "SYTE", "TAK", "TCEHY", "TD", "TECK", "TELL",
    "TGB", "TGE", "TGI", "TIGR", "TLK", "TM", "TME", "TNDM", "TOELF", "TOT",
    "TS", "TSEM", "TSU", "TTM", "TU", "TV", "TVE", "TX", "UBS", "UMC",
    "UN", "UNAM", "UNH", "UPL", "UVE", "VALE", "VEDL", "VIPS", "VLN", "VOD",
    "VTL", "VWAGY", "WB", "WCN", "WIT", "WNS", "WP", "WPP", "X", "XPEV",
    "XRX", "YANG", "YINN", "YPF", "YUMC", "ZIM", "ZK", "ZTO",
    # Recent IPOs / SPACs / High-volume actives (2023-2026)
    "ALAB", "ARM", "ASTS", "BABA", "BBAI", "BBLN", "BIRK", "BLDE", "BRBR", "BROS",
    "BRZE", "CART", "CAVA", "CELH", "CGEM", "CHWY", "CIFR", "CLNN", "CLOV", "CMI",
    "CRSP", "DNA", "DUOL", "ELAN", "EVTL", "FA", "FBIN", "FNF", "FOUR", "FTLF",
    "GDRX", "GENI", "GNTX", "GTX", "HIMS", "INMD", "INSP", "IOT", "JAMF", "JOBY",
    "KGEI", "KLG", "KSPI", "LMND", "MAPS", "MASS", "MNDY", "MRVI", "NABL", "NCLH",
    "NRDS", "NU", "OPRT", "OWL", "PCT", "PCTY", "PFC", "PLBY", "PLNT", "PLTR",
    "PRCT", "PRX", "PSFE", "PYPL", "QS", "RAIL", "RBRK", "RDDT", "RGTI", "RHCS",
    "RKLB", "RLX", "RNG", "RNW", "ROVR", "RVNC", "S", "SES", "SES", "SES",
    "SGFY", "SOFI", "SPCE", "SPSC", "SQ", "SVCO", "TIGR", "TMC", "TOST", "TPCS",
    "TPG", "TWLO", "U", "UPST", "VRT", "WFRD", "WOOF", "WULF", "ZG", "ZH",
    "ZIM", "ZWS", "ARCH", "ARRY", "ARQQ", "ASAN", "BLDP", "BOIL", "BOOM", "BTAI",
    "BTI", "BVS", "CART", "CATX", "CCEL", "CCEP", "CDLR", "CDNA", "CFLT", "CHRD",
    "CLBT", "CLNN", "CLSK", "CMPS", "CMPX", "COTY", "CRDO", "CRGY", "CRM", "CSCO",
    "CYTK", "DASH", "DAVA", "DDOG", "DJT", "DLRN", "DMRC", "DNUT", "DOCN", "DRCT",
    "DRS", "DUOL", "EFC", "ENVA", "EQNR", "EQX", "EW", "FIVE", "FLNC", "FOUR",
    "FROG", "FSLY", "FTAI", "GDS", "GEHC", "GETY", "GLPI", "GMS", "GOEV", "GPRE",
    "GPRO", "GRRR", "GTLB", "HDSN", "HIMS", "HRTX", "HSAI", "HUBC", "HUBS", "IBKR",
    "INDV", "INSE", "IOT", "IPI", "IPWR", "IREN", "IRWD", "JAMF", "JKHY", "KAVL",
    "KIDS", "KMTS", "KNTK", "KOD", "KOS", "KOSS", "KSCP", "KTOS", "KURA", "KVHI",
    "LFST", "LGND", "LITE", "LIVE", "LMND", "LMNL", "LNTH", "LOMA", "LULU", "LUNG",
    "LUNR", "LZ", "MASS", "MBLY", "MCFE", "MCK", "MDB", "MDLA", "MGNX", "MGRC",
    "MIDD", "MIME", "MKTW", "MLAB", "MLCO", "MMSI", "MNDY", "MORN", "MRNS", "MRSN",
    "MTLS", "MTTR", "MULN", "MURF", "NABL", "NCRA", "NEPT", "NET", "NEXT", "NMTC",
    "NTAP", "NTLA", "NTNX", "NTRA", "NU", "NVCT", "NWBI", "NWS", "NWSA", "NYCB",
    "OB", "OCSL", "OFLX", "OKE", "OKTA", "OLED", "OLO", "OLPX", "OM", "ONON",
    "OPK", "OPRT", "OPRX", "ORC", "ORI", "ORN", "OS", "OSIS", "OSPN", "OSTK",
    "OTIS", "OUST", "OXSQ", "PACB", "PAGS", "PAR", "PARR", "PATH", "PAYS", "PCTI",
    "PD", "PDD", "PDFS", "PDS", "PEGA", "PENN", "PEP", "PERI", "PETS", "PFE",
    "PGEN", "PHG", "PHIO", "PHM", "PHR", "PI", "PII", "PIN", "PINE", "PINS",
    "PIPR", "PJT", "PK", "PLBC", "PLNT", "PLOW", "PLPC", "PLRX", "PLSE", "PLTK",
    "PLUS", "PLXS", "PLYM", "PM", "PNC", "PNFP", "PNM", "PNTG", "PNW", "PODD",
    "POOL", "POR", "POST", "POWI", "POWL", "PPBI", "PPC", "PR", "PRA", "PRAA",
    "PRDO", "PRFT", "PRG", "PRGO", "PRGS", "PRI", "PRIM", "PRK", "PRLB", "PRMW",
    "PRO", "PRPL", "PRTA", "PRTY", "PRU", "PRVA", "PSB", "PSEC", "PSMT", "PSN",
    "PSTG", "PSTL", "PTCT", "PTGX", "PTON", "PTSI", "PTVE", "PUMP", "PVH", "PWP",
    "PWSC", "PWUP", "PX", "PYCR", "PZZA", "QCOM", "QCRH", "QDEL", "QGEN", "QLYS",
    "QNST", "QRTEA", "QRTEB", "QTRX", "QTWO", "QURE", "R", "RACE", "RAMP", "RBA",
    "RBB", "RBC", "RBCAA", "RC", "RCKT", "RCM", "RCMT", "RCUS", "RDFN", "RDN",
    "RDWR", "REAL", "REI", "REPL", "REPX", "REX", "REXR", "REYN", "RGA", "RGEN",
    "RGLD", "RGNX", "RGP", "RGR", "RH", "RHI", "RICK", "RILY", "RIOT", "RKLB",
    "RKT", "RLAY", "RLI", "RLJ", "RLMD", "RLX", "RMAX", "RMBS", "RMD", "RMR",
    "RNG", "RNST", "ROCK", "ROG", "ROIC", "ROIV", "ROL", "RPAY", "RPD", "RPM",
    "RRBI", "RRGB", "RRR", "RRX", "RSI", "RTL", "RTLR", "RUSHA", "RUSHB", "RUTH",
    "RVMD", "RVT", "RWT", "RXO", "RXT", "RYAM", "RYAN", "RYI", "RYN", "S",
    "SABR", "SAFE", "SAFM", "SAFT", "SAH", "SAIA", "SAIC", "SAM", "SAMG", "SANA",
    "SANM", "SASR", "SATS", "SAVE", "SBCF", "SBGI", "SBH", "SBLK", "SBR", "SBSI",
    "SBT", "SCCO", "SCHL", "SCI", "SCL", "SCSC", "SCVL", "SDGR", "SEAS", "SEDG",
    "SEE", "SEM", "SEMR", "SERV", "SF", "SFBS", "SFE", "SFL", "SFM", "SFNC",
    "SGA", "SGH", "SGRY", "SHAK", "SHC", "SHEN", "SHO", "SHOO", "SHYF", "SIBN",
    "SIEB", "SIG", "SIGI", "SIRI", "SITC", "SITE", "SIX", "SJW", "SKT", "SKYW",
    "SLAB", "SLG", "SLGN", "SLM", "SLNO", "SLP", "SLVM", "SM", "SMBC", "SMBK",
    "SMG", "SMHI", "SMP", "SMPL", "SMRT", "SMTC", "SNBR", "SNCY", "SNDR", "SNDX",
    "SNFCA", "SNV", "SNX", "SOI", "SON", "SP", "SPB", "SPHR", "SPNT", "SPNS",
    "SPOK", "SPSC", "SPT", "SPTN", "SPWH", "SR", "SRCE", "SRDX", "SRE", "SRG",
    "SRPT", "SSB", "SSD", "SSP", "SSTI", "SSTK", "ST", "STAA", "STAG", "STBA",
    "STC", "STEL", "STEM", "STEP", "STER", "STGW", "STKL", "STN", "STNE", "STR",
    "STRA", "STRL", "STT", "SUM", "SUN", "SUPN", "SUPR", "SVC", "SVRA", "SWAV",
    "SWBI", "SWI", "SWIM", "SWX", "SXC", "SXI", "SXT", "SYBT", "SYNA", "SYRS",
]

_ETF_RAW: list[str] = [
    # Broad-market core
    "SPY", "QQQ", "IWM", "DIA", "VOO", "VTI", "VEA", "VWO", "EFA", "EEM",
    "IEMG", "IVV", "IJH", "IJR", "VO", "VB", "VTV", "VUG", "VYM", "VIG",
    "SCHB", "SCHX", "SCHA", "SCHM", "SCHV", "SCHG", "SCHD", "SPHQ", "SPLG",
    "ITOT", "IVE", "IVW", "IUSV", "IUSG", "IUSB", "DGRO", "NOBL", "QUAL",
    # Fixed Income
    "AGG", "BND", "LQD", "HYG", "TLT", "IEF", "SHY", "TIP", "GOVT", "BSV",
    "BIV", "BLV", "VCSH", "VCIT", "VCLT", "VGSH", "VGIT", "VGLT", "VTIP",
    "MUB", "TFI", "SHM", "VTEB", "HYD", "JNK", "ANGL", "FALN", "EMB", "PCY",
    "IGOV", "BWX", "BNDX", "FLOT", "USFR", "BIL", "SGOV", "SCHO", "SCHR",
    "STIP", "VTC", "EDV", "ZROZ", "TLH", "IEI", "BAB", "PFF", "PGX", "PFFD",
    # Sector SPDRs + iShares sectors
    "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB", "XLRE",
    "XLC", "VGT", "VFH", "VDE", "VHT", "VCR", "VDC", "VIS", "VPU", "VAW",
    "VNQ", "IYR", "IYW", "IYF", "IYE", "IYH", "IYK", "IYC", "IYJ", "IDU",
    "FXG", "FXL", "FXD", "FXH", "FXR", "FXO", "FXN", "FXZ", "RYT", "RGI",
    # Thematic / Innovation
    "ARKK", "ARKG", "ARKW", "ARKQ", "ARKF", "ARKX", "PRNT", "IZRL",
    "SMH", "SOXX", "PSI", "XSD", "FTXL", "XSW", "IGV", "FDN", "PNQI",
    "ITA", "PPA", "XAR", "ITB", "XHB", "PKB", "XME", "REMX", "PICK",
    "IBB", "XBI", "ARKG", "IDNA", "GNOM", "HELX", "PILL", "BIB", "BIS",
    "KRE", "IAT", "KBE", "KBWB", "KBWR", "JETS", "URA", "URNM", "NLR",
    "BUG", "HACK", "WCBR", "AIQ", "BOTZ", "ROBO", "ROBT", "IRBO", "THNQ",
    "MOO", "WOOD", "CUT", "PHO", "WOOD", "LIT", "BATT", "ICLN", "TAN",
    "FAN", "PBW", "QCLN", "ACES", "PBD", "KLNE", "URNJ", "CLOU", "WCLD",
    "BLOK", "BITQ", "DAPP", "BITO", "BTF", "MAXI", "GBTC", "ETHE", "ETHV",
    "BLNK", "DRIV", "IDRV", "KARS", "CARZ", "EKAR", "MJ", "MSOS", "YOLO",
    "BJK", "PEJ", "PEZ", "FCG", "SLX", "URA", "URNM", "MJ", "GAMR", "ESPO",
    # International / Country
    "VXUS", "ACWI", "ACWX", "URTH", "VEU", "VPL", "VGK", "EWJ", "EWG",
    "EWU", "EWQ", "EWI", "EWP", "EWN", "EWD", "EWY", "EWZ", "EWT", "EWH",
    "EWA", "EWC", "EWM", "EWS", "EWL", "EWW", "EZA", "EIRL", "EIDO", "EPHE",
    "EPOL", "GREK", "EPU", "ECH", "ARGT", "INDA", "INDY", "EPI", "PIN",
    "FXI", "MCHI", "ASHR", "KWEB", "CQQQ", "CHIQ", "CHIK", "CHIC", "CHII",
    "PGJ", "YINN", "YANG", "FLCH", "FLKR", "FLBR", "FLIN", "FLMX", "FLJP",
    "ILF", "VNM", "FM", "AAXJ", "FNDF", "FNDE", "EWJV", "DXJ", "DBJP", "HEWJ",
    # Smart Beta / Factor
    "MTUM", "VLUE", "QUAL", "USMV", "SIZE", "PDP", "PIE", "DEM", "DGS",
    "SDOG", "DEW", "VYMI", "DOO", "DGRW", "DGRE", "RPV", "RPG", "PRF",
    "FNDX", "SPYG", "SPYV", "SPYD", "SPLV", "SPHB", "OEF", "MGC", "MGK",
    "MGV", "MDY", "MDYG", "MDYV", "VTV", "VOE", "VBR", "VBK", "SLY", "SLYG",
    # Commodities (broad and single)
    "GLD", "SLV", "USO", "BNO", "UNG", "DBA", "DBC", "PDBC", "GSG", "DJP",
    "CORN", "WEAT", "SOYB", "CANE", "COW", "JJG", "JJC", "JO", "NIB", "BAL",
    "PALL", "PPLT", "SGOL", "IAU", "GLDM", "SIVR", "SLVO", "FCG", "CPER",
    "URA", "URNM", "LIT", "BATT", "REMX", "PALL", "PPLT", "SPPP", "WOOD",
    # Real Estate sub-sectors
    "VNQ", "IYR", "SCHH", "RWR", "FREL", "USRT", "MORT", "REM", "REZ", "ROOF",
    "NETL", "INDS", "SRVR", "PSR", "ICF", "BBRE", "EWRE", "PRTL", "VNQI",
    # Cash / Money Market
    "BIL", "SGOV", "SHV", "PULS", "FLRN", "USFR", "ICSH", "BOND", "CARY",
    # Volatility / Inverse / Leveraged
    "VXX", "VIXY", "UVXY", "SVXY", "SH", "PSQ", "DOG", "RWM", "TBT", "TBF",
    "SQQQ", "TQQQ", "SPXL", "SPXS", "UPRO", "SDS", "SSO", "TNA", "TZA",
    "FAS", "FAZ", "ERX", "ERY", "TMF", "TMV", "UVXY", "SOXL", "SOXS",
    "TECL", "TECS", "SDOW", "UDOW", "UCO", "SCO", "BOIL", "KOLD", "AGQ",
    # New emerging / niche
    "MOAT", "AOA", "AOR", "AOM", "AOK", "MGAS", "MAGS", "MAGS",
]

_FX_RAW: list[str] = [
    # G10 majors
    "EURUSD=X", "GBPUSD=X", "USDJPY=X", "USDCHF=X", "AUDUSD=X", "USDCAD=X",
    "NZDUSD=X",
    # G10 crosses
    "EURGBP=X", "EURJPY=X", "GBPJPY=X", "AUDJPY=X", "EURCHF=X",
    "EURAUD=X", "GBPCHF=X", "GBPAUD=X", "AUDCAD=X", "AUDCHF=X", "AUDNZD=X",
    "CADJPY=X", "CHFJPY=X", "NZDJPY=X", "EURCAD=X", "EURNZD=X", "GBPNZD=X",
    "GBPCAD=X", "NZDCAD=X", "NZDCHF=X", "EURSEK=X", "EURNOK=X", "EURDKK=X",
    "EURHUF=X", "EURPLN=X", "EURCZK=X", "EURTRY=X", "EURZAR=X", "EURMXN=X",
    # Scandi/Nordic
    "USDSEK=X", "USDNOK=X", "USDDKK=X", "USDISK=X",
    # EM majors
    "USDMXN=X", "USDZAR=X", "USDTRY=X", "USDBRL=X", "USDINR=X", "USDCNY=X",
    "USDCNH=X", "USDHKD=X", "USDSGD=X", "USDKRW=X", "USDTWD=X", "USDTHB=X",
    "USDIDR=X", "USDPHP=X", "USDMYR=X", "USDVND=X", "USDPLN=X", "USDHUF=X",
    "USDCZK=X", "USDRON=X", "USDILS=X", "USDAED=X", "USDSAR=X", "USDARS=X",
    "USDCLP=X", "USDCOP=X", "USDPEN=X", "USDEGP=X",
]

_COMMODITY_RAW: list[str] = [
    # Precious
    "GC=F", "SI=F", "PL=F", "PA=F", "MGC=F", "SIL=F",
    # Energy
    "CL=F", "BZ=F", "NG=F", "RB=F", "HO=F", "QM=F", "QG=F",
    # Industrial metals
    "HG=F", "ALI=F", "QC=F",
    # Grains / Softs
    "ZC=F", "ZW=F", "ZS=F", "ZL=F", "ZM=F", "ZO=F", "ZR=F",
    "KC=F", "CC=F", "SB=F", "CT=F", "OJ=F", "LBR=F",
    # Livestock
    "LE=F", "HE=F", "GF=F",
]

_BOND_RAW: list[str] = [
    # US yields (^IRX 13w, ^FVX 5y, ^TNX 10y, ^TYX 30y)
    "^IRX", "^FVX", "^TNX", "^TYX",
    # Sovereign 10y proxies (best-effort yfinance tickers — engine falls
    # back to NEUTRAL if the feed is unavailable, so failed tickers don't
    # break the scan)
    "^DE10Y", "^GB10Y", "^JP10Y",
    "^IT10Y", "^FR10Y", "^ES10Y", "^NL10Y", "^BE10Y",
    "^AU10Y", "^NZ10Y", "^CA10Y", "^CH10Y", "^SE10Y",
]


def _dedup_preserve_order(symbols: list[str]) -> list[str]:
    """Strip + upper-case + dedupe a symbol list, keeping first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in symbols:
        if not isinstance(raw, str):
            continue
        sym = raw.strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    return out


MIS_UNIVERSES: dict[str, list[str]] = {
    "CRYPTO": _filter_crypto_universe(_CRYPTO_RAW),
    "EQUITY": _dedup_preserve_order(_EQUITY_RAW),
    "ETF": _dedup_preserve_order(_ETF_RAW),
    "FX": _dedup_preserve_order(_FX_RAW),
    "COMMODITY": _dedup_preserve_order(_COMMODITY_RAW),
    "BOND": _dedup_preserve_order(_BOND_RAW),
}


# ── Default config (mirrors TBV3 default.yaml — repackaged for MIS) ──────

DEFAULT_CONSENSUS: dict[str, float] = {
    "strong_buy_threshold": 0.95,
    "buy_threshold": 0.30,
    "sell_threshold": -0.30,
    "strong_sell_threshold": -0.95,
    "conflict_ratio_threshold": 0.6,
    "min_active_signals": 4,
}

DEFAULT_NO_TRADE: dict[str, float] = {
    "adx_min": 15.0,
    "atr_high_percentile": 95.0,
    "min_confidence": 30.0,
}

DEFAULT_RISK: dict[str, Any] = {
    "confidence_threshold": 25,
    "max_risk_level": "MEDIUM",
}

DEFAULT_INDICATOR_WEIGHTS: dict[str, float] = {
    "adx_di": 1.5,
    "atr_filter": 0.0,
    "bollinger": 1.5,
    "cci": 1.0,
    "ema_cross": 1.8,
    "ichimoku": 2.0,
    "macd": 2.0,
    "mfi": 1.2,
    "obv": 1.2,
    "psar": 1.3,
    "roc": 1.0,
    "rsi": 1.5,
    "sma_cross": 1.8,
    "stochastic": 1.2,
    "williams_r": 1.0,
    "supertrend": 1.7,
    "vwap": 1.5,
    "cvd": 1.4,
    "keltner": 1.3,
    "heikin_ashi": 1.1,
    # Funding-rate / open-interest / liquidation only register for
    # crypto-futures; their weights stay here so the UI can tune them
    # but the indicator instance is only built when relevant.
    "funding_rate": 1.3,
    "open_interest": 1.2,
    "liquidation_pressure": 1.4,
}

DEFAULT_INDICATOR_THRESHOLDS: dict[str, dict[str, Any]] = {
    "adx_di": {"period": 14, "strong_trend": 25, "weak_trend": 15},
    "atr": {"period": 14, "high_volatility_multiplier": 2.0},
    "bollinger": {
        "period": 20, "squeeze_threshold": 0.02, "std_dev": 2.0,
        "adx_period": 14, "adx_trend_floor": 20, "high_volume_multiplier": 1.5,
    },
    "cci": {"period": 20, "buy": -100, "sell": 100, "strong_buy": -200, "strong_sell": 200},
    "ema_cross": {"long_period": 21, "short_period": 9, "strong_divergence_pct": 0.02},
    "ichimoku": {"kijun_period": 26, "senkou_b_period": 52, "tenkan_period": 9},
    "macd": {"fast_period": 12, "signal_period": 9, "slow_period": 26, "strong_histogram_threshold": 0.5},
    "mfi": {"period": 14, "buy": 30, "sell": 70, "strong_buy": 20, "strong_sell": 80},
    "obv": {"sma_period": 20, "divergence_lookback": 10, "slope_min_normalized": 0.001},
    "psar": {
        "af_start": 0.02, "af_increment": 0.02, "af_max": 0.2,
        "weak_distance_pct": 0.5, "strong_distance_pct": 2.0,
    },
    "roc": {"period": 12, "strong_threshold": 5.0, "weak_threshold": 1.0},
    "rsi": {
        "period": 14, "buy": 35, "sell": 65, "strong_buy": 25, "strong_sell": 80,
        "divergence_lookback": 14,
    },
    "sma_cross": {
        "long_period": 50, "short_period": 10,
        "strong_divergence_pct": 0.02, "weak_divergence_pct": 0.005,
    },
    "stochastic": {"k_period": 14, "d_period": 3, "overbought": 80, "oversold": 20},
    "williams_r": {"period": 14, "overbought": -20, "oversold": -80},
    "supertrend": {"atr_period": 10, "multiplier": 3.0, "confirmation_bars": 3, "flip_buffer_atr": 0.3},
    "vwap": {"rolling_period": 96, "band_std_1": 1.0, "band_std_2": 2.0, "high_volume_multiplier": 1.5},
    "cvd": {"cvd_ema_period": 20, "slope_lookback": 5, "divergence_lookback": 10, "divergence_pct_threshold": 0.02},
    "keltner": {"ema_period": 20, "atr_period": 10, "multiplier": 2.0, "bb_period": 20, "bb_std": 2.0},
    "heikin_ashi": {"confirmation_bars": 3, "strong_confirmation_bars": 5, "doji_atr_ratio": 0.2},
    "funding_rate": {"history_days": 30, "z_score_strong": 2.5, "z_score_normal": 1.5},
    "open_interest": {"period": "1h", "lookback_bars": 5, "strong_threshold_pct": 5.0, "normal_threshold_pct": 2.0},
    "liquidation_pressure": {
        "window_minutes": 60, "strong_imbalance_ratio": 3.0,
        "weak_imbalance_ratio": 1.5, "min_total_notional": 100000.0,
    },
}


def _base_market_config(market: str = "CRYPTO") -> dict[str, Any]:
    """Return a fresh copy of the default per-market calibration.

    Includes the ZAK timeframe matrix and active TF set for the given
    market. Caller passes ``market`` so each entry gets the right TF
    defaults; missing/unknown markets fall back to CRYPTO's ZAK so the
    UI never sees a None.
    """
    tf_weights = MARKET_TF_WEIGHTS.get(market, MARKET_TF_WEIGHTS["CRYPTO"])
    tf_set = MARKET_DEFAULT_TFS.get(market, MARKET_DEFAULT_TFS["CRYPTO"])
    return {
        "indicator_weights": copy.deepcopy(DEFAULT_INDICATOR_WEIGHTS),
        "indicator_thresholds": copy.deepcopy(DEFAULT_INDICATOR_THRESHOLDS),
        "consensus": copy.deepcopy(DEFAULT_CONSENSUS),
        "no_trade": copy.deepcopy(DEFAULT_NO_TRADE),
        "risk": copy.deepcopy(DEFAULT_RISK),
        "tf_weights": dict(tf_weights),
        "tf_set": list(tf_set),
        "universe_override": [],  # Empty → use MIS_UNIVERSES[market].
    }


def _default_bundle() -> dict[str, Any]:
    return {
        "version": 1,
        "markets": {m: _base_market_config(m) for m in MIS_MARKETS},
    }


CONFIG_PATH_NAME = "mis_config.json"


def load_mis_config() -> dict[str, Any]:
    """Load the persisted MIS config, falling back to defaults on miss/corrupt."""
    import json
    path = cache_path(CONFIG_PATH_NAME)
    if not path.exists():
        return _default_bundle()
    try:
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        LOG.warning("MIS config unreadable, using defaults: %s", exc)
        return _default_bundle()
    if not isinstance(payload, dict) or "markets" not in payload:
        return _default_bundle()
    # Backfill any missing markets so the UI never sees None.
    base = _default_bundle()
    base_markets = base["markets"]
    incoming = payload.get("markets") or {}
    merged: dict[str, Any] = {}
    for m in MIS_MARKETS:
        merged[m] = _merge_market_config(base_markets[m], incoming.get(m) or {}, market=m)
    payload["markets"] = merged
    payload.setdefault("version", base["version"])
    return payload


def _merge_market_config(
    base: dict[str, Any],
    override: dict[str, Any],
    *,
    market: str | None = None,
) -> dict[str, Any]:
    """Shallow-merge user overrides over the defaults, deep for nested dicts."""
    out = copy.deepcopy(base)
    if not isinstance(override, dict):
        return out
    for key, value in override.items():
        if key in {"indicator_weights", "consensus", "no_trade", "risk"} and isinstance(value, dict):
            out[key] = {**out.get(key, {}), **value}
        elif key == "tf_weights" and isinstance(value, dict):
            merged_tf = dict(out.get("tf_weights", {}))
            for tf, w in value.items():
                if isinstance(tf, str):
                    try:
                        merged_tf[tf] = int(w) if not isinstance(w, bool) else 0
                    except (TypeError, ValueError):
                        continue
            out["tf_weights"] = merged_tf
        elif key == "tf_set" and isinstance(value, list):
            # Keep only TFs we know weights for, deduped, in user-provided order.
            known = set(out.get("tf_weights", {}).keys())
            seen: set[str] = set()
            cleaned: list[str] = []
            for tf in value:
                if not isinstance(tf, str):
                    continue
                tf = tf.strip()
                if tf and tf in known and tf not in seen:
                    seen.add(tf)
                    cleaned.append(tf)
            out["tf_set"] = cleaned
        elif key == "indicator_thresholds" and isinstance(value, dict):
            merged_thresh = copy.deepcopy(out.get("indicator_thresholds", {}))
            for ind, params in value.items():
                if isinstance(params, dict):
                    merged_thresh[ind] = {**merged_thresh.get(ind, {}), **params}
            out["indicator_thresholds"] = merged_thresh
        elif key == "universe_override" and isinstance(value, list):
            cleaned = [str(s).strip().upper() for s in value if isinstance(s, str) and str(s).strip()]
            # Out[''] not yet aware of market — caller filters per-market
            # in `_resolve_universe`. We still dedupe here so the persisted
            # JSON stays tidy.
            seen2: set[str] = set()
            ordered: list[str] = []
            for sym in cleaned:
                if sym not in seen2:
                    seen2.add(sym)
                    ordered.append(sym)
            out["universe_override"] = ordered
        else:
            out[key] = value
    # If the user accidentally cleared `tf_set`, fall back to "all weighted TFs"
    # so the next scan still produces a meaningful score.
    if not out.get("tf_set"):
        out["tf_set"] = list(out.get("tf_weights", {}).keys())
    return out


def save_mis_config(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate + persist the MIS config bundle."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    markets = payload.get("markets")
    if not isinstance(markets, dict):
        raise ValueError("payload.markets must be an object")
    base = _default_bundle()["markets"]
    cleaned: dict[str, Any] = {}
    for m in MIS_MARKETS:
        incoming = markets.get(m)
        if not isinstance(incoming, dict):
            cleaned[m] = base[m]
            continue
        cleaned[m] = _merge_market_config(base[m], incoming, market=m)
    bundle = {"version": int(payload.get("version", 1)) or 1, "markets": cleaned}
    atomic_write_json(cache_path(CONFIG_PATH_NAME), bundle, secure=True)
    return bundle


# ── Scan request / result schema ─────────────────────────────────────────

@dataclass
class MisScanRequest:
    markets: list[str]
    # Back-compat: single-TF override per market. When set, that ONE TF is the
    # only one scanned for that market. New callers should leave this empty
    # and use ``tf_set_override`` instead.
    timeframes: dict[str, str] = field(default_factory=dict)
    # Multi-TF override per market: ``{"CRYPTO": ["1h", "4h", "1d"]}``. When a
    # market appears here, this list replaces the saved ``tf_set`` for the
    # duration of the scan. ``tf_weights`` still come from the saved config.
    tf_set_override: dict[str, list[str]] = field(default_factory=dict)
    top_n: int = 50
    min_confidence: float = 0.0  # Filter out rows with confidence < this.
    only_signals: bool = False  # If true, drop NEUTRAL rows.
    max_symbols_per_market: int | None = None  # Hard cap per market.


@dataclass
class MisScanRow:
    symbol: str
    market: str
    asset_class: str
    # Comma-joined string of every TF that contributed to the aggregate
    # (e.g. ``"1h·4h·1d"``). Kept for back-compat with the v1 row shape;
    # ``per_tf`` is the actual structured data.
    timeframe: str
    direction: str
    final_signal: str
    weighted_score: float
    confidence: float
    last: float | None
    change_pct: float | None
    top_indicators: list[dict[str, Any]]
    indicator_breakdown: list[dict[str, Any]]
    # Per-TF breakdown: ``[{tf, weight, direction, final_signal, score,
    # confidence, contribution}, ...]``. The aggregate ``weighted_score``
    # above is the weight-normalised sum of these contributions.
    per_tf: list[dict[str, Any]] = field(default_factory=list)
    tf_count_scanned: int = 0
    tf_count_with_signal: int = 0
    skipped: str | None = None


@dataclass
class MisScanResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    markets: list[str] = field(default_factory=list)
    per_market_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0
    started_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Engine adapters ──────────────────────────────────────────────────────

def _resolve_universe(market: str, config: dict[str, Any]) -> list[str]:
    """Return the symbol list for a market, honouring user overrides.

    For CRYPTO, the universe (default OR user override) is filtered to
    USDT-quoted, non-stablecoin-base symbols. This is enforced in *both*
    paths so a user cannot smuggle ``USDCUSDT`` or ``BTCBUSD`` in via
    settings.
    """
    market_cfg = (config.get("markets") or {}).get(market) or {}
    override = market_cfg.get("universe_override") or []
    if override:
        raw = [str(s).strip().upper() for s in override if isinstance(s, str) and str(s).strip()]
        if market == "CRYPTO":
            return _filter_crypto_universe(raw)
        return _dedup_preserve_order(raw)
    return list(MIS_UNIVERSES.get(market, []))


def _resample_ohlcv(df, rule: str):
    """Downsample an OHLCV DataFrame to a coarser cadence.

    Uses the canonical OHLCV aggregation: open=first, high=max, low=min,
    close=last, volume=sum. Drops rows where every column is NaN (a gap
    in the source stream resampled to nothing). The aggregator below
    requires ≥55 bars after this step, so the caller must fetch enough
    source history — ``_days_for_timeframe`` already over-shoots.
    """
    if df is None or len(df) == 0:
        return None
    try:
        # Engine DataFrames are indexed on a tz-aware datetime; pandas
        # ``.resample`` will happily consume that. ``label='right'`` and
        # ``closed='right'`` mirror the way TradingView/Binance label bars
        # (bar timestamp = bar close time).
        agg: dict[str, str] = {"open": "first", "high": "max", "low": "min", "close": "last"}
        if "volume" in df.columns:
            agg["volume"] = "sum"
        keep = [c for c in agg.keys() if c in df.columns]
        if "open" not in keep or "close" not in keep:
            return None
        resampled = df[keep].resample(rule, label="right", closed="right").agg(agg).dropna()
        return resampled if len(resampled) else None
    except Exception as exc:  # noqa: BLE001
        LOG.debug("MIS resample failed (%s): %s", rule, exc)
        return None


async def _fetch_ohlcv(deps: Any, symbol: str, market: str, timeframe: str, days: int):
    """Best-effort OHLCV DataFrame fetch via the engine's data adapters.

    For non-CRYPTO markets where the requested TF isn't yfinance-native
    (3m, 2h, 4h, 6h, 8h, 12h), this fetches the coarser source TF and
    resamples in-process. This is what lets every market run the same
    12-TF ZAK matrix even though yfinance only natively serves 9 of
    those bar sizes.
    """
    try:
        from showme.engine.core.base_data_source import DataKind, DataRequest
        from showme.engine.core.instrument import AssetClass, Instrument
    except Exception as exc:  # noqa: BLE001
        LOG.warning("MIS: engine imports unavailable: %s", exc)
        return None
    ac_name = _ASSET_CLASS_MAP.get(market, "EQUITY")
    ac_attr = getattr(AssetClass, ac_name, None)
    if ac_attr is None:
        # ETF/BOND may not exist on every engine version → fall back to EQUITY.
        ac_attr = AssetClass.EQUITY
    inst = Instrument(symbol=symbol, asset_class=ac_attr)
    adapter = None
    if market == "CRYPTO":
        adapter = getattr(deps, "ccxt_failover", None) or getattr(deps, "coingecko", None)
    if adapter is None:
        adapter = getattr(deps, "yfinance", None)
    if adapter is None:
        return None

    # Decide whether to fetch the requested TF directly or resample. CCXT
    # (CRYPTO) supports every TF in the ZAK matrix natively, so skip the
    # resample path; yfinance needs the bridge for 5 of the 12 TFs.
    fetch_tf = timeframe
    resample_rule: str | None = None
    fetch_days = days
    if market != "CRYPTO" and timeframe in _RESAMPLE_RULES:
        source_tf, rule = _RESAMPLE_RULES[timeframe]
        fetch_tf = source_tf
        resample_rule = rule
        # Source TF needs at least as much history as the target × ratio.
        # ``_days_for_timeframe`` already over-shoots, but bump again to
        # guarantee 55+ resampled bars even on illiquid tickers.
        fetch_days = max(_days_for_timeframe(source_tf), days)

    try:
        df = await adapter.fetch(DataRequest(
            kind=DataKind.OHLCV, instrument=inst,
            start=datetime.now(timezone.utc) - timedelta(days=fetch_days),
            interval=fetch_tf,
        ))
    except Exception as exc:  # noqa: BLE001
        LOG.debug("MIS OHLCV fetch failed %s/%s: %s", symbol, fetch_tf, exc)
        return None
    if df is None:
        return None
    if resample_rule:
        df = _resample_ohlcv(df, resample_rule)
    return df


def _days_for_timeframe(timeframe: str) -> int:
    """Pick an OHLCV history window deep enough for the slowest indicator
    (Ichimoku senkou_b = 52 bars). Adds margin so divergence lookbacks have
    enough lead-in."""
    tf = timeframe.lower()
    if tf in {"1m", "5m", "15m", "30m"}:
        return 14
    if tf in {"1h", "2h"}:
        return 45
    if tf == "4h":
        return 90
    if tf in {"6h", "8h", "12h"}:
        return 180
    if tf in {"1d", "1day"}:
        return 365
    if tf in {"1wk", "1w"}:
        return 365 * 4
    if tf in {"1mo", "1month"}:
        return 365 * 8
    return 365


def _scan_one_sync(df, market_config: dict[str, Any]) -> dict[str, Any]:
    """Run all indicators + consensus on a single DataFrame.

    Runs in a worker thread (``asyncio.to_thread``) since indicator math
    is CPU-bound pandas. Returns a dict so it crosses the thread boundary
    cleanly.
    """
    from showme.engine.consensus.engine import ConsensusEngine
    from showme.engine.services.signal_service import SignalService

    # SignalService needs ``market_type`` to decide whether to register the
    # futures-only indicators. MIS always omits FundingRate/OpenInterest/
    # LiquidationPressure because we're not feeding a Binance client.
    cfg = dict(market_config)
    cfg.setdefault("market_type", "spot")

    service = SignalService(cfg)
    results = service.calculate_all(df)
    engine = ConsensusEngine(cfg)
    output = engine.evaluate(results)
    return {
        "consensus": output,
        "indicator_results": [r.to_dict() for r in results],
    }


def _last_change_pct(df) -> tuple[float | None, float | None]:
    """Read the last close and the close-to-close % change."""
    try:
        close = df["close"].dropna()
        if len(close) == 0:
            return None, None
        last = float(close.iloc[-1])
        if len(close) < 2:
            return last, None
        prev = float(close.iloc[-2])
        if prev == 0:
            return last, None
        return last, (last / prev - 1.0) * 100.0
    except Exception:  # noqa: BLE001
        # QA-fix: log so a malformed close column does not silently zero out
        # the scan row's % change.
        LOG.debug("_last_change_pct: close column unreadable", exc_info=True)
        return None, None


# ── Main scan entry-point ────────────────────────────────────────────────

async def run_mis_scan(req: MisScanRequest, deps: Any) -> MisScanResult:
    """Sweep every selected market with the full indicator stack across the
    market's full ZAK-weighted TF set.

    Each symbol is scanned on every active TF for its market. The per-TF
    consensus contributions are aggregated as:

        contribution_i = sign(direction_i) × (confidence_i / 100) × (zak_i / 100)
        aggregate_score = Σ contribution_i
        aggregate_confidence = min(100, |aggregate_score| × 100 / (Σ zak_i / 100))

    This matches TBV3's bot_service multi-TF aggregation (see
    ``TBV3/src/services/bot_service.py`` line 140-150 / 1004-1023).

    Concurrency is gated by a single per-call semaphore. ``24`` keeps
    yfinance + ccxt within their per-second caps while letting each
    symbol's TFs run in parallel — typical crypto sweep finishes in
    ~90-150 s with full 12-TF coverage.
    """
    started = time.perf_counter()
    config = load_mis_config()

    selected = [m for m in req.markets if m in MIS_MARKETS]
    if not selected:
        selected = list(MIS_MARKETS)

    rows: list[dict[str, Any]] = []
    per_market: dict[str, dict[str, int]] = {}
    warnings: list[str] = []

    # Bigger semaphore than v1 because each symbol now schedules N TF fetches.
    semaphore = asyncio.Semaphore(24)

    def _resolve_tfs(market: str, market_cfg: dict[str, Any]) -> tuple[list[str], dict[str, int]]:
        """Pick which TFs to scan + the weight to give each one.

        Priority:
          1. ``tf_set_override[market]`` if the request explicitly sets it
          2. Legacy ``timeframes[market]`` single-TF override (back-compat)
          3. The saved ``tf_set`` for the market (default = all TFs)
        Weights always come from the saved ``tf_weights``; missing weights
        fall back to the asset-class default ZAK.
        """
        weights = dict(market_cfg.get("tf_weights") or {})
        for k, v in MARKET_TF_WEIGHTS.get(market, {}).items():
            weights.setdefault(k, v)

        override_list = req.tf_set_override.get(market) if req.tf_set_override else None
        legacy_single = req.timeframes.get(market) if req.timeframes else None

        if isinstance(override_list, list) and override_list:
            tfs = [tf for tf in override_list if isinstance(tf, str) and tf]
        elif isinstance(legacy_single, str) and legacy_single:
            tfs = [legacy_single]
            weights.setdefault(legacy_single, 50)
        else:
            tfs = list(market_cfg.get("tf_set") or MARKET_DEFAULT_TFS.get(market, ["1d"]))
        # De-dupe + ensure each tf has a weight (fall back to 50).
        seen: set[str] = set()
        ordered: list[str] = []
        for tf in tfs:
            if tf not in seen:
                seen.add(tf)
                ordered.append(tf)
                weights.setdefault(tf, 50)
        return ordered, weights

    async def _scan_one_tf(
        symbol: str,
        market: str,
        market_cfg: dict[str, Any],
        tf: str,
        weight: int,
    ) -> tuple[dict[str, Any] | None, Any]:
        """Run a single (symbol, tf) consensus pass. Returns
        ``(per_tf_row | None, df_for_quote)``.

        On insufficient bars or fetch failure the per-TF row carries
        ``skipped`` so the aggregator can still account for the attempt.
        """
        days = _days_for_timeframe(tf)
        async with semaphore:
            df = await _fetch_ohlcv(deps, symbol, market, tf, days)
        if df is None or len(df) < 55:
            return {
                "tf": tf, "weight": int(weight),
                "direction": "NEUTRAL", "final_signal": "NEUTRAL",
                "score": 0.0, "confidence": 0.0, "contribution": 0.0,
                "skipped": "insufficient bars",
            }, None
        try:
            payload = await asyncio.to_thread(_scan_one_sync, df, market_cfg)
        except Exception as exc:  # noqa: BLE001
            return {
                "tf": tf, "weight": int(weight),
                "direction": "NEUTRAL", "final_signal": "NEUTRAL",
                "score": 0.0, "confidence": 0.0, "contribution": 0.0,
                "skipped": f"calc_error: {exc}",
            }, df
        consensus = payload["consensus"]
        final_signal = consensus.get("final_signal") or "NEUTRAL"
        direction = _signal_to_direction(final_signal)
        conf = float(consensus.get("confidence") or 0.0)
        score = float(consensus.get("weighted_score") or 0.0)
        sign = 1 if direction == "LONG" else -1 if direction == "SHORT" else 0
        contribution = sign * (conf / 100.0) * (weight / 100.0)
        return {
            "tf": tf, "weight": int(weight),
            "direction": direction, "final_signal": final_signal,
            "score": round(score, 4), "confidence": round(conf, 2),
            "contribution": round(contribution, 4),
            "indicator_results": payload["indicator_results"],
            "score_data": consensus.get("score_data") or {},
        }, df

    async def _one(symbol: str, market: str) -> None:
        market_cfg = (config["markets"] or {}).get(market) or _base_market_config(market)
        tfs, weights = _resolve_tfs(market, market_cfg)
        if not tfs:
            rows.append({
                "symbol": symbol, "market": market,
                "asset_class": _ASSET_CLASS_MAP.get(market, "EQUITY"),
                "timeframe": "", "direction": "NEUTRAL", "final_signal": "NEUTRAL",
                "weighted_score": 0.0, "confidence": 0.0,
                "last": None, "change_pct": None,
                "top_indicators": [], "indicator_breakdown": [],
                "per_tf": [], "tf_count_scanned": 0, "tf_count_with_signal": 0,
                "skipped": "no active timeframes for market",
            })
            return

        # Schedule every TF in parallel; the semaphore keeps the fetch
        # firehose under control.
        tf_results = await asyncio.gather(
            *(_scan_one_tf(symbol, market, market_cfg, tf, weights.get(tf, 50)) for tf in tfs)
        )

        per_tf_payload: list[dict[str, Any]] = []
        last_df = None
        weight_sum_active = 0.0       # weight of every TF that produced a result
        weight_sum_with_signal = 0.0  # weight of TFs that produced a non-NEUTRAL result
        weighted_contrib = 0.0
        tfs_with_signal = 0
        agg_indicator_results: list[dict[str, Any]] = []
        agg_signal_details: list[dict[str, Any]] = []
        for tf_row, df in tf_results:
            if tf_row is None:
                continue
            per_tf_payload.append({
                k: v for k, v in tf_row.items()
                if k not in {"indicator_results", "score_data"}
            })
            if tf_row.get("skipped"):
                continue
            weight_sum_active += tf_row["weight"] / 100.0
            weighted_contrib += tf_row.get("contribution") or 0.0
            if tf_row["direction"] != "NEUTRAL":
                tfs_with_signal += 1
                weight_sum_with_signal += tf_row["weight"] / 100.0
            if df is not None:
                last_df = df
            # Accumulate the indicator breakdown from each TF; we'll pick
            # the strongest contributors across the whole TF stack below.
            for ind in tf_row.get("indicator_results") or []:
                agg_indicator_results.append({**ind, "_tf": tf_row["tf"]})
            for d in (tf_row.get("score_data") or {}).get("signal_details") or []:
                agg_signal_details.append({**d, "_tf": tf_row["tf"]})

        # All TFs failed → record one skipped row.
        if last_df is None or weight_sum_active <= 0:
            rows.append({
                "symbol": symbol, "market": market,
                "asset_class": _ASSET_CLASS_MAP.get(market, "EQUITY"),
                "timeframe": "·".join(tfs),
                "direction": "NEUTRAL", "final_signal": "NEUTRAL",
                "weighted_score": 0.0, "confidence": 0.0,
                "last": None, "change_pct": None,
                "top_indicators": [], "indicator_breakdown": [],
                "per_tf": per_tf_payload,
                "tf_count_scanned": len(tfs),
                "tf_count_with_signal": 0,
                "skipped": "no usable timeframes",
            })
            return

        # Aggregated direction + confidence (mirrors TBV3 aggregation).
        if weighted_contrib > 0.05:
            direction = "LONG"
        elif weighted_contrib < -0.05:
            direction = "SHORT"
        else:
            direction = "NEUTRAL"
        # Map back to one of the 5 signal labels for the UI badge.
        abs_score = abs(weighted_contrib)
        if direction == "LONG":
            final_signal = "STRONG_BUY" if abs_score >= 0.5 else "BUY"
        elif direction == "SHORT":
            final_signal = "STRONG_SELL" if abs_score >= 0.5 else "SELL"
        else:
            final_signal = "NEUTRAL"
        # Confidence reflects how strongly the *firing* TFs agree. Dividing
        # by the active-signal weight (not the total active weight) means a
        # symbol where 5 of 12 TFs all point SHORT scores high confidence
        # rather than being penalised for the 7 NEUTRAL TFs. Mirrors how
        # TBV3's tfs_str display surfaces conviction across firing TFs.
        denom = max(weight_sum_with_signal, 0.01)
        aggregate_confidence = min(100.0, abs(weighted_contrib) * 100.0 / denom)

        # Top-3 contributing indicators across the whole TF stack.
        top = sorted(
            agg_signal_details,
            key=lambda d: abs(d.get("weighted_score") or 0),
            reverse=True,
        )[:3]
        top_chips = [
            {
                "name": d.get("name"),
                "signal": d.get("signal"),
                "weighted_score": d.get("weighted_score"),
                "reason": d.get("reason"),
                "tf": d.get("_tf"),
            }
            for d in top
        ]
        last, change_pct = _last_change_pct(last_df)
        # Normalized score lives in [-1, +1] and is invariant to TF count
        # — divides the raw weighted_contrib by the sum of weights that
        # actually fired. THIS is the metric used for cross-market sort,
        # because `weighted_score` (the raw sum) scales with how many TFs
        # produced a result. With the unified 12-TF matrix that's now in
        # principle the same upper bound for every market, but failed
        # fetches still skew the raw sum — normalizing keeps the ranking
        # robust to provider hiccups.
        normalized_score = weighted_contrib / max(weight_sum_active, 0.01)
        rows.append({
            "symbol": symbol,
            "market": market,
            "asset_class": _ASSET_CLASS_MAP.get(market, "EQUITY"),
            "timeframe": "·".join(tfs),
            "direction": direction,
            "final_signal": final_signal,
            "weighted_score": round(weighted_contrib, 4),
            "normalized_score": round(normalized_score, 4),
            "confidence": round(aggregate_confidence, 2),
            "last": last,
            "change_pct": change_pct,
            "top_indicators": top_chips,
            "indicator_breakdown": agg_indicator_results,
            "per_tf": per_tf_payload,
            "tf_count_scanned": len(tfs),
            "tf_count_with_signal": tfs_with_signal,
            "skipped": None,
        })

    tasks: list[asyncio.Task[None]] = []
    universes_by_market: dict[str, list[str]] = {}
    total_symbols = 0
    for market in selected:
        universe = _resolve_universe(market, config)
        if req.max_symbols_per_market:
            universe = universe[: req.max_symbols_per_market]
        universes_by_market[market] = universe
        per_market[market] = {"requested": len(universe), "completed": 0, "skipped": 0}
        total_symbols += len(universe)

    # Publish initial progress so the UI can show "0 / total" the moment
    # it starts polling — without this the first poll lands during task
    # creation and would briefly see status=idle from a previous run.
    _progress_update(
        status="running",
        total=total_symbols,
        completed=0,
        in_flight=0,
        skipped=0,
        markets=list(selected),
        started_at=datetime.now(timezone.utc).isoformat(),
        elapsed_ms=0.0,
        current_symbol="",
        current_market="",
    )

    progress_lock = asyncio.Lock()

    async def _one_with_progress(symbol: str, market: str) -> None:
        # Bump in_flight on entry, completed on exit. We don't lock around
        # the inner `_one` call because the scan is per-task anyway; the
        # asyncio lock prevents two coroutines stomping on the same counter
        # bump (asyncio is cooperative but ``+=`` reads-then-writes), and
        # ``_PROGRESS_LOCK`` (C12) makes the same write atomic with respect
        # to ``get_scan_progress`` reads coming from the route layer.
        async with progress_lock:
            with _PROGRESS_LOCK:
                _SCAN_PROGRESS["in_flight"] = (_SCAN_PROGRESS.get("in_flight") or 0) + 1
        try:
            await _one(symbol, market)
            async with progress_lock:
                with _PROGRESS_LOCK:
                    _SCAN_PROGRESS["completed"] = (_SCAN_PROGRESS.get("completed") or 0) + 1
                    _SCAN_PROGRESS["current_symbol"] = symbol
                    _SCAN_PROGRESS["current_market"] = market
        except Exception:  # noqa: BLE001 — count and re-raise to gather
            async with progress_lock:
                with _PROGRESS_LOCK:
                    _SCAN_PROGRESS["skipped"] = (_SCAN_PROGRESS.get("skipped") or 0) + 1
                    _SCAN_PROGRESS["completed"] = (_SCAN_PROGRESS.get("completed") or 0) + 1
            raise
        finally:
            async with progress_lock:
                with _PROGRESS_LOCK:
                    _SCAN_PROGRESS["in_flight"] = max(0, (_SCAN_PROGRESS.get("in_flight") or 0) - 1)

    for market in selected:
        for symbol in universes_by_market[market]:
            tasks.append(asyncio.create_task(_one_with_progress(symbol, market)))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    # Roll up the per-market counters.
    for r in rows:
        bucket = per_market.setdefault(r["market"], {"requested": 0, "completed": 0, "skipped": 0})
        if r.get("skipped"):
            bucket["skipped"] += 1
        else:
            bucket["completed"] += 1

    # Apply min_confidence / only_signals filters AFTER aggregation so the
    # counts still reflect how many symbols we actually fetched.
    filtered = [
        r for r in rows
        if not r.get("skipped")
        and r["confidence"] >= req.min_confidence
        and (not req.only_signals or r["direction"] != "NEUTRAL")
    ]
    # Sort by the TF-count-invariant ``normalized_score`` so cross-market
    # rank is fair: a 12-TF crypto row no longer beats a 12-TF equity row
    # purely because more TFs produced data. Tie-break on raw confidence
    # so symbols with equal conviction but more contributing TFs surface
    # first.
    filtered.sort(
        key=lambda r: (abs(r.get("normalized_score", 0.0)), r.get("confidence", 0.0)),
        reverse=True,
    )
    top_rows = filtered[: req.top_n] if req.top_n else filtered

    elapsed_ms = (time.perf_counter() - started) * 1000
    result = MisScanResult(
        rows=top_rows,
        markets=selected,
        per_market_counts=per_market,
        warnings=warnings,
        elapsed_ms=elapsed_ms,
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    # Flip progress to ``done`` so the polling UI can stop. We keep the
    # final snapshot around (not cleared to ``idle``) so a poll that
    # lands just after the POST returns still sees a coherent end state.
    _progress_update(
        status="done",
        completed=total_symbols,
        in_flight=0,
        elapsed_ms=elapsed_ms,
    )
    return result


def _signal_to_direction(signal: str) -> str:
    s = (signal or "").upper()
    if s in {"STRONG_BUY", "BUY"}:
        return "LONG"
    if s in {"STRONG_SELL", "SELL"}:
        return "SHORT"
    return "NEUTRAL"


# ── Public introspection helpers (consumed by the route family) ──────────

def list_indicator_names() -> list[str]:
    """Return the indicator names MIS knows weights/thresholds for."""
    return sorted(DEFAULT_INDICATOR_WEIGHTS.keys())


def list_markets() -> list[dict[str, Any]]:
    """Return market metadata for the UI (size + TF set + ZAK weights)."""
    config = load_mis_config()
    out: list[dict[str, Any]] = []
    for m in MIS_MARKETS:
        universe = _resolve_universe(m, config)
        cfg = (config.get("markets") or {}).get(m) or {}
        active_set = cfg.get("tf_set") or list(MARKET_DEFAULT_TFS.get(m, []))
        weights = {**MARKET_TF_WEIGHTS.get(m, {}), **(cfg.get("tf_weights") or {})}
        out.append({
            "key": m,
            "default_timeframe": MIS_DEFAULT_TIMEFRAMES.get(m, "1d"),
            "size": len(universe),
            "asset_class": _ASSET_CLASS_MAP.get(m, m),
            "default_tfs": list(MARKET_DEFAULT_TFS.get(m, [])),
            "active_tfs": list(active_set),
            "tf_weights": {tf: int(weights.get(tf, 50)) for tf in MARKET_DEFAULT_TFS.get(m, [])},
        })
    return out


__all__ = [
    "CONFIG_PATH_NAME",
    "MARKET_DEFAULT_TFS",
    "MARKET_TF_WEIGHTS",
    "MIS_DEFAULT_TIMEFRAMES",
    "MIS_MARKETS",
    "MIS_UNIVERSES",
    "MisScanRequest",
    "MisScanResult",
    "MisScanRow",
    "STABLECOIN_BASES",
    "get_scan_progress",
    "list_indicator_names",
    "list_markets",
    "load_mis_config",
    "run_mis_scan",
    "save_mis_config",
]
