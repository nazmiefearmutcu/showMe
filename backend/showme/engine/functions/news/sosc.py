"""SOSC — Entity Sentiment (news + social buzz + GDELT tone), read from Awareness.

Every number comes from the awareness-markets service (``/v1/markets/sentiment``):

* ``news``: per-entity FinBERT sentiment of Awareness-collected news items over a
  1d / 7d / 30d window, with its hourly or daily series.
* ``headlines``: the newest items behind that sentiment.
* ``social``: the ApeWisdom rank / mention change for the ticker, when listed.
* ``gdelt_tone``: the GDELT DOC timeline tone series Awareness stored for the entity.

No legacy GDELT/FinBERT/StockTwits path remains here. When Awareness is down the
function returns ``provider_unavailable``; it never invents a sentiment value.
"""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

from showme.engine.core.base_function import BaseFunction, FunctionDeps, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.data_sources.awareness import (
    AwarenessClient,
    AwarenessResponse,
    AwarenessUnavailable,
    awareness_base_url,
    get_awareness_client,
)

WINDOW_BUCKETS: dict[str, str] = {"1d": "1h", "7d": "1h", "30d": "1d"}
DEFAULT_WINDOW = "7d"
HEADLINE_LIMIT = 25
UNAVAILABLE_NEXT_ACTIONS = ["Start awareness-markets (SHOWME_AWARENESS_HOME) and retry."]


def _base_symbol(raw: str) -> str:
    """Crypto quote suffixes are stripped; the match is suffix-anchored so FX-style
    ``USDJPY`` is left intact. ``BRK.B`` becomes the Awareness entity form ``BRK-B``;
    BIST ``.IS`` tickers keep their suffix."""
    sym = str(raw or "").strip().upper()
    base = sym.removesuffix("USDT").removesuffix("-USD").removesuffix("USD") or sym
    if base.endswith(".IS"):
        return base
    return base.replace(".", "-")


def _window_from_params(params: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return ``(window, error)``. ``window`` (1d|7d|30d) is the contract parameter; the
    legacy ``days`` parameter (still sent by the current pane) is mapped onto it."""
    raw = params.get("window")
    if raw not in (None, ""):
        window = str(raw).strip().lower()
        if window in WINDOW_BUCKETS:
            return window, None
        return None, f"window must be one of 1d, 7d, 30d (got {raw!r})"
    if params.get("days") not in (None, ""):
        try:
            days = int(float(str(params["days"])))
        except (TypeError, ValueError):
            return None, f"days must be a number (got {params['days']!r})"
        return ("1d" if days <= 1 else "7d" if days <= 7 else "30d"), None
    return DEFAULT_WINDOW, None


def _trend(value: Any) -> str | None:
    if value is None:
        return None
    v = float(value)
    return "bullish" if v > 0.05 else "bearish" if v < -0.05 else "flat"


def _tone_trend(value: Any) -> str | None:
    """GDELT tone is on its native scale (roughly -10 to +10), so the +/-0.05 band of
    ``_trend`` would call almost every sample bullish or bearish. Use a band of 1."""
    if value is None:
        return None
    v = float(value)
    return "bullish" if v > 1.0 else "bearish" if v < -1.0 else "flat"


def _mention_trend(change_pct: Any) -> str | None:
    if change_pct is None:
        return None
    v = float(change_pct)
    return "rising" if v > 5 else "falling" if v < -5 else "flat"


def _headline(item: dict[str, Any]) -> dict[str, Any]:
    """Flat headline shape (payload contract, label + score form): ``sentiment`` is the
    label string, ``sentiment_score`` the score in [-1, +1], ``sentiment_model`` the id."""
    sentiment = item.get("sentiment") or {}
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "publisher_name": item.get("publisher_name"),
        "url": item.get("url"),
        "published_at": item.get("published_at"),
        "sentiment": sentiment.get("label"),
        "sentiment_score": sentiment.get("score"),
        "sentiment_model": sentiment.get("model"),
        "quality_label": item.get("quality_label"),
    }


def _social_match(social: Any, base: str) -> dict[str, Any] | None:
    if not isinstance(social, dict):
        return None
    for group in ("stocks", "crypto"):
        for row in social.get(group) or []:
            if isinstance(row, dict) and str(row.get("ticker", "")).upper() == base:
                return {
                    "rank": row.get("rank"),
                    "mentions": row.get("mentions"),
                    "mention_change_pct": row.get("mention_change_pct"),
                    "rank_change": row.get("rank_change"),
                    "as_of": row.get("as_of"),
                }
    return None


_MODEL_NAMES = {"finbert": "FinBERT", "lexicon": "lexicon"}


def _model_family(model: str) -> str:
    return model.split(":", 1)[0].strip().lower()


def _scored_by(headlines: list[dict[str, Any]]) -> tuple[list[str], str | None]:
    """Distinct model ids on the returned headlines, and the display name for the row label:
    ``FinBERT``, ``lexicon``, or ``mixed: finbert+lexicon`` when the headlines differ."""
    models = sorted({h["sentiment_model"] for h in headlines if h.get("sentiment_model")})
    if not models:
        return [], None
    families = sorted({_model_family(m) for m in models})
    if len(families) == 1:
        return models, _MODEL_NAMES.get(families[0], families[0])
    return models, "mixed: " + "+".join(families)


def _methodology(base: str, window: str, bucket: str, models: list[str]) -> str:
    if models:
        scored_by = (
            f"the model Awareness recorded for it ({', '.join(models)}), as named on the "
            "headlines returned"
        )
    else:
        scored_by = "the model Awareness recorded for it (no returned item named a model)"
    return (
        f"SOSC reports Awareness entity sentiment for {base} over the last {window} "
        f"({bucket} buckets). Each Awareness-collected news item is scored by {scored_by}, "
        "giving a sentiment score in [-1, +1] per item. news.mean is the arithmetic mean of "
        "those item scores in each bucket and overall; news.weighted_mean weights each item by "
        "its model confidence times its source-quality score, as computed by Awareness. "
        "positive_share and negative_share are the fractions of items labelled positive or "
        "negative; momentum_z and dispersion are Awareness statistics and are null when there "
        "are too few observations. headlines are the newest items behind the score. social is "
        "the ApeWisdom rank and mention change for the ticker when it is on the ranked list, "
        "otherwise null. gdelt_tone is the GDELT DOC tone series Awareness stored for the entity, "
        "in GDELT's native scale (roughly -10 to +10), not rescaled. Nothing is estimated: an "
        "empty window returns status empty and no sentiment value."
    )


_FIELD_DICT = {
    "news.mean": "Mean FinBERT item score in [-1, +1] for the window.",
    "news.weighted_mean": "Confidence x source-quality weighted mean, computed by Awareness.",
    "news.series": "Bucketed counts and means (hourly for 1d/7d, daily for 30d).",
    "headlines": "Newest items behind the sentiment, with their item-level label and score.",
    "social.mention_change_pct": "Change in ApeWisdom mentions versus 24 hours earlier.",
    "gdelt_tone": "GDELT DOC tone series for the entity (native scale, roughly -10 to +10).",
    "rows": "Legacy platform table: News, Reddit (ApeWisdom) and GDELT tone rows when present.",
}


@FunctionRegistry.register
class SOSCFunction(BaseFunction):
    code = "SOSC"
    name = "Social Sentiment"
    asset_classes = (AssetClass.EQUITY, AssetClass.CRYPTO)
    category = "news"
    description = (
        "Per-symbol news sentiment (FinBERT over Awareness news), social buzz rank and GDELT tone, "
        "with the headlines behind the score."
    )

    def __init__(self, deps: FunctionDeps | None = None) -> None:
        super().__init__(deps)
        self._awareness: AwarenessClient | None = None

    def _client(self) -> AwarenessClient:
        return self._awareness or get_awareness_client()

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        raw_symbol = getattr(instrument, "symbol", None) or params.get("symbol")
        if not raw_symbol:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "input_required",
                    "reason": "Pass a symbol to score.",
                    "rows": [],
                    "next_actions": ["Enter a ticker, for example AAPL or BTC."],
                    "methodology": _methodology("the symbol", DEFAULT_WINDOW, "1h", []),
                    "field_dictionary": _FIELD_DICT,
                },
                sources=[],
                metadata={"live": False, "fallback": True, "data_mode": "provider_unavailable"},
            )
        base = _base_symbol(str(raw_symbol))
        window, error = _window_from_params(params)
        if window is None:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "input_error",
                    "reason": error,
                    "symbol": base,
                    "rows": [],
                    "next_actions": ["Use window 1d, 7d or 30d."],
                    "methodology": _methodology(base, DEFAULT_WINDOW, "1h", []),
                    "field_dictionary": _FIELD_DICT,
                },
                sources=[],
                warnings=[error or "invalid window"],
                metadata={"symbol": base, "live": False},
            )
        bucket = WINDOW_BUCKETS[window]

        client = self._client()
        entity_result, social_result = await asyncio.gather(
            client.get(f"/sentiment/entity/{quote(base, safe='.-')}", {"window": window, "bucket": bucket}),
            client.get("/sentiment/social"),
            return_exceptions=True,
        )
        if isinstance(entity_result, AwarenessUnavailable):
            return self._unavailable(instrument, base, window, bucket, entity_result.reason)
        if isinstance(entity_result, BaseException):
            raise entity_result
        entity: AwarenessResponse = entity_result

        errors: list[str] = []
        social_resp: AwarenessResponse | None = None
        if isinstance(social_result, AwarenessUnavailable):
            errors.append(f"social buzz unavailable: {social_result.reason}")
        elif isinstance(social_result, BaseException):
            raise social_result
        else:
            social_resp = social_result

        body = entity.data if isinstance(entity.data, dict) else {}
        headlines = [_headline(h) for h in (body.get("headlines") or []) if isinstance(h, dict)][:HEADLINE_LIMIT]
        models, model_name = _scored_by(headlines)
        count = int(body.get("count") or 0)
        mean = body.get("mean")
        news = {
            "count": count,
            "mean": mean,
            "weighted_mean": body.get("weighted_mean"),
            "positive_share": body.get("positive_share"),
            "negative_share": body.get("negative_share"),
            "momentum_z": body.get("momentum_z"),
            "dispersion": body.get("dispersion"),
            "latest_at": body.get("latest_at"),
            "publishers": body.get("publishers"),
            "series": [s for s in (body.get("series") or []) if isinstance(s, dict)],
        }
        gdelt_tone = [t for t in (body.get("gdelt_tone") or []) if isinstance(t, dict)]
        social = _social_match(social_resp.data if social_resp else None, base)

        rows: list[dict[str, Any]] = []
        if count > 0:
            platform = f"News ({model_name or 'model not reported'})"
            rows.append({"platform": platform, "mentions": count, "sentiment": mean, "trend": _trend(mean)})
        if social is not None:
            rows.append({
                "platform": "Reddit (ApeWisdom)",
                "mentions": social["mentions"],
                "rank": social["rank"],
                "trend": _mention_trend(social["mention_change_pct"]),
            })
        if gdelt_tone:
            last = gdelt_tone[-1].get("value")
            rows.append({"platform": "GDELT tone", "mentions": None, "sentiment": last, "trend": _tone_trend(last)})

        stale = list(entity.stale_providers)
        if social_resp is not None:
            stale += [p for p in social_resp.stale_providers if p not in stale]
        live = not stale
        notes = list(dict.fromkeys(entity.notes + (social_resp.notes if social_resp else [])))
        errors += [f"stale or failing provider: {p}" for p in stale]
        feed_health = body.get("feed_health") or entity.meta.get("feed_health")
        meta = {
            "providers": entity.providers,
            "generated_at": entity.generated_at,
            "notes": notes,
            "feed_health": feed_health,
        }

        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": "ok" if count > 0 else "empty",
                "symbol": base,
                "window": window,
                "news": news,
                "headlines": headlines,
                "social": social,
                "gdelt_tone": gdelt_tone,
                "rows": rows,
                "methodology": _methodology(base, window, bucket, models),
                "field_dictionary": _FIELD_DICT,
                "meta": meta,
            },
            sources=["awareness:sentiment"],
            warnings=list(dict.fromkeys(notes + errors)),
            metadata={
                **entity.provenance(),
                "symbol": base,
                "window": window,
                "bucket": bucket,
                "data_mode": "live_official" if live else "cached_snapshot",
                "live": live,
                "provider_errors": errors,
                "feed_health": feed_health,
                "service_url": awareness_base_url(),
            },
        )

    def _unavailable(
        self,
        instrument: Instrument | None,
        base: str,
        window: str,
        bucket: str,
        reason: str,
    ) -> FunctionResult:
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": "provider_unavailable",
                "reason": reason,
                "symbol": base,
                "window": window,
                "rows": [],
                "headlines": [],
                "gdelt_tone": [],
                "social": None,
                "next_actions": list(UNAVAILABLE_NEXT_ACTIONS),
                "methodology": _methodology(base, window, bucket, []),
                "field_dictionary": _FIELD_DICT,
                "meta": {"providers": [], "generated_at": None, "notes": [], "feed_health": None},
            },
            sources=["no_live_source"],
            warnings=[f"awareness: {reason}"],
            metadata={"symbol": base, "fallback": True, "live": False, "data_mode": "provider_unavailable"},
        )
