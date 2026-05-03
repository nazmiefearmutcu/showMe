"""Sentiment scoring service.

Tier 1: HuggingFace transformers (FinBERT or distilroberta finance)
Tier 2: VADER (lightweight, no GPU)
Tier 3: keyword heuristic ("rally", "surge", "plunge", ...)

Lazy-loaded. CPU-only OK; first call ~2-5s warmup.
"""

from __future__ import annotations

from typing import Any


_MODEL = None
_MODEL_KIND: str | None = None
_VADER = None


def _load_model() -> tuple[Any, str]:
    global _MODEL, _MODEL_KIND
    if _MODEL is not None:
        return _MODEL, _MODEL_KIND  # type: ignore[return-value]
    try:
        from transformers import pipeline  # type: ignore
        # FinBERT (ProsusAI) is the gold standard for financial sentiment.
        _MODEL = pipeline("sentiment-analysis", model="ProsusAI/finbert",
                          tokenizer="ProsusAI/finbert", truncation=True, max_length=512)
        _MODEL_KIND = "finbert"
        return _MODEL, _MODEL_KIND
    except Exception:
        pass
    try:
        from transformers import pipeline  # type: ignore
        _MODEL = pipeline("sentiment-analysis", truncation=True, max_length=512)
        _MODEL_KIND = "default"
        return _MODEL, _MODEL_KIND
    except Exception:
        pass
    try:
        # nltk vader fallback
        from nltk.sentiment.vader import SentimentIntensityAnalyzer  # type: ignore
        global _VADER
        _VADER = _VADER or SentimentIntensityAnalyzer()
        _MODEL = _VADER
        _MODEL_KIND = "vader"
        return _MODEL, _MODEL_KIND
    except Exception:
        pass
    _MODEL = "keyword"
    _MODEL_KIND = "keyword"
    return _MODEL, _MODEL_KIND


_BULL = {"rally", "surge", "soar", "jump", "gain", "beat", "outperform",
         "upgrade", "raise", "bullish", "growth", "record", "strong", "tops"}
_BEAR = {"plunge", "drop", "slump", "fall", "miss", "underperform",
         "downgrade", "cut", "bearish", "decline", "loss", "warn", "weak"}


def _keyword_score(text: str) -> dict[str, float]:
    t = (text or "").lower()
    bull = sum(1 for w in _BULL if w in t)
    bear = sum(1 for w in _BEAR if w in t)
    total = bull + bear
    if total == 0:
        return {"label": "neutral", "score": 0.0}
    s = (bull - bear) / total
    label = "positive" if s > 0.1 else ("negative" if s < -0.1 else "neutral")
    return {"label": label, "score": float(s)}


def score_text(text: str) -> dict[str, Any]:
    if not text:
        return {"label": "neutral", "score": 0.0, "model": "empty"}
    model, kind = _load_model()
    try:
        if kind in ("finbert", "default"):
            r = model(text[:1500])[0]  # type: ignore[operator]
            label = r["label"].lower()
            sc = float(r["score"])
            sign = 1.0 if label in ("positive", "label_2", "bullish", "pos") else (
                -1.0 if label in ("negative", "label_0", "bearish", "neg") else 0.0
            )
            return {"label": label, "score": sign * sc, "model": kind}
        if kind == "vader":
            r = model.polarity_scores(text)  # type: ignore[union-attr]
            comp = r["compound"]
            return {"label": "positive" if comp > 0.05 else ("negative" if comp < -0.05 else "neutral"),
                    "score": float(comp), "model": "vader"}
    except Exception:
        pass
    return {**_keyword_score(text), "model": "keyword"}


def score_batch(texts: list[str]) -> list[dict[str, Any]]:
    return [score_text(t) for t in texts]
