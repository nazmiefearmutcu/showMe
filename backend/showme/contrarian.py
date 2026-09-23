"""Contrarian-pattern corrector layered on top of FinBERT sentiment.

FinBERT scores the *tone* of financial language, not the *direction* a
headline argues for. A completed-bottom call ("cycle bottom may already
be in at $56K") is built from bear-market vocabulary — "bottom", a price
anchor far below spot — so FinBERT labels it negative even though the
claim itself is bullish. The same failure class covers fear-vs-outcome
pivots ("traders braced for a total wipeout but Bitcoin had other
plans"): the fear words dominate the surface tone while the message is
relief.

``correct_direction`` flips exactly that class of false negatives, and
nothing else:

* only ``neg`` → ``pos`` — a pos/neu row always passes through
  untouched, so the corrector can never create a new negative read;
* only on the whitelisted phrases in ``_RULES`` — tight, completed-
  bottom claims ("bottom is in", "has bottomed") rather than bare
  "bottom" tokens, which also occur in still-bearish headlines
  ("searching for a bottom", "bottom is near");
* a flipped row keeps FinBERT's confidence magnitude, floored at 0.6 so
  downstream buckets (NI treats ``>= +0.5`` as bull) see it as clearly
  positive;
* the caller MUST surface the returned note — ``stamp_items`` stamps it
  as ``sentiment_note`` plus ``sentiment_model="finbert+contrarian"`` —
  so a corrected row never masquerades as raw model output (same
  honesty rule as the veryfinder/FinBERT fallback chain).

Pure regex, no model, no I/O: the corrector runs inline in
:func:`showme.finbert_analyzer.stamp_items` at negligible cost.
"""
from __future__ import annotations

import re
from typing import Any

# (pattern, provenance note) pairs, checked in order; first match wins.
# All phrases are claims that the drawdown is OVER — deliberately not
# "bottom" alone, which also appears in headlines expecting more downside.
_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\bbottom\s+(?:is|may\s+(?:already\s+)?be|has\s+been|might\s+be)"
            r"\s+(?:already\s+)?in\b",
            re.IGNORECASE,
        ),
        "contrarian bottom-call",
    ),
    (
        re.compile(r"\b(?:has|have|had)\s+(?:already\s+)?bottomed\b", re.IGNORECASE),
        "contrarian bottom-call",
    ),
    (
        re.compile(r"\bbottomed\s+(?:out|at)\b", re.IGNORECASE),
        "contrarian bottom-call",
    ),
    (
        re.compile(
            r"\bworst\s+(?:is|may\s+be|might\s+be)\s+(?:already\s+)?"
            r"(?:over|behind)(?:\s+us)?\b",
            re.IGNORECASE,
        ),
        "contrarian bottom-call",
    ),
    (
        re.compile(r"\bcapitulation\s+(?:is\s+)?(?:over|behind)(?:\s+us)?\b", re.IGNORECASE),
        "contrarian bottom-call",
    ),
    (
        re.compile(r"\bhad\s+other\s+plans\b", re.IGNORECASE),
        "contrarian fear-pivot",
    ),
    (
        # Fear stated, then a "but" pivot into an outcome token that says
        # the asset shrugged it off — "braced for a wipeout but BTC rallied".
        re.compile(
            r"\bbraced\s+for\b[^.!?]{0,120}?\bbut\b[^.!?]{0,120}?\b"
            r"(?:had\s+other\s+plans|defied|defies|rose|rallied|rallies|rebounded"
            r"|surged|climbed|recovered|bounced|held\s+(?:firm|up)|stood\s+firm)\b",
            re.IGNORECASE,
        ),
        "contrarian fear-pivot",
    ),
)

# Floor for a flipped score_signed: below NI's +0.5 bull-bucket threshold
# a flip would move the label while the row still renders outside the bull
# bucket — visible nonsense. 0.6 clears the bucket with margin.
_MIN_FLIP_SCORE = 0.6


def correct_direction(text: str, result: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Return ``(result, note)`` with neg→pos applied when a rule fires.

    ``result`` is the canonical FinBERT envelope (``label``, ``score``,
    ``score_signed``, ``all_scores``). When no rule fires the ORIGINAL
    dict is returned unchanged with ``note=None`` so callers can treat
    "note is None" as "raw model output".
    """
    if result.get("label") != "neg" or not text or not text.strip():
        return result, None
    for pattern, note in _RULES:
        if pattern.search(text):
            magnitude = abs(float(result.get("score_signed") or 0.0))
            flipped = dict(result)
            flipped["label"] = "pos"
            flipped["score_signed"] = round(max(_MIN_FLIP_SCORE, magnitude), 4)
            return flipped, note
    return result, None


__all__ = ["correct_direction"]
