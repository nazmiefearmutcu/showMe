"""SOSC — Social Sentiment (StockTwits + Reddit aggregator)."""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument


@FunctionRegistry.register
class SOSCFunction(BaseFunction):
    code = "SOSC"
    name = "Social Sentiment"
    category = "news"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        if not _truthy(params.get("live_social") or params.get("live")):
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_social_template(instrument.symbol),
                sources=["social_sentiment_model"],
                metadata={"live": False},
            )
        warnings: list[str] = []
        twits = {}
        reddit = []
        try:
            if self.deps.stocktwits:
                twits = await asyncio.wait_for(
                    self.deps.stocktwits.fetch(DataRequest(
                        kind=DataKind.SOCIAL, instrument=instrument, limit=50
                    )),
                    timeout=float(params.get("timeout", 8)),
                )
            else:
                warnings.append("stocktwits: provider not configured")
        except Exception as e:
            warnings.append(f"stocktwits: {e}")
        try:
            if self.deps.reddit:
                reddit = await asyncio.wait_for(
                    self.deps.reddit.fetch(DataRequest(
                        kind=DataKind.SOCIAL, instrument=instrument, limit=25
                    )),
                    timeout=float(params.get("timeout", 8)),
                )
            else:
                warnings.append("reddit: provider not configured")
        except Exception as e:
            warnings.append(f"reddit: {e}")
        bullish = (twits.get("bullish_count", 0) if isinstance(twits, dict) else 0)
        bearish = (twits.get("bearish_count", 0) if isinstance(twits, dict) else 0)
        ratio = bullish / max(bearish, 1)
        # ML sentiment over Reddit titles
        ml_pos = ml_neg = ml_neu = 0
        ml_avg = 0.0
        scores: list[dict[str, Any]] = []
        try:
            from showme.engine.services.sentiment import score_batch
            titles = [r.get("title") or "" for r in (reddit or [])][:30]
            scores = score_batch(titles) if titles else []
            for s in scores:
                lbl = (s.get("label") or "").lower()
                if "pos" in lbl: ml_pos += 1
                elif "neg" in lbl: ml_neg += 1
                else: ml_neu += 1
            if scores:
                ml_avg = sum(s.get("score", 0) for s in scores) / len(scores)
        except Exception as e:
            warnings.append(f"sentiment: {e}")
        rows = _sentiment_rows(instrument.symbol, twits, reddit, scores)
        if not rows and not (bullish or bearish):
            reason = "No live Stocktwits or Reddit sentiment records were returned."
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "reason": reason,
                    "rows": [],
                    "symbol": instrument.symbol,
                    "stocktwits": twits if isinstance(twits, dict) else {},
                    "reddit": [],
                    "bullish": 0,
                    "bearish": 0,
                    "bull_bear_ratio": 0,
                    "next_actions": [
                        "Configure Stocktwits/Reddit providers or retry later.",
                        "Open Raw function payload to inspect provider errors.",
                    ],
                },
                sources=["stocktwits", "reddit", "sentiment"],
                metadata={"provider_errors": warnings or [reason], "live": True},
            )
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "rows": rows,
                "stocktwits": twits, "reddit": reddit,
                "bullish": bullish, "bearish": bearish,
                "bull_bear_ratio": ratio,
                "ml_pos": ml_pos, "ml_neg": ml_neg, "ml_neu": ml_neu,
                "ml_avg_score": ml_avg,
            },
            sources=["stocktwits", "reddit", "sentiment"],
            metadata={"provider_errors": warnings, "live": True},
        )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _social_template(symbol: str) -> dict[str, Any]:
    return {
        "stocktwits": {"bullish_count": 42, "bearish_count": 18, "message_count": 96},
        "reddit": [
            {"title": f"{symbol} market discussion", "score": 12, "url": None},
            {"title": f"{symbol} risk thread", "score": 7, "url": None},
        ],
        "bullish": 42,
        "bearish": 18,
        "bull_bear_ratio": 2.3333,
        "ml_pos": 1,
        "ml_neg": 0,
        "ml_neu": 1,
        "ml_avg_score": 0.64,
    }


def _sentiment_rows(
    symbol: str,
    twits: Any,
    reddit: Any,
    scores: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(twits, dict):
        count = int(twits.get("message_count") or twits.get("messages") or 0)
        bullish = int(twits.get("bullish_count") or 0)
        bearish = int(twits.get("bearish_count") or 0)
        if count or twits.get("bullish_count") or twits.get("bearish_count"):
            rows.append({
                "symbol": symbol,
                "source": "stocktwits",
                "title": "Stocktwits message balance",
                "bullish": bullish,
                "bearish": bearish,
                "message_count": count,
                "sentiment_score": _balance_score(bullish, bearish),
            })
    if isinstance(reddit, list):
        scored = scores or []
        for idx, item in enumerate(reddit[:20]):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            url = item.get("url") or item.get("permalink")
            score = scored[idx] if idx < len(scored) and isinstance(scored[idx], dict) else {}
            if title:
                rows.append({
                    "symbol": symbol,
                    "source": "reddit",
                    "title": title,
                    "reddit_score": item.get("score"),
                    "sentiment_label": score.get("label"),
                    "sentiment_score": _signed_sentiment_score(score),
                    "comments": item.get("num_comments") or item.get("comments"),
                    "url": url,
                })
    return rows


def _balance_score(bullish: int, bearish: int) -> float:
    total = bullish + bearish
    if total <= 0:
        return 0.0
    return round((bullish - bearish) / total, 4)


def _signed_sentiment_score(score: dict[str, Any]) -> float:
    label = str(score.get("label") or "").lower()
    raw = score.get("score", 0)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 0.0
    if "neg" in label:
        return round(-abs(value), 4)
    if "pos" in label:
        return round(abs(value), 4)
    return 0.0
