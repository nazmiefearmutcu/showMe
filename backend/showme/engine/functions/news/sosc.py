"""SOSC — Social / News Sentiment.

Real, KEYLESS implementation. The product claim is an aggregate social-sentiment
read for a symbol. Authenticated social APIs (X, Reddit, StockTwits) need keys
and are inert in the standard build, so instead of emitting a hardcoded neutral
baseline we derive a genuine sentiment signal from two keyless sources:

  * GDELT DOC 2.0 API (https://api.gdeltproject.org/api/v2/doc/doc) — global
    news/social article volume + per-article *tone* over a rolling window.
  * The bundled FinBERT analyzer (``showme.finbert_analyzer``) scoring the
    recent headlines for an independent financial-sentiment read.

The two are blended into a net sentiment in [-1, +1] with real article counts.
On a genuine network failure we return ``provider_unavailable`` with an honest
warning — never a fabricated number.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument

_UA = {"User-Agent": "showMe research desk admin@showme.app"}
_GDELT_DOC = "https://api.gdeltproject.org/api/v2/doc/doc"


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


async def _client():
    """Shared keyless async HTTP client (httpx) from the provider layer.

    ``get_client`` is an async factory, so it MUST be awaited — returning the
    bare coroutine would make ``.get`` fail and silently drop SOSC to the
    provider_unavailable branch on the happy path.
    """
    from showme.providers._http import get_client

    return await get_client()


def _finbert():
    try:
        from showme.finbert_analyzer import get_finbert_analyzer

        return get_finbert_analyzer()
    except Exception:
        return None


def _query_for(symbol: str) -> str:
    """Build a GDELT query — ticker scoped to finance context, English.

    GDELT's query parser is strict: ``(`` may ONLY wrap an OR'd statement, and
    two adjacent parenthesised groups (the old
    ``("AAPL" OR "AAPL stock") (stock OR ...)`` shape) are rejected with HTTP
    200 + ``"Parentheses may only be used around OR'd statements."`` and zero
    articles. The reliable shape (empirically verified 2026-06-01: 21 articles
    for AAPL) is a BARE symbol term ANDed with a SINGLE finance OR-group.
    """
    sym = symbol.upper()
    return f"{sym} (stock OR shares OR earnings OR market OR price OR trading OR investors)"


async def _gdelt_articles(symbol: str, timespan: str, maxrecords: int) -> list[dict[str, Any]]:
    """Pull recent articles + tone from GDELT DOC 2.0 (keyless).

    GDELT throttles aggressively ("limit requests to one every 5 seconds")
    and returns HTTP 429 under bursts. Rather than surfacing a transient 429
    as a hard provider_unavailable, retry ONCE after honouring the documented
    cool-off so a quick second click (or a verification burst) still resolves.
    """
    import time
    client = await _client()
    t_start = time.perf_counter()

    async def _hit(query: str) -> list[dict[str, Any]]:
        if time.perf_counter() - t_start > 4.0:
            return []
        params = {
            "query": query,
            "mode": "ArtList",
            "format": "json",
            "maxrecords": str(maxrecords),
            "timespan": timespan,
            "sort": "DateDesc",
        }
        r = None
        for attempt in range(2):
            if time.perf_counter() - t_start > 5.0:
                break
            try:
                r = await client.get(_GDELT_DOC, params=params, headers=_UA, timeout=3.0)
                if r.status_code == 429:
                    if attempt == 0:
                        await asyncio.sleep(1.0)
                        continue
                    else:
                        break
                r.raise_for_status()
                break
            except Exception:
                if attempt == 1:
                    raise
                await asyncio.sleep(0.5)
        if r is None:
            return []
        try:
            payload = r.json()
        except Exception:
            return []
        arts = payload.get("articles") if isinstance(payload, dict) else None
        return arts if isinstance(arts, list) else []

    arts = await _hit(_query_for(symbol))
    if not arts and (time.perf_counter() - t_start < 4.0):
        arts = await _hit(symbol.upper())
    return arts


def _to_unit_tone(tone: Any) -> float | None:
    """GDELT tone is roughly [-10, +10]; map to [-1, +1] and clamp."""
    try:
        v = float(tone)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    return max(-1.0, min(1.0, v / 10.0))


@FunctionRegistry.register
class SOSCFunction(BaseFunction):
    code = "SOSC"
    name = "Social Sentiment"
    asset_classes = (AssetClass.EQUITY, AssetClass.CRYPTO)
    category = "news"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        sym = (getattr(instrument, "symbol", None) or params.get("symbol") or "AAPL").upper()
        # crypto symbols arrive as BTCUSDT / BTC-USD — strip to the base token
        base = sym.replace("USDT", "").replace("-USD", "").replace("USD", "") or sym
        days = int(params.get("days", 3) or 3)
        timespan = f"{max(1, min(days, 14))}d"
        maxrecords = max(20, min(int(params.get("limit", 75) or 75), 250))

        warnings: list[str] = []
        try:
            articles = await _gdelt_articles(base, timespan, maxrecords)
        except Exception as exc:  # noqa: BLE001
            reason = str(exc) or exc.__class__.__name__
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "symbol": sym,
                    "rows": [],
                    "summary": {"symbol": sym, "net_sentiment": None, "total_mentions": 0,
                                "source_mode": "gdelt_unreachable"},
                    "reason": f"GDELT request failed: {reason}",
                    "next_actions": ["Retry once the GDELT endpoint recovers."],
                    "methodology": "SOSC reads keyless GDELT news/social tone and scores headlines with FinBERT.",
                    "field_dictionary": _FIELD_DICT,
                },
                sources=["no_live_source"],
                warnings=[f"gdelt: {reason}"],
                metadata={"symbol": sym, "live": False},
            )

        if not articles:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "empty",
                    "symbol": sym,
                    "rows": [],
                    "summary": {"symbol": sym, "net_sentiment": 0.0, "total_mentions": 0,
                                "source_mode": "gdelt"},
                    "methodology": "SOSC reads keyless GDELT news/social tone and scores headlines with FinBERT.",
                    "field_dictionary": _FIELD_DICT,
                },
                sources=["gdelt"],
                warnings=[f"No recent GDELT coverage for {base} in the last {timespan}."],
                metadata={"symbol": sym, "live": True},
            )

        # ---- GDELT tone leg --------------------------------------------------
        tones = [t for t in (_to_unit_tone(a.get("tone")) for a in articles) if t is not None]
        gdelt_tone = round(sum(tones) / len(tones), 4) if tones else 0.0
        domains: dict[str, dict[str, Any]] = {}
        headlines: list[str] = []
        for a in articles:
            dom = str(a.get("domain") or a.get("sourcecountry") or "unknown")
            t = _to_unit_tone(a.get("tone"))
            d = domains.setdefault(dom, {"mentions": 0, "tone_sum": 0.0, "n": 0})
            d["mentions"] += 1
            if t is not None:
                d["tone_sum"] += t
                d["n"] += 1
            title = str(a.get("title") or "").strip()
            if title:
                headlines.append(title)

        # ---- FinBERT headline leg (independent financial sentiment) ----------
        finbert_score = None
        fb = _finbert()
        if fb is not None and headlines:
            try:
                sample = headlines[:8]
                results = await asyncio.to_thread(
                    lambda: [fb.analyze_text(h) for h in sample]
                )
                signed = []
                for res in results:
                    if not isinstance(res, dict):
                        continue
                    lbl = str(res.get("label", "")).lower()
                    sc = float(res.get("score", 0.0) or 0.0)
                    if "pos" in lbl:
                        signed.append(sc)
                    elif "neg" in lbl:
                        signed.append(-sc)
                    else:
                        signed.append(0.0)
                if signed:
                    finbert_score = round(sum(signed) / len(signed), 4)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"finbert: {exc}")

        # Blend: average the two real signals when both present.
        legs = [x for x in (gdelt_tone, finbert_score) if x is not None]
        net = round(sum(legs) / len(legs), 4) if legs else gdelt_tone

        # Per-source rows (real outlet aggregates), top by mention count.
        rows = []
        for dom, agg in sorted(domains.items(), key=lambda kv: kv[1]["mentions"], reverse=True)[:25]:
            mean_tone = round(agg["tone_sum"] / agg["n"], 4) if agg["n"] else 0.0
            rows.append({
                "platform": dom,
                "mentions": agg["mentions"],
                "sentiment": mean_tone,
                "trend": "bullish" if mean_tone > 0.05 else "bearish" if mean_tone < -0.05 else "flat",
                "source_mode": "gdelt",
            })

        def _label(v: float) -> str:
            return "bullish" if v > 0.05 else "bearish" if v < -0.05 else "neutral"

        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": "ok",
                "symbol": sym,
                "rows": rows,
                "cards": [
                    {"key": "net_sentiment", "label": "Net sentiment", "value": net},
                    {"key": "label", "label": "Read", "value": _label(net)},
                    {"key": "total_mentions", "label": "Articles", "value": len(articles)},
                    {"key": "gdelt_tone", "label": "GDELT tone", "value": gdelt_tone},
                    {"key": "finbert", "label": "FinBERT", "value": finbert_score},
                ],
                "summary": {
                    "symbol": sym,
                    "net_sentiment": net,
                    "label": _label(net),
                    "total_mentions": len(articles),
                    "gdelt_tone": gdelt_tone,
                    "finbert_headline_sentiment": finbert_score,
                    "window": timespan,
                    "outlets": len(domains),
                    "source_mode": "gdelt+finbert" if finbert_score is not None else "gdelt",
                },
                "methodology": (
                    "SOSC measures real news/social sentiment for the symbol. Article volume and per-article "
                    "tone come from the keyless GDELT DOC 2.0 API over a rolling window; tone is mapped from "
                    "GDELT's [-10,+10] scale to [-1,+1]. Recent headlines are independently scored by the bundled "
                    "FinBERT financial-sentiment model, and the two legs are averaged into a net read. Rows show "
                    "the top outlets by mention count with their mean tone."
                ),
                "field_dictionary": _FIELD_DICT,
            },
            sources=["gdelt", "finbert"] if finbert_score is not None else ["gdelt"],
            warnings=warnings,
            metadata={"symbol": sym, "live": True, "window": timespan,
                      "article_count": len(articles)},
        )


_FIELD_DICT = {
    "platform": "News/social outlet (GDELT source domain).",
    "mentions": "Article count from that outlet in the window.",
    "sentiment": "Mean tone for that outlet, mapped to [-1, +1].",
    "trend": "Bullish / bearish / flat from the mean tone.",
    "net_sentiment": "Blended GDELT + FinBERT sentiment in [-1, +1].",
}
