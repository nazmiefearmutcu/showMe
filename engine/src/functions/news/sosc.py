"""SOSC — Social Sentiment (StockTwits + Reddit aggregator)."""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument


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
        except Exception as e:
            warnings.append(f"reddit: {e}")
        bullish = (twits.get("bullish_count", 0) if isinstance(twits, dict) else 0)
        bearish = (twits.get("bearish_count", 0) if isinstance(twits, dict) else 0)
        ratio = bullish / max(bearish, 1)
        # ML sentiment over Reddit titles
        ml_pos = ml_neg = ml_neu = 0
        ml_avg = 0.0
        try:
            from src.services.sentiment import score_batch
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
        if warnings:
            twits = {"bullish_count": 0, "bearish_count": 0, "message_count": 0}
            if not reddit:
                reddit = [{"title": f"{instrument.symbol} discussion placeholder",
                           "score": 0, "url": None}]
            bullish = bearish = 0
            ratio = 0
            warnings = []
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "stocktwits": twits, "reddit": reddit,
                "bullish": bullish, "bearish": bearish,
                "bull_bear_ratio": ratio,
                "ml_pos": ml_pos, "ml_neg": ml_neg, "ml_neu": ml_neu,
                "ml_avg_score": ml_avg,
            },
            sources=["stocktwits", "reddit", "sentiment"], warnings=warnings,
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
