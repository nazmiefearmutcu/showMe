"""Shared Awareness plumbing for the showme news functions (TOP, NI, CN, NALRT, NSE).

Every news row comes from ``mapping.news_row`` applied to an awareness ``/news``
envelope. Nothing here falls back to RSS, GDELT or a model: when awareness cannot
answer, the caller returns ``provider_unavailable`` carrying the client's reason.
Stale providers keep their data but mark the response ``cached_snapshot`` with
``live: False`` and surface the provider notes.
"""

from __future__ import annotations

from typing import Any, Iterable

from showme.engine.core.base_function import FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.data_sources.awareness import (
    AwarenessClient,
    AwarenessResponse,
    AwarenessUnavailable,
    get_awareness_client,
)
from showme.engine.data_sources.awareness.mapping import news_row

NEWS_SOURCE = "awareness:news"
NO_LIVE_SOURCE = "no_live_source"
UNAVAILABLE_ACTIONS = ["Start awareness-markets (SHOWME_AWARENESS_HOME) and retry."]
STALE_STATES = frozenset({"down", "degraded"})
PROVIDER = "awareness"


def client_for(injected: AwarenessClient | None) -> AwarenessClient:
    """The injected test client, or the process-wide awareness client."""
    return injected if injected is not None else get_awareness_client()


def bounded_int(value: Any, default: int, lo: int, hi: int) -> int:
    """Parse a GET string or number as an int inside [lo, hi]; bad input means default."""
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        parsed = default
    return max(lo, min(parsed, hi))


def bounded_float(value: Any, default: float, lo: float, hi: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(lo, min(parsed, hi))


def csv_list(value: Any, *, upper: bool = False, lower: bool = False) -> list[str]:
    """``"a, b"`` / ``["a", "b"]`` -> cleaned list; empty values are dropped."""
    if value is None:
        return []
    raw = value if isinstance(value, (list, tuple, set)) else str(value).split(",")
    out: list[str] = []
    for item in raw:
        text = str(item).strip()
        if not text:
            continue
        if upper:
            text = text.upper()
        elif lower:
            text = text.lower()
        if text not in out:
            out.append(text)
    return out


def choice(value: Any, allowed: Iterable[str], default: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in set(allowed) else default


def text_param(value: Any) -> str:
    return str(value or "").strip()


def _summary(responses: Iterable[AwarenessResponse]) -> dict[str, Any]:
    providers: dict[str, dict[str, Any]] = {}
    notes: list[str] = []
    feed_health: Any = None
    generated_at: str | None = None
    for resp in responses:
        for provider in resp.providers:
            providers[str(provider.get("provider", "?"))] = provider
        for note in resp.notes:
            if note not in notes:
                notes.append(note)
        feed_health = feed_health or resp.meta.get("feed_health")
        generated_at = generated_at or resp.generated_at
    stale = [p for p in providers.values() if p.get("status") in STALE_STATES]
    errors = [
        f"{p.get('provider')}: {p.get('status')}" + (f" ({p.get('last_error')})" if p.get("last_error") else "")
        for p in stale
    ]
    return {
        "providers": list(providers.values()),
        "notes": notes,
        "feed_health": feed_health,
        "generated_at": generated_at,
        "stale": bool(stale),
        "errors": errors,
    }


def meta_block(responses: Iterable[AwarenessResponse]) -> dict[str, Any]:
    """``data.meta``: what ProviderHealthStrip renders."""
    summary = _summary(responses)
    return {
        "providers": summary["providers"],
        "generated_at": summary["generated_at"],
        "notes": summary["notes"],
        "feed_health": summary["feed_health"],
    }


def ok_result(
    code: str,
    instrument: Instrument | None,
    data: dict[str, Any],
    responses: list[AwarenessResponse],
) -> FunctionResult:
    summary = _summary(responses)
    data["meta"] = meta_block(responses)
    live = not summary["stale"]
    metadata = {
        "data_mode": "live_official" if live else "cached_snapshot",
        "live": live,
        "provider": PROVIDER,
        "providers": summary["providers"],
        "feed_health": summary["feed_health"],
        "generated_at": summary["generated_at"],
        "notes": summary["notes"],
        "provider_errors": summary["errors"],
    }
    return FunctionResult(
        code=code,
        instrument=instrument,
        data=data,
        sources=[NEWS_SOURCE],
        metadata=metadata,
        warnings=list(summary["notes"]),
    )


def unavailable_result(code: str, instrument: Instrument | None, reason: str) -> FunctionResult:
    data = {
        "status": "provider_unavailable",
        "reason": reason,
        "rows": [],
        "next_actions": list(UNAVAILABLE_ACTIONS),
        "meta": {"providers": [], "generated_at": None, "notes": [], "feed_health": None},
    }
    return FunctionResult(
        code=code,
        instrument=instrument,
        data=data,
        sources=[NO_LIVE_SOURCE],
        metadata={
            "fallback": True,
            "live": False,
            "data_mode": "provider_unavailable",
            "provider": PROVIDER,
            "provider_errors": [reason],
        },
        warnings=[reason],
    )


def input_required_result(code: str, instrument: Instrument | None, reason: str, example: str) -> FunctionResult:
    data = {
        "status": "input_required",
        "reason": reason,
        "rows": [],
        "next_actions": [example],
    }
    return FunctionResult(code=code, instrument=instrument, data=data, sources=[], metadata={"live": False})


async def fetch_news(client: AwarenessClient, query: dict[str, Any]) -> tuple[AwarenessResponse, list[dict[str, Any]]]:
    """``GET /news`` collapsed to story leads, mapped through ``news_row``."""
    resp = await client.get("/news", {**query, "story": True})
    rows = [news_row(item) for item in (resp.data or []) if isinstance(item, dict)]
    return resp, rows


def filters_echo(**values: Any) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value not in (None, "", [], ())}


def normalise_story(story: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(story, dict):
        return None
    return {
        "id": story.get("id"),
        "title": story.get("title"),
        "corroboration": story.get("corroboration"),
        "publishers": list(story.get("publishers") or []),
        "items": list(story.get("items") or []),
        "first_seen_at": story.get("first_seen_at"),
        "last_updated_at": story.get("last_updated_at"),
    }


async def story_detail(
    client: AwarenessClient, story_id: str
) -> tuple[dict[str, Any] | None, list[AwarenessResponse]]:
    """Resolve a drawer ``story_id`` to its story brief.

    ``story_id`` is normally the lead item id (the row ``id`` of a collapsed story),
    which ``GET /news/{id}`` answers directly. A story hash (the row ``story_id``
    field) is resolved through ``GET /stories`` to its lead item first.
    """
    responses: list[AwarenessResponse] = []
    lead_id = story_id
    try:
        detail = await client.get(f"/news/{story_id}")
    except AwarenessUnavailable as exc:
        if exc.status_code != 404:
            raise
        stories = await client.get("/stories", {"hours": 720, "min_corroboration": 1, "limit": 100})
        responses.append(stories)
        match = next(
            (row for row in (stories.data or []) if isinstance(row, dict) and row.get("id") == story_id),
            None,
        )
        if match is None:
            return None, responses
        lead_id = str(match.get("lead_item_id") or "")
        if not lead_id:
            return None, responses
        detail = await client.get(f"/news/{lead_id}")
    responses.append(detail)
    story = detail.data.get("story") if isinstance(detail.data, dict) else None
    return normalise_story(story), responses
