"""FinBERT singleton — finance-domain sentiment on news titles/snippets.

Lazy-loaded once per process (model load is ~300 MB, ~3s cold). All callers
use ``FinBertAnalyzer.instance()``. Inference runs in ``asyncio.to_thread``
so it doesn't block the event loop.

The model bundle is fetched via the standard HuggingFace cache (we ship the
weights inside the .app via PyInstaller; outside the .app the first call
falls back to network). If the bundle is missing / network is unavailable
the singleton stays in the ``unavailable`` state — callers MUST treat that
as "leave the existing sentiment field alone, stamp neutral as the
last-resort default" rather than crashing.

Contract for callers
--------------------
``label(text)``       → dict ``{label, score, score_signed, all_scores}``
``label_many(texts)`` → list of the same dict per input position.

``label`` is one of ``"pos" | "neu" | "neg"``.

``score`` is the FinBERT softmax confidence of the top label in [0, 1].

``score_signed`` is a directional score in [-1, +1]:
  - ``+score`` when ``label == "pos"``
  - ``-score`` when ``label == "neg"``
  -      0.0   when ``label == "neu"``
This is the value news handlers stamp as ``sentiment_score`` — it matches
the existing ``score_text`` contract in ``engine/services/sentiment.py``.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, ClassVar


LOG = logging.getLogger("showme.finbert")

# Mirror the HF label → canonical short-form used everywhere else in showMe.
_LABEL_MAP = {"positive": "pos", "negative": "neg", "neutral": "neu"}

# Defensive default — never raise, never let callers see a missing field.
_NEUTRAL: dict[str, Any] = {
    "label": "neu",
    "score": 0.0,
    "score_signed": 0.0,
    "all_scores": [],
}


class FinBertAnalyzer:
    """Process-wide singleton wrapping the ProsusAI/finbert sentiment pipeline."""

    _instance: ClassVar["FinBertAnalyzer | None"] = None
    _instance_lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self) -> None:
        # Heavy imports happen ONLY inside __init__ so a bare
        # `from showme.finbert_analyzer import FinBertAnalyzer` stays cheap.
        from transformers import pipeline  # noqa: PLC0415 - intentional lazy import

        self._pipe = pipeline(
            "sentiment-analysis",
            model="ProsusAI/finbert",
            tokenizer="ProsusAI/finbert",
            top_k=None,  # return all 3 scores so callers can compute score_signed
            truncation=True,
            max_length=512,
        )
        self._infer_lock = threading.Lock()

    @classmethod
    def instance(cls) -> "FinBertAnalyzer":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ── Inference (sync; callers wrap in to_thread) ──────────────────────
    def _label_sync(self, text: str) -> dict[str, Any]:
        if not text or not text.strip():
            return dict(_NEUTRAL)
        with self._infer_lock:
            raw = self._pipe(text[:512])
        return _normalize_one(raw)

    def _label_many_sync(self, texts: list[str]) -> list[dict[str, Any]]:
        # An empty list short-circuits — call the pipeline with [] and you
        # get [] back, but skipping the call avoids the to_thread hop.
        if not texts:
            return []
        cleaned = [(t or "")[:512] for t in texts]
        # If EVERY input is blank, neutral-stamp without calling the model.
        if not any(t.strip() for t in cleaned):
            return [dict(_NEUTRAL) for _ in texts]
        # Replace blanks with a single-space placeholder so the pipeline
        # never sees an empty string (transformers raises on empty input
        # in some versions). We re-mask blanks back to NEUTRAL below.
        masked = [t if t.strip() else " " for t in cleaned]
        with self._infer_lock:
            raw = self._pipe(masked)
        out: list[dict[str, Any]] = []
        for idx, scores in enumerate(raw):
            if not cleaned[idx].strip():
                out.append(dict(_NEUTRAL))
                continue
            out.append(_normalize_one(scores))
        return out

    # ── Inference (async wrappers) ───────────────────────────────────────
    async def label(self, text: str) -> dict[str, Any]:
        """Return ``{label, score, score_signed, all_scores}`` for ``text``.

        Empty/whitespace text returns the canonical NEUTRAL stamp without
        invoking the model. Inference runs off-loop via ``to_thread``.
        """
        return await asyncio.to_thread(self._label_sync, text)

    async def label_many(self, texts: list[str]) -> list[dict[str, Any]]:
        """Batch version of :meth:`label`. Output length always matches input."""
        return await asyncio.to_thread(self._label_many_sync, texts)


def _normalize_one(raw: Any) -> dict[str, Any]:
    """Convert one pipeline output into the canonical envelope.

    ``transformers`` returns ``list[list[dict]]`` when ``top_k=None`` for a
    single input it returns ``[[ {label, score}, ... ]]``; for a list it
    returns ``[[ ... ], [ ... ], ...]``. ``_normalize_one`` accepts either
    the inner list ``[{label, score}, ...]`` (passed from ``_label_many``)
    or the outer wrapper (passed from ``_label``).
    """
    if not raw:
        return dict(_NEUTRAL)
    # Single-input call returns the outer wrapper; unwrap if needed.
    if isinstance(raw, list) and raw and isinstance(raw[0], list):
        raw = raw[0]
    if not raw:
        return dict(_NEUTRAL)
    try:
        top = max(raw, key=lambda s: float(s.get("score") or 0.0))
    except (TypeError, ValueError):
        return dict(_NEUTRAL)
    label = _LABEL_MAP.get(str(top.get("label", "")).lower(), "neu")
    score = float(top.get("score") or 0.0)
    sign = 1.0 if label == "pos" else (-1.0 if label == "neg" else 0.0)
    all_scores = [
        {
            "label": _LABEL_MAP.get(str(s.get("label", "")).lower(), "neu"),
            "score": float(s.get("score") or 0.0),
        }
        for s in raw
    ]
    return {
        "label": label,
        "score": score,
        "score_signed": round(sign * score, 4),
        "all_scores": all_scores,
    }


# ── News-item stamping helper ────────────────────────────────────────────
def _item_text(item: dict[str, Any]) -> str:
    """Pick the best text snippet for sentiment classification.

    Prefers title + first 200 chars of summary/body; falls back to title
    only; falls back to empty string if neither exists. Headline-only is
    intentional — FinBERT was trained on financial *headlines* and short
    snippets, not multi-paragraph articles.
    """
    title = (item.get("title") or item.get("headline") or "").strip()
    summary = (
        item.get("summary")
        or item.get("body")
        or item.get("description")
        or item.get("snippet")
        or ""
    ).strip()
    if title and summary:
        return f"{title}. {summary[:200]}"
    return title or summary[:280]


async def stamp_items(
    items: list[dict[str, Any]],
    *,
    overwrite_existing: bool = False,
) -> tuple[list[dict[str, Any]], str | None]:
    """Stamp ``sentiment`` + ``sentiment_score`` on each news item via FinBERT.

    Returns ``(items, warning)`` where ``warning`` is ``None`` on success
    or a short human-readable string when FinBERT is unavailable (model
    missing / load failed). Items are mutated IN PLACE and also returned
    for convenience.

    When ``overwrite_existing`` is False (the default) an item that already
    carries BOTH ``sentiment`` and ``sentiment_score`` is left alone — this
    is so a richer upstream model (e.g. XSEN's RoBERTa or an enrichment
    pipeline that already ran) keeps precedence. Set the flag to True only
    in tests / migrations.

    If the model load fails, every item is stamped ``sentiment="neutral"``
    + ``sentiment_score=0.0`` so the UI never sees a missing field.
    """
    if not items:
        return items, None

    # Decide which items need scoring.
    pending_idx: list[int] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        if not overwrite_existing and "sentiment" in item and "sentiment_score" in item:
            # Already labelled by an upstream pipeline — keep it.
            continue
        pending_idx.append(idx)

    if not pending_idx:
        return items, None

    texts = [_item_text(items[i]) for i in pending_idx]

    warning: str | None = None
    try:
        analyzer = await asyncio.to_thread(FinBertAnalyzer.instance)
        results = await analyzer.label_many(texts)
    except Exception as exc:  # noqa: BLE001 - fall through to neutral stamp
        LOG.warning("finbert: model unavailable, stamping neutral: %r", exc)
        warning = f"finbert unavailable: {exc.__class__.__name__}"
        results = [dict(_NEUTRAL) for _ in texts]

    # Map "neu" → "neutral" / "pos" → "positive" / "neg" → "negative" on the
    # stamped item so the public payload uses the long-form labels the
    # existing schema (see manifest/seeds/top_seed.py + cn_seed.py) speaks.
    long_form = {"pos": "positive", "neg": "negative", "neu": "neutral"}

    for slot, result in zip(pending_idx, results):
        item = items[slot]
        long_label = long_form.get(result["label"], "neutral")
        item["sentiment"] = long_label
        item["sentiment_score"] = float(result.get("score_signed") or 0.0)
        # Preserve raw FinBERT scores for downstream UIs that want to draw
        # a 3-bar histogram (positive / neutral / negative).
        item["sentiment_model"] = "finbert" if warning is None else "neutral_fallback"
        item.setdefault("sentiment_all_scores", result.get("all_scores") or [])
    return items, warning


__all__ = ["FinBertAnalyzer", "stamp_items"]
