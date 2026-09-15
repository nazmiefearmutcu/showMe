"""Live, keyless Stocktwits sentiment fallback for the X-sentiment chain.

The primary social-sentiment source is X (``x_spontaneous`` search →
syndication hydration → the bundled RoBERTa classifier in ``x_analysis``).
When that chain is unavailable — search engines blocked from the local
network, a Cloudflare challenge on nitter/jina, or a missing model bundle —
the home gauge would silently sit at "Neutral 0%" forever. This module keeps
the gauge honest and alive by reading Stocktwits' public, unauthenticated
symbol stream, where most messages carry the author's own Bullish/Bearish tag.

Design rules (mirrors ``x_analysis`` doctrine):
  * Only messages WITH a Bullish/Bearish label contribute to the score. No
    lexicon guessing, no unlabeled-chatter inflation — never invent a verdict
    from noise. Below ``MIN_LABELED_FOR_VERDICT`` labelled posts the caller
    gets ``None`` (no chip) instead of a fake number.
  * Stocktwits sits behind Cloudflare; a plain ``httpx`` client is challenged
    after a request burst. We use ``curl_cffi`` with Chrome TLS
    impersonation when available and fall back to ``httpx`` otherwise (the
    fallback may fail closed — the failure is surfaced, never faked).
  * Responses are cached per symbol (default 5 min) and live requests are
    politely spaced (>= ~3/s across the process) so the 60s dashboard refresh
    cannot hammer the public endpoint.

Every payload states its source explicitly (``"source": "stocktwits"``).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

LOG = logging.getLogger("showme.stocktwits")

BASE_URL = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
DEFAULT_TIMEOUT_SECONDS = 12.0
DEFAULT_CACHE_TTL_SECONDS = 300.0
# Failures are cached for a shorter window so a transient challenge/blip
# recovers quickly without letting a refresh burst retry-loop.
FAILURE_CACHE_TTL_SECONDS = 45.0
MIN_REQUEST_INTERVAL_SECONDS = 0.35
MIN_LABELED_FOR_VERDICT = 5

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15"
)

# Bases that Stocktwits lists in its crypto namespace ("<BASE>.X"). The
# per-symbol stream simply 404s for anything else, so a miss is fail-closed.
_CRYPTO_BASES = frozenset(
    {
        "BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT", "LTC",
        "BCH", "MATIC", "SHIB", "UNI", "ATOM", "NEAR", "APT", "ARB", "OP", "FIL",
        "XLM", "TRX", "ALGO", "ETC", "HBAR", "SUI", "TON", "PEPE", "INJ", "SEI",
        "TIA", "RNDR", "AAVE", "MKR", "CRV", "SAND", "MANA", "GRT", "IMX",
    }
)

# Two locks on purpose: the throttle sleep must NOT block cache reads for the
# other symbols in a 12-symbol fan-out (they can proceed while one sleeps).
_cache_lock = threading.Lock()
_throttle_lock = threading.Lock()
_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
_last_request_at = 0.0


def to_stocktwits_symbol(symbol: str) -> str | None:
    """Map a showMe symbol to Stocktwits' namespace.

    Accepted input shapes: ``AAPL``, ``BTCUSDT``, ``BTC/USDT``, ``BTC-USD``,
    ``BTC.X``. Crypto bases are mapped to Stocktwits' ``<BASE>.X`` form;
    equities/ETFs pass through unchanged. Returns ``None`` only for empty
    input (everything else is attempted upstream and fails closed on 404).
    """
    raw = (symbol or "").strip().upper()
    if not raw:
        return None
    if raw.endswith(".X"):
        return raw
    compact = raw.replace("/", "").replace("-", "").replace("_", "").replace(" ", "")
    for quote_ccy in ("USDT", "USDC", "USD"):
        if compact.endswith(quote_ccy):
            base = compact[: -len(quote_ccy)]
            if base in _CRYPTO_BASES:
                return f"{base}.X"
            break
    return raw


def _http_get_json(url: str, timeout: float) -> dict[str, Any]:
    """GET ``url`` as JSON.

    curl_cffi + Chrome impersonation first (beats the Cloudflare challenge
    that plain clients hit); ``httpx`` fallback for builds without curl_cffi.
    Raises ``RuntimeError`` on any non-200 so callers cache the failure.
    """
    try:
        from curl_cffi import requests as curl_requests  # type: ignore[import-not-found]

        response = curl_requests.get(url, impersonate="chrome", timeout=timeout)
        if response.status_code != 200:
            raise RuntimeError(f"stocktwits http {response.status_code}")
        return response.json()
    except ImportError:
        pass
    import httpx

    with httpx.Client(
        timeout=timeout,
        headers={"User-Agent": _USER_AGENT},
        follow_redirects=True,
    ) as client:
        response = client.get(url)
        if response.status_code != 200:
            raise RuntimeError(f"stocktwits http {response.status_code}")
        return response.json()


def _throttle() -> None:
    """Space live request STARTS so a fan-out stays under the radar."""
    global _last_request_at
    with _throttle_lock:
        now = time.monotonic()
        wait = MIN_REQUEST_INTERVAL_SECONDS - (now - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def _mood_for_score(score: float) -> str:
    if score > 0.18:
        return "bullish"
    if score < -0.18:
        return "bearish"
    return "mixed"


def _aggregate(
    symbol: str,
    messages: list[dict[str, Any]],
    *,
    st_symbol: str,
) -> dict[str, Any] | None:
    """Fold labelled Stocktwits messages into the X-symbol-chip shape.

    Returns ``None`` when fewer than ``MIN_LABELED_FOR_VERDICT`` labelled
    posts exist — the caller must not fabricate a reading from noise.
    """
    labeled = 0
    bullish = 0
    bearish = 0
    examples: dict[str, list[dict[str, Any]]] = {"bullish": [], "bearish": []}
    for msg in messages:
        sentiment = (
            ((msg.get("entities") or {}).get("sentiment") or {}).get("basic") or ""
        ).strip().lower()
        if sentiment not in {"bullish", "bearish"}:
            continue
        labeled += 1
        if sentiment == "bullish":
            bullish += 1
        else:
            bearish += 1
        if len(examples[sentiment]) < 3:
            user = (msg.get("user") or {}).get("username") or "stocktwits"
            likes = (msg.get("likes") or {}).get("total") or 0
            try:
                likes_int = int(likes)
            except (TypeError, ValueError):
                likes_int = 0
            mid = msg.get("id")
            examples[sentiment].append(
                {
                    "user": user,
                    "text": str(msg.get("body") or "")[:280],
                    "likes": likes_int,
                    "retweets": 0,
                    "url": f"https://stocktwits.com/{user}/message/{mid}" if mid else "",
                    "score": 1.0 if sentiment == "bullish" else -1.0,
                    "emotion": "",
                    "topic": "",
                    "date": str(msg.get("created_at") or ""),
                }
            )
    if labeled < MIN_LABELED_FOR_VERDICT:
        return None
    score = round((bullish - bearish) / labeled, 3)
    confidence = round(min(1.0, labeled / 20.0), 3)
    mood = _mood_for_score(score)
    scanned = len(messages)
    summary = (
        f"Stocktwits: {labeled} labelled posts out of the latest {scanned} "
        f"({bullish} bullish / {bearish} bearish) — mood {mood}, net {score:+.2f}."
    )
    return {
        "symbol": symbol,
        "ok": True,
        "source": "stocktwits",
        "stocktwits_symbol": st_symbol,
        "post_count": labeled,
        "messages_scanned": scanned,
        "mood": mood,
        "summary": summary,
        "summary_tr": summary,
        "bullish_score": score,
        "confidence": confidence,
        "dominant": {"sentiment": mood, "emotion": "", "topic": ""},
        "distributions": {
            "sentiment_pct": {
                "bullish": round(bullish / labeled * 100, 1),
                "bearish": round(bearish / labeled * 100, 1),
            },
            "emotion_pct": {},
            "topic_pct": {},
        },
        "examples": examples,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "methodology": (
            "Author-labelled Bullish/Bearish tags on the public Stocktwits "
            "symbol stream, scored as (bullish - bearish) / labelled. "
            "Unlabelled messages are excluded."
        ),
    }


def fetch_symbol_chip(
    symbol: str,
    *,
    timeout: float | None = None,
    cache_ttl: float | None = None,
) -> dict[str, Any] | None:
    """Return a live Stocktwits sentiment chip for ``symbol`` or ``None``.

    Cache-first; on a miss the request is politely throttled. Both successes
    and failures are cached (failures for a shorter window) so callers are
    free to poll this from a 60s dashboard refresh.
    """
    st_symbol = to_stocktwits_symbol(symbol)
    if not st_symbol:
        return None
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(st_symbol)
    if entry is not None and entry[0] > now:
        cached = entry[1]
        if cached is None:
            return None
        return {**cached, "symbol": symbol}

    _throttle()
    chip: dict[str, Any] | None = None
    ttl = cache_ttl if cache_ttl is not None else DEFAULT_CACHE_TTL_SECONDS
    try:
        payload = _http_get_json(
            BASE_URL.format(symbol=quote(st_symbol)),
            timeout if timeout is not None else DEFAULT_TIMEOUT_SECONDS,
        )
        messages = payload.get("messages") or []
        if isinstance(messages, list):
            chip = _aggregate(symbol, messages, st_symbol=st_symbol)
    except Exception as exc:  # noqa: BLE001
        LOG.info("stocktwits fetch failed for %s (%s): %s", symbol, st_symbol, exc)
        ttl = FAILURE_CACHE_TTL_SECONDS
        chip = None

    with _cache_lock:
        _cache[st_symbol] = (time.monotonic() + ttl, chip)
    if chip is None:
        return None
    return {**chip, "symbol": symbol}


def clear_cache() -> None:
    """Test/ops hook — drop every cached response."""
    with _cache_lock:
        _cache.clear()


__all__ = [
    "fetch_symbol_chip",
    "to_stocktwits_symbol",
    "clear_cache",
    "MIN_LABELED_FOR_VERDICT",
]
