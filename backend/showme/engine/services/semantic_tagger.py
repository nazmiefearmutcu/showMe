"""Hybrid AI tag hook (MEET Bloomberg Faz 2 — scaffolding, passive).

Phase-2 contract:
  * rule tags are FINAL (not provisional); this hook is infrastructure only
    and is never called on the MEET synchronous path,
  * no ``onnxruntime`` dependency is added — when the import is missing the
    hook stays silently passive via ``available == False``,
  * ``tag_status`` carries the ``provisional`` / ``confirmed`` concept for
    the later async ``tag_v2`` step; unit tests drive this module with mocks.

No model weights are downloaded here.
"""

from __future__ import annotations

from typing import Any

try:  # Optional acceleration only; absence is normal and silent.
    import onnxruntime  # type: ignore  # noqa: F401
    available: bool = True
except Exception:
    onnxruntime = None  # type: ignore[assignment]
    available = False

PROVISIONAL = "provisional"
CONFIRMED = "confirmed"

#: Rule confidence at/above which a headline needs no model pass
#: (spec: rule > 0.95 finishes, ~65% of traffic).
RULE_CONFIRM_THRESHOLD = 0.95


def tag_status(rule_confidence: Any = 1.0) -> str:
    """Map a rule-tagger confidence onto provisional/confirmed."""
    try:
        confidence = float(rule_confidence)
    except (TypeError, ValueError):
        return PROVISIONAL
    return CONFIRMED if confidence >= RULE_CONFIRM_THRESHOLD else PROVISIONAL


def suggest_tags(
    text: str,
    *,
    rule_tags: Any = (),
    rule_confidence: Any = 1.0,
) -> dict[str, Any]:
    """Passive suggestion: echo rule tags with their status.

    When ``available`` is False (no onnxruntime in this phase) no model
    runs — the caller keeps the rule tags as final. A future model pass
    only *adds* tags; it never removes rule/provider tags.
    """
    tags = [str(t).strip().upper() for t in (rule_tags or []) if str(t).strip()]
    return {
        "tags": tags,
        "tag_status": tag_status(rule_confidence),
        "model": None,
        "available": available,
    }


def apply_tags(row: dict[str, Any], suggestion: dict[str, Any] | None) -> dict[str, Any]:
    """Stamp ``details.tag_status`` without touching existing tags.

    Existing ``asset_tags`` / ``topic_tags`` (rule or provider ground
    truth) are never overwritten or removed here.
    """
    if not isinstance(row, dict) or not isinstance(suggestion, dict):
        return row
    out = dict(row)
    details = dict(out.get("details") or {})
    details["tag_status"] = str(suggestion.get("tag_status") or CONFIRMED)
    out["details"] = details
    return out


__all__ = [
    "CONFIRMED",
    "PROVISIONAL",
    "RULE_CONFIRM_THRESHOLD",
    "apply_tags",
    "available",
    "suggest_tags",
    "tag_status",
]
