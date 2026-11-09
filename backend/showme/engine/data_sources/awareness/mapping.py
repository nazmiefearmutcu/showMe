"""Map awareness records onto the row shapes showme panes render.

News rows keep the legacy keys panes already read (``title``, ``url``/``link``,
``source``, ``published_at``, ``sentiment``, ``sentiment_score``,
``importance_score``) — now filled with real attribution — and add the richer
awareness fields (publisher tier, quality verdict + reasons, story size,
entities, topics, excerpt).
"""

from __future__ import annotations

from typing import Any


def news_row(item: dict[str, Any]) -> dict[str, Any]:
    sentiment = item.get("sentiment") or {}
    publisher = item.get("publisher_name") or item.get("publisher_id") or ""
    entities = [
        {"type": e.get("type"), "id": e.get("id"), "name": e.get("name"), "confidence": e.get("confidence")}
        for e in (item.get("entities") or [])
        if isinstance(e, dict)
    ]
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "url": item.get("url"),
        "link": item.get("url"),
        "source": publisher,
        "publisher": publisher,
        "publisher_id": item.get("publisher_id"),
        "publisher_domain": item.get("publisher_domain"),
        "publisher_tier": item.get("publisher_tier"),
        "author": item.get("author"),
        "published_at": item.get("published_at"),
        "first_seen_at": item.get("first_seen_at"),
        "summary": item.get("summary"),
        "excerpt": item.get("excerpt"),
        "language": item.get("language"),
        "content_type": item.get("content_type"),
        "symbols": list(item.get("symbols") or []),
        "countries": list(item.get("countries") or []),
        "topics": list(item.get("topics") or []),
        "asset_classes": list(item.get("asset_classes") or []),
        "entities": entities,
        "sentiment": sentiment.get("label"),
        "sentiment_score": sentiment.get("score"),
        "sentiment_confidence": sentiment.get("confidence"),
        "sentiment_model": sentiment.get("model"),
        "entity_sentiment": item.get("entity_sentiment") or {},
        "importance_score": item.get("importance"),
        "importance": item.get("importance"),
        "quality_label": item.get("quality_label"),
        "quality_score": item.get("quality_score"),
        "quality_reasons": list(item.get("quality_reasons") or []),
        "story_id": item.get("story_id"),
        "story_size": item.get("story_size") or 1,
        "is_paywalled": bool(item.get("is_paywalled")),
    }


def provider_note_lines(meta: dict[str, Any]) -> list[str]:
    """Human-readable warnings from an awareness envelope's meta block."""
    lines = [str(n) for n in (meta.get("notes") or [])]
    return list(dict.fromkeys(lines))
