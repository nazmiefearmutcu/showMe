"""Scanner Agent — Phase A (universe) + Phase B (ZAK-weighted coarse scan).

Round-17 ships a self-contained service that wraps the ShowMe ZAK matrix
concept across multiple asset classes. We deliberately *don't* import
``bot_service.ScannerService`` (it owns live bot state); instead we re-use
the lighter ``src.data_sources`` adapters via the existing
``function_factory`` to fetch OHLCV.

Phases:

1. **A — Universe Selection.** Given an intent (NL string + optional
   structured filters), pick a target universe. Round 17 ships static
   universe lists per asset class; Round 19's Planner LLM swaps them for
   intent-driven selection.

2. **B — Coarse Scan.** For each symbol × top-3 ZAK timeframes, pull
   recent OHLCV and run a deterministic consensus signal over RSI(14),
   MACD(12,26,9) and 50/200-MA cross. Each signal × ZAK weight contributes
   to the symbol's final score.

Round-17 covers Phases A+B with a shared ConsensusEngine. Phases C-E
(fine scan, narrative, attribution) land in subsequent rounds and slot
in via the ``ScannerResult.phases`` envelope.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

LOG = logging.getLogger("showme.scanner")

# ── ZAK matrix (per asset class) ──────────────────────────────────────────
# Numbers calibrated from ShowMe §bot_service._ZAK and adjusted per class so
# longer TFs dominate equity/macro while shorter TFs matter more for FX.

ZAK_MATRIX: dict[str, dict[str, int]] = {
    "EQUITY": {"1mo": 90, "1wk": 80, "1d": 70, "1h": 50, "30m": 35, "15m": 25},
    "ETF":    {"1mo": 90, "1wk": 80, "1d": 70, "1h": 50, "30m": 35, "15m": 25},
    "CRYPTO": {"1d": 95, "12h": 90, "8h": 85, "4h": 75, "1h": 58, "15m": 38},
    "FX":     {"1d": 70, "4h": 60, "1h": 55, "30m": 45, "15m": 35, "5m": 22},
    "COMMODITY": {"1mo": 88, "1wk": 80, "1d": 72, "1h": 50, "30m": 35, "15m": 22},
    "BOND":   {"1mo": 92, "1wk": 84, "1d": 70},
    "MACRO":  {"1mo": 92, "1wk": 84, "1d": 70},
}


# ── Built-in universes ────────────────────────────────────────────────────
# Static for Round 17 (Phase A NL parser arrives in Round 19).

UNIVERSES: dict[str, list[str]] = {
    "EQUITY:US:LARGE": [
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "JPM",
        "V", "MA", "JNJ", "WMT", "PG", "HD", "UNH", "DIS", "AVGO", "XOM",
        "BAC", "CVX",
    ],
    "EQUITY:US:SP500_TOP30": [
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "JPM",
        "V", "MA", "JNJ", "WMT", "PG", "HD", "UNH", "DIS", "AVGO", "XOM",
        "BAC", "CVX", "ORCL", "ABBV", "KO", "PEP", "MRK", "TMO", "COST",
        "CSCO", "ACN", "ADBE",
    ],
    "CRYPTO:MAJORS": [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT",
        "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
    ],
    "FX:G10": [
        "EURUSD=X", "GBPUSD=X", "USDJPY=X", "USDCHF=X", "AUDUSD=X",
        "USDCAD=X", "NZDUSD=X", "USDSEK=X", "USDNOK=X", "EURGBP=X",
    ],
    "COMMODITY:CORE": [
        "GC=F", "SI=F", "CL=F", "BZ=F", "NG=F", "HG=F", "PL=F", "ZC=F",
    ],
    "ETF:US:CORE": [
        "SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "TLT", "HYG", "GLD",
        "SLV", "USO", "VNQ", "XLE", "XLF", "XLK",
    ],
}


def list_universes() -> list[dict[str, Any]]:
    return [
        {"key": k, "asset_class": k.split(":")[0], "size": len(v)}
        for k, v in UNIVERSES.items()
    ]


# ── Consensus engine (pure-numpy, no SciPy / TA-lib) ──────────────────────

def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2.0 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(out[-1] + k * (v - out[-1]))
    return out


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0 and avg_gain == 0:
        return 50.0  # flat market is neutral, not overbought
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _macd(closes: list[float]) -> tuple[float, float, float] | None:
    if len(closes) < 35:
        return None
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    # Lengths match by construction: ema12[-len(ema26):] has the same length as ema26.
    macd_line = [a - b for a, b in zip(ema12[-len(ema26):], ema26, strict=True)]
    signal = _ema(macd_line, 9)
    return macd_line[-1], signal[-1], macd_line[-1] - signal[-1]


def _ma_cross(closes: list[float]) -> int:
    if len(closes) < 200:
        return 0
    short = sum(closes[-50:]) / 50
    long_ = sum(closes[-200:]) / 200
    if short > long_ * 1.005:
        return 1
    if short < long_ * 0.995:
        return -1
    return 0


def consensus_signal(closes: list[float]) -> dict[str, Any]:
    """Return {direction, confidence, components} given a closing-price series.

    Confidence ∈ [0, 100]. Direction ∈ {LONG, SHORT, NEUTRAL}.
    """
    rsi = _rsi(closes)
    macd = _macd(closes)
    ma = _ma_cross(closes)
    score = 0.0
    pieces: list[dict[str, Any]] = []
    if rsi is not None:
        rsi_score = 0
        if rsi < 30:
            rsi_score = 1
        elif rsi > 70:
            rsi_score = -1
        elif rsi < 45:
            rsi_score = 0.4
        elif rsi > 55:
            rsi_score = -0.4
        score += rsi_score
        pieces.append({"name": "rsi", "value": rsi, "score": rsi_score})
    if macd is not None:
        line, sig, hist = macd
        macd_score = 1 if hist > 0 else -1 if hist < 0 else 0
        score += macd_score * 0.8
        pieces.append({
            "name": "macd", "line": line, "signal": sig, "hist": hist,
            "score": macd_score,
        })
    score += ma * 0.6
    pieces.append({"name": "ma_cross", "score": ma})
    direction = "LONG" if score > 0.5 else "SHORT" if score < -0.5 else "NEUTRAL"
    confidence = min(100.0, abs(score) / 2.4 * 100.0)
    return {
        "direction": direction,
        "confidence": round(confidence, 2),
        "score": round(score, 4),
        "components": pieces,
    }


# ── Phase A — Universe selection ──────────────────────────────────────────

@dataclass
class ScanRequest:
    intent: str = ""
    universe: str | None = None
    asset_class: str | None = None
    timeframes: list[str] | None = None
    top_n: int = 20
    # Comma-joined list of phases to run, e.g. "A,B,C,D". Default = "A,B".
    phases: str = "A,B"
    # Top-K from Phase B fed into Phase C (defaults to min(top_n, 8)).
    fine_top_k: int | None = None


@dataclass
class PhaseResult:
    name: str
    started_at: float
    elapsed_ms: float
    output: dict[str, Any]


@dataclass
class ScannerResult:
    intent: str
    universe_key: str
    asset_class: str
    timeframes: list[str]
    rows: list[dict[str, Any]]
    phases: list[PhaseResult] = field(default_factory=list)
    elapsed_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "phases": [asdict(p) for p in self.phases],
        }


def _intent_universe(intent: str) -> tuple[str, str]:
    """Naive Phase-A NL → universe routing. Round 19 swaps in the LLM."""
    needle = intent.lower()
    if "crypto" in needle or "bitcoin" in needle or "btc" in needle:
        return "CRYPTO:MAJORS", "CRYPTO"
    if any(k in needle for k in ("fx", "currency", "forex", "eur/usd")):
        return "FX:G10", "FX"
    if any(k in needle for k in ("oil", "gold", "commodity", "wheat")):
        return "COMMODITY:CORE", "COMMODITY"
    if "etf" in needle:
        return "ETF:US:CORE", "ETF"
    return "EQUITY:US:LARGE", "EQUITY"


def select_universe(req: ScanRequest) -> tuple[str, str, list[str]]:
    if req.universe and req.universe in UNIVERSES:
        ac = req.universe.split(":")[0]
        return req.universe, ac, list(UNIVERSES[req.universe])
    if req.asset_class:
        for key, syms in UNIVERSES.items():
            if key.startswith(f"{req.asset_class.upper()}:"):
                return key, req.asset_class.upper(), list(syms)
    key, ac = _intent_universe(req.intent)
    return key, ac, list(UNIVERSES[key])


# ── Phase B — Coarse scan ────────────────────────────────────────────────

async def _fetch_closes(deps: Any, symbol: str, asset_class: str,
                        timeframe: str, days: int) -> list[float]:
    """Best-effort OHLCV close-series fetch via ShowMe adapters."""
    try:
        from datetime import datetime, timedelta, timezone
        from showme.engine.core.base_data_source import DataKind, DataRequest
        from showme.engine.core.instrument import AssetClass, Instrument
    except Exception as exc:  # noqa: BLE001
        LOG.warning("ShowMe imports unavailable: %s", exc)
        return []
    ac_map = {
        "EQUITY": AssetClass.EQUITY,
        "ETF": AssetClass.ETF if hasattr(AssetClass, "ETF") else AssetClass.EQUITY,
        "CRYPTO": AssetClass.CRYPTO,
        "FX": AssetClass.FX,
        "COMMODITY": AssetClass.COMMODITY,
    }
    inst = Instrument(symbol=symbol, asset_class=ac_map.get(asset_class, AssetClass.EQUITY))
    adapter = None
    if asset_class == "CRYPTO":
        adapter = getattr(deps, "ccxt_failover", None) or getattr(deps, "coingecko", None)
    if adapter is None:
        adapter = getattr(deps, "yfinance", None)
    if adapter is None:
        return []
    try:
        df = await adapter.fetch(DataRequest(
            kind=DataKind.OHLCV, instrument=inst,
            start=datetime.now(timezone.utc) - timedelta(days=days),
            interval=timeframe,
        ))
    except Exception as exc:  # noqa: BLE001
        LOG.debug("OHLCV fetch failed %s/%s: %s", symbol, timeframe, exc)
        return []
    if df is None:
        return []
    try:
        closes = [float(x) for x in df["close"].dropna().tolist()]
        return closes[-260:]  # cap so MA200 is the longest window we ever need
    except Exception:
        return []


async def _scan_one(deps: Any, symbol: str, asset_class: str,
                    zak: dict[str, int], days: int) -> dict[str, Any]:
    contributions: list[dict[str, Any]] = []
    aggregate = 0.0
    weight_sum = 0.0
    used_tfs: list[str] = []
    for tf, weight in zak.items():
        closes = await _fetch_closes(deps, symbol, asset_class, tf, days)
        if len(closes) < 35:
            continue
        sig = consensus_signal(closes)
        # Direction sign × confidence × ZAK weight
        sign = 1 if sig["direction"] == "LONG" else -1 if sig["direction"] == "SHORT" else 0
        contrib = sign * (sig["confidence"] / 100.0) * (weight / 100.0)
        aggregate += contrib
        weight_sum += weight
        used_tfs.append(tf)
        contributions.append({
            "tf": tf, "weight": weight, "direction": sig["direction"],
            "confidence": sig["confidence"], "contribution": round(contrib, 4),
        })
    if not contributions:
        return {"symbol": symbol, "asset_class": asset_class,
                "skipped": "no usable timeframes"}
    direction = "LONG" if aggregate > 0.05 else "SHORT" if aggregate < -0.05 else "NEUTRAL"
    confidence = min(100.0, abs(aggregate) * 100.0 / max(weight_sum / 100.0, 1.0))
    return {
        "symbol": symbol,
        "asset_class": asset_class,
        "direction": direction,
        "score": round(aggregate, 4),
        "confidence": round(confidence, 2),
        "timeframes": used_tfs,
        "contributions": contributions,
    }


async def run_scan(req: ScanRequest, deps: Any) -> ScannerResult:
    started = time.perf_counter()
    phases: list[PhaseResult] = []

    # Phase A — universe selection.
    a_started = time.perf_counter()
    universe_key, asset_class, symbols = select_universe(req)
    if asset_class.upper() not in ZAK_MATRIX:
        asset_class = "EQUITY"
    zak_full = ZAK_MATRIX[asset_class.upper()]
    if req.timeframes:
        zak = {tf: zak_full.get(tf, 50) for tf in req.timeframes}
    else:
        # Use top 3 ZAK timeframes for the coarse pass.
        zak = dict(sorted(zak_full.items(), key=lambda kv: -kv[1])[:3])
    phases.append(PhaseResult(
        name="A.universe",
        started_at=a_started,
        elapsed_ms=(time.perf_counter() - a_started) * 1000,
        output={
            "universe_key": universe_key,
            "asset_class": asset_class,
            "n_symbols": len(symbols),
            "timeframes": list(zak.keys()),
        },
    ))

    # Phase B — coarse scan.
    b_started = time.perf_counter()
    days = 365 if asset_class in ("EQUITY", "ETF", "BOND", "COMMODITY", "MACRO") else 90
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    sem = asyncio.Semaphore(8)

    async def _task(sym: str) -> None:
        async with sem:
            try:
                row = await _scan_one(deps, sym, asset_class, zak, days)
                rows.append(row)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"{sym}: {exc}")

    await asyncio.gather(*(_task(s) for s in symbols))
    rows.sort(key=lambda r: -abs(r.get("score") or 0))
    rows_top = rows[: req.top_n]
    phases.append(PhaseResult(
        name="B.coarse_scan",
        started_at=b_started,
        elapsed_ms=(time.perf_counter() - b_started) * 1000,
        output={
            "n_evaluated": len(symbols),
            "n_with_signal": sum(1 for r in rows if "skipped" not in r),
            "top_n": len(rows_top),
        },
    ))

    requested = {p.strip().upper() for p in (req.phases or "A,B").split(",") if p.strip()}

    # Phase C — fine scan: shorter timeframes + last-quote overextension.
    if "C" in requested:
        c_started = time.perf_counter()
        fine_zak = dict(sorted(zak_full.items(), key=lambda kv: kv[1])[:4])
        # When the user asks for a manual TF override on Phase B, prefer the
        # short end of *that* set for Phase C instead.
        if req.timeframes:
            fine_zak = {tf: zak_full.get(tf, 50) for tf in req.timeframes[-3:]}
        k = req.fine_top_k or min(req.top_n, 8)
        targets = [r for r in rows_top if "skipped" not in r][:k]
        await _phase_c(targets, deps, asset_class, fine_zak, warnings)
        phases.append(PhaseResult(
            name="C.fine_scan",
            started_at=c_started,
            elapsed_ms=(time.perf_counter() - c_started) * 1000,
            output={
                "fine_top_k": len(targets),
                "fine_timeframes": list(fine_zak.keys()),
            },
        ))

    # Phase D — risk overlay against the live portfolio.
    if "D" in requested:
        d_started = time.perf_counter()
        overlay = _phase_d_overlay(rows_top, deps, warnings)
        phases.append(PhaseResult(
            name="D.risk_overlay",
            started_at=d_started,
            elapsed_ms=(time.perf_counter() - d_started) * 1000,
            output=overlay,
        ))

    return ScannerResult(
        intent=req.intent,
        universe_key=universe_key,
        asset_class=asset_class,
        timeframes=list(zak.keys()),
        rows=rows_top,
        phases=phases,
        elapsed_ms=(time.perf_counter() - started) * 1000,
        warnings=warnings,
    )


# ── Phase C — Fine scan + overextension overlay ───────────────────────────

async def _last_quote(deps: Any, symbol: str, asset_class: str) -> dict[str, Any]:
    """Best-effort last-tick fetch for the overextension snapshot."""
    try:
        from showme.engine.core.base_data_source import DataKind, DataRequest
        from showme.engine.core.instrument import AssetClass, Instrument
    except (ImportError, ModuleNotFoundError) as exc:
        # Per PY-LINT-05 P1: only catch import errors here. AttributeError
        # from a renamed symbol must still surface so the overextension
        # overlay isn't silently dropped.
        LOG.debug("scanner._last_quote: engine adapters unavailable: %s", exc)
        return {}
    ac_map = {
        "EQUITY": AssetClass.EQUITY,
        "ETF": AssetClass.ETF if hasattr(AssetClass, "ETF") else AssetClass.EQUITY,
        "CRYPTO": AssetClass.CRYPTO,
        "FX": AssetClass.FX,
        "COMMODITY": AssetClass.COMMODITY,
    }
    inst = Instrument(symbol=symbol,
                      asset_class=ac_map.get(asset_class, AssetClass.EQUITY))
    adapter = None
    if asset_class == "CRYPTO":
        adapter = getattr(deps, "ccxt_failover", None) or getattr(deps, "coingecko", None)
    if adapter is None:
        adapter = getattr(deps, "yfinance", None)
    if adapter is None:
        return {}
    try:
        q = await adapter.fetch(DataRequest(kind=DataKind.QUOTE, instrument=inst))
    except Exception as exc:  # noqa: BLE001
        # Per PY-LINT-05 P1: surface the failure to operators rather than
        # silently encoding it as a result-shaped dict that callers ignore.
        LOG.warning("scanner._last_quote failed for %s: %s", symbol, exc)
        return {}
    if q is None:
        return {}
    last = getattr(q, "last", None)
    prev_close = getattr(q, "previous_close", None) or getattr(q, "prev_close", None)
    change_pct = None
    if last is not None and prev_close:
        try:
            change_pct = (float(last) / float(prev_close) - 1.0) * 100.0
        except Exception:
            change_pct = None
    return {
        "last": float(last) if last is not None else None,
        "previous_close": float(prev_close) if prev_close is not None else None,
        "change_pct": change_pct,
    }


def _overextension_score(closes: list[float], change_pct: float | None) -> dict[str, Any]:
    """How far is `last close` from its recent moving average?

    Returns z-score against the last 30 closes and an "overbought / oversold"
    label when |z| >= 2. Combines with the day's `change_pct` (if available)
    for a single overextension flag.
    """
    if len(closes) < 30 or any(not isinstance(c, (int, float)) for c in closes[-30:]):
        return {}
    window = closes[-30:]
    mean = sum(window) / len(window)
    var = sum((c - mean) ** 2 for c in window) / len(window)
    sd = var ** 0.5
    z = (closes[-1] - mean) / sd if sd > 0 else 0.0
    label = "OVERBOUGHT" if z >= 2.0 else "OVERSOLD" if z <= -2.0 else "OK"
    overextended = label != "OK" or (
        change_pct is not None and abs(change_pct) >= 5.0
    )
    return {
        "z_score_30d": round(z, 3),
        "deviation_label": label,
        "overextended": overextended,
        "change_pct_today": round(change_pct, 3) if change_pct is not None else None,
    }


async def _phase_c(
    targets: list[dict[str, Any]],
    deps: Any,
    asset_class: str,
    fine_zak: dict[str, int],
    warnings: list[str],
) -> None:
    """Mutate `targets` in-place with a `fine` block per row."""

    async def _enrich(row: dict[str, Any]) -> None:
        sym = row["symbol"]
        try:
            quote = await _last_quote(deps, sym, asset_class)
        except Exception as exc:  # noqa: BLE001
            quote = {"error": str(exc)}
        # Pull a 30-bar series at the highest-resolution TF in fine_zak.
        sub_tf = next(iter(fine_zak), "1d")
        days = 14 if sub_tf in ("15m", "5m", "1m", "30m") else 60
        closes = await _fetch_closes(deps, sym, asset_class, sub_tf, days)
        oext = _overextension_score(closes, quote.get("change_pct"))
        # Per-fine-TF consensus (mini Phase B repeat at lower resolution).
        fine_contribs: list[dict[str, Any]] = []
        for tf, weight in fine_zak.items():
            cl = await _fetch_closes(deps, sym, asset_class, tf, days)
            if len(cl) < 35:
                continue
            sig = consensus_signal(cl)
            sign = 1 if sig["direction"] == "LONG" else -1 if sig["direction"] == "SHORT" else 0
            contrib = sign * (sig["confidence"] / 100.0) * (weight / 100.0)
            fine_contribs.append({
                "tf": tf, "weight": weight,
                "direction": sig["direction"],
                "confidence": sig["confidence"],
                "contribution": round(contrib, 4),
            })
        row["fine"] = {
            "quote": quote,
            "overextension": oext,
            "contributions": fine_contribs,
        }

    sem = asyncio.Semaphore(6)

    async def _wrap(r: dict[str, Any]) -> None:
        async with sem:
            try:
                await _enrich(r)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"phase_c {r['symbol']}: {exc}")

    await asyncio.gather(*(_wrap(r) for r in targets))


# ── Phase D — Portfolio risk overlay (deterministic) ─────────────────────

def _phase_d_overlay(
    rows_top: list[dict[str, Any]],
    deps: Any,
    warnings: list[str],
) -> dict[str, Any]:
    """Stamp a `position_overlap` flag per row + a portfolio-level summary.

    Symbols already in the portfolio get `held=True`; same-asset-class
    overlap is reported as a concentration warning. Fully deterministic —
    no live yfinance calls, so safe to run on every scan.
    """
    overlap_flags: dict[str, dict[str, Any]] = {}
    portfolio_symbols: set[str] = set()
    by_class: dict[str, int] = {}
    try:
        ps_mod = importlib.import_module("showme.engine.portfolio.state")
        ps = ps_mod.PortfolioState()
        for p in getattr(ps, "positions", []) or []:
            sym = getattr(getattr(p, "instrument", None), "symbol", None)
            if not sym:
                continue
            portfolio_symbols.add(sym.upper())
            ac = getattr(getattr(p, "instrument", None), "asset_class", None)
            ac_name = getattr(ac, "value", str(ac))
            by_class[ac_name] = by_class.get(ac_name, 0) + 1
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"phase_d portfolio: {exc}")
    new_long = 0
    new_short = 0
    held = 0
    for row in rows_top:
        sym = (row.get("symbol") or "").upper()
        is_held = sym in portfolio_symbols
        flag = {"held": is_held}
        # Concentration: same asset class as anything already held.
        ac = (row.get("asset_class") or "").upper()
        if by_class.get(ac, 0) >= 5 and not is_held:
            flag["high_concentration"] = True
        overlap_flags[sym] = flag
        row["position_overlap"] = flag
        if is_held:
            held += 1
        elif row.get("direction") == "LONG":
            new_long += 1
        elif row.get("direction") == "SHORT":
            new_short += 1
    return {
        "portfolio_symbols": len(portfolio_symbols),
        "by_class": by_class,
        "held_in_results": held,
        "new_long": new_long,
        "new_short": new_short,
    }


import importlib  # noqa: E402  (placed at bottom to keep top-level concise)
