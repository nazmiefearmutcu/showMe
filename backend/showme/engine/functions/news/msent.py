"""MSENT — Market Sentiment dashboard, read from Awareness.

Market-wide sentiment indicators as Awareness reports them (``/v1/markets/sentiment/market``):
CNN Fear & Greed (score, rating, components, history), crypto Fear & Greed, the VIX term
structure (VIX, VIX9D, VIX3M, contango/backwardation) and ApeWisdom social buzz movers.
Sections Awareness returns as null stay null: this function never supplies a default gauge.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionDeps, FunctionRegistry, FunctionResult
from showme.engine.data_sources.awareness import (
    AwarenessClient,
    AwarenessResponse,
    AwarenessUnavailable,
    awareness_base_url,
    get_awareness_client,
)

DEFAULT_HISTORY_DAYS = 90
MAX_HISTORY_DAYS = 365
UNAVAILABLE_NEXT_ACTIONS = ["Start awareness-markets (SHOWME_AWARENESS_HOME) and retry."]
SECTIONS = ("cnn", "crypto", "vix")


def _history_days(params: dict[str, Any]) -> tuple[int | None, str | None]:
    raw = params.get("history_days")
    if raw in (None, ""):
        return DEFAULT_HISTORY_DAYS, None
    try:
        days = int(float(str(raw)))
    except (TypeError, ValueError):
        return None, f"history_days must be a whole number of days (got {raw!r})"
    return max(1, min(days, MAX_HISTORY_DAYS)), None


def _within(ts: Any, cutoff: datetime) -> bool:
    """Keep a history point when its timestamp is inside the window; keep unparseable points
    rather than silently dropping Awareness data."""
    try:
        when = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when >= cutoff


def _trim_section(section: Any, cutoff: datetime) -> Any:
    """Return the section with its ``history`` restricted to the requested window."""
    if not isinstance(section, dict):
        return None
    out = dict(section)
    if isinstance(section.get("history"), list):
        out["history"] = [point for point in section["history"] if _within(point.get("ts"), cutoff)]
    return out


def _has_content(section: Any) -> bool:
    if not isinstance(section, dict):
        return False
    return any(value is not None for key, value in section.items() if key != "history") or bool(
        section.get("history")
    )


def _social(data: dict[str, Any]) -> dict[str, Any] | None:
    social = data.get("social")
    if not isinstance(social, dict):
        return None
    return {"stocks": list(social.get("stocks") or []), "crypto": list(social.get("crypto") or [])}


@FunctionRegistry.register
class MSENTFunction(BaseFunction):
    code = "MSENT"
    name = "Market Sentiment"
    asset_classes = ()
    category = "news"
    description = (
        "Market-wide sentiment dashboard from Awareness: CNN and crypto Fear & Greed, "
        "VIX term structure and social buzz movers."
    )

    def __init__(self, deps: FunctionDeps | None = None) -> None:
        super().__init__(deps)
        self._awareness: AwarenessClient | None = None

    def _client(self) -> AwarenessClient:
        return self._awareness or get_awareness_client()

    async def execute(self, instrument: Any = None, **params: Any) -> FunctionResult:
        history_days, error = _history_days(params)
        if history_days is None:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "input_error",
                    "reason": error,
                    "rows": [],
                    "next_actions": ["Pass history_days as a whole number between 1 and 365."],
                },
                sources=[],
                warnings=[error or "invalid history_days"],
                metadata={"live": False},
            )

        try:
            response: AwarenessResponse = await self._client().get("/sentiment/market")
        except AwarenessUnavailable as exc:
            return self._unavailable(instrument, exc.reason)

        raw = response.data if isinstance(response.data, dict) else {}
        cutoff = datetime.now(timezone.utc) - timedelta(days=history_days)
        cnn = _trim_section(raw.get("cnn"), cutoff)
        crypto = _trim_section(raw.get("crypto"), cutoff)
        vix = _trim_section(raw.get("vix"), cutoff)
        social = _social(raw)
        sections_present = [name for name, value in (("cnn", cnn), ("crypto", crypto), ("vix", vix)) if _has_content(value)]
        has_social = bool(social and (social["stocks"] or social["crypto"]))
        status = "ok" if sections_present or has_social else "empty"

        stale = response.stale_providers
        live = not stale
        errors = [f"stale or failing provider: {p}" for p in stale]
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": status,
                "cnn": cnn,
                "crypto": crypto,
                "vix": vix,
                "social": social,
                "sources": raw.get("sources") if isinstance(raw.get("sources"), dict) else {},
                "history_days": history_days,
                "meta": {
                    "providers": response.providers,
                    "generated_at": response.generated_at,
                    "notes": response.notes,
                    "feed_health": response.meta.get("feed_health"),
                },
            },
            sources=["awareness:sentiment"],
            warnings=list(dict.fromkeys(response.notes + errors)),
            metadata={
                **response.provenance(),
                "history_days": history_days,
                "sections": sections_present,
                "data_mode": "live_official" if live else "cached_snapshot",
                "live": live,
                "provider_errors": errors,
                "service_url": awareness_base_url(),
            },
        )

    def _unavailable(self, instrument: Any, reason: str) -> FunctionResult:
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": "provider_unavailable",
                "reason": reason,
                "rows": [],
                "next_actions": list(UNAVAILABLE_NEXT_ACTIONS),
                "cnn": None,
                "crypto": None,
                "vix": None,
                "social": None,
                "meta": {"providers": [], "generated_at": None, "notes": [], "feed_health": None},
            },
            sources=["no_live_source"],
            warnings=[f"awareness: {reason}"],
            metadata={"fallback": True, "live": False, "data_mode": "provider_unavailable"},
        )
