"""Shared plumbing for functions that read the Awareness markets service.

Every helper here follows the honesty rules of the showme <-> Awareness
payload contract: failures become ``provider_unavailable`` with the client's
reason, stale providers flip ``live`` off, and nothing is ever invented.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd

from showme.engine.core.base_function import FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.data_sources.awareness import (
    AwarenessClient,
    AwarenessResponse,
    AwarenessUnavailable,
    get_awareness_client,
)

PROVIDER = "awareness"
NO_LIVE_SOURCE = "no_live_source"
UNAVAILABLE_NEXT_ACTION = "Start awareness-markets (SHOWME_AWARENESS_HOME) and retry."

_COUNTRY_ALIASES = {"UK": "GB", "EZ": "EU"}
_IMPORTANCE_WORDS = {"low": 1, "medium": 2, "high": 3}


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def iso_day(value: date) -> str:
    return value.isoformat()


def parse_day(value: Any) -> date | None:
    """Parse ``YYYY-MM-DD`` (or an ISO datetime prefix); anything else is None."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def parse_int(value: Any, *, default: int, floor: int, ceiling: int) -> int:
    try:
        parsed = int(float(str(value).strip()))
    except (TypeError, ValueError):
        parsed = default
    return max(floor, min(ceiling, parsed))


def parse_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def parse_csv(value: Any, *, upper: bool = True) -> list[str]:
    if value is None:
        return []
    parts = [str(item) for item in value] if isinstance(value, (list, tuple, set)) else str(value).split(",")
    out: list[str] = []
    for part in parts:
        token = part.strip()
        if not token:
            continue
        token = token.upper() if upper else token.lower()
        if token not in out:
            out.append(token)
    return out


def country_codes(value: Any) -> list[str]:
    """CSV of country tokens mapped onto awareness ISO-2 codes. ALL or empty means no filter."""
    codes: list[str] = []
    for token in parse_csv(value):
        if token == "ALL":
            return []
        code = _COUNTRY_ALIASES.get(token, token)
        if code not in codes:
            codes.append(code)
    return codes


def importance_level(value: Any, default: int = 1) -> int:
    if isinstance(value, str) and value.strip().lower() in _IMPORTANCE_WORDS:
        return _IMPORTANCE_WORDS[value.strip().lower()]
    return parse_int(value, default=default, floor=1, ceiling=3)


def client_for(fn: Any) -> AwarenessClient:
    """Injected test seam (``fn._awareness``) or the process-wide client."""
    injected = getattr(fn, "_awareness", None)
    return injected if injected is not None else get_awareness_client()


async def aw_get(fn: Any, path: str, params: dict[str, Any] | None = None) -> tuple[AwarenessResponse | None, str | None]:
    """GET one awareness endpoint. Returns ``(response, None)`` or ``(None, reason)``."""
    try:
        return await client_for(fn).get(path, params or {}), None
    except AwarenessUnavailable as exc:
        return None, exc.reason


def merge_meta(responses: Iterable[AwarenessResponse]) -> dict[str, Any]:
    """Merged provider health across answered awareness calls."""
    providers: list[dict[str, Any]] = []
    seen: set[str] = set()
    notes: list[str] = []
    generated: list[str] = []
    feed_health: Any = None
    stale: list[str] = []
    for resp in responses:
        for item in resp.providers:
            key = f"{item.get('provider')}|{item.get('status')}"
            if key not in seen:
                seen.add(key)
                providers.append(item)
        for note in resp.notes:
            if note not in notes:
                notes.append(note)
        if resp.generated_at:
            generated.append(resp.generated_at)
        if feed_health is None and resp.meta.get("feed_health") is not None:
            feed_health = resp.meta.get("feed_health")
        stale.extend(resp.stale_providers)
    return {
        "providers": providers,
        "generated_at": max(generated) if generated else None,
        "notes": notes,
        "feed_health": feed_health,
        "stale_providers": sorted(set(stale)),
    }


def data_meta(responses: Iterable[AwarenessResponse]) -> dict[str, Any]:
    """The ``data.meta`` block that panes embed for ProviderHealthStrip."""
    merged = merge_meta(responses)
    return {key: merged[key] for key in ("providers", "generated_at", "notes", "feed_health")}


def provenance_metadata(
    responses: Iterable[AwarenessResponse],
    *,
    provider_errors: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """FunctionResult.metadata for an answered awareness call (live or cached)."""
    merged = merge_meta(responses)
    stale = bool(merged["stale_providers"])
    out: dict[str, Any] = {
        "data_mode": "cached_snapshot" if stale else "live_official",
        "live": not stale,
        "provider": PROVIDER,
        "providers": merged["providers"],
        "feed_health": merged["feed_health"],
        "generated_at": merged["generated_at"],
        "notes": merged["notes"],
        "provider_errors": list(provider_errors or []),
    }
    if extra:
        out.update(extra)
    return out


def unavailable_result(
    code: str,
    instrument: Instrument | None,
    reason: str,
    *,
    extra: dict[str, Any] | None = None,
) -> FunctionResult:
    """Honest envelope when awareness could not answer at all."""
    data: dict[str, Any] = {
        "status": "provider_unavailable",
        "reason": reason,
        "rows": [],
        "next_actions": [UNAVAILABLE_NEXT_ACTION],
        "meta": {"providers": [], "generated_at": None, "notes": [], "feed_health": None},
    }
    if extra:
        data.update(extra)
    return FunctionResult(
        code=code,
        instrument=instrument,
        data=data,
        sources=[NO_LIVE_SOURCE],
        warnings=[reason],
        metadata={
            "fallback": True,
            "live": False,
            "data_mode": "provider_unavailable",
            "provider": PROVIDER,
            "provider_errors": [reason],
        },
    )


def provider_name(source: Any) -> str | None:
    """Provider label from a live ProviderRef ``{provider, url, fetched_at, basis}`` or a plain string.

    Awareness returns ``source`` as an object on every holiday row. The UI renders this value as text,
    so the function layer always hands out the provider name, never the object.
    """
    if isinstance(source, dict):
        text = str(source.get("provider") or "").strip()
        return text or None
    if source is None:
        return None
    text = str(source).strip()
    return text or None


def holiday_row(item: dict[str, Any]) -> dict[str, Any]:
    """Awareness holiday record -> the HolidayRow shape of the payload contract.

    ``source`` is the provider name (string). The full ProviderRef stays in ``source_ref``.
    """
    raw_source = item.get("source")
    return {
        "date": item.get("date"),
        "country": item.get("country"),
        "exchange": item.get("exchange"),
        "name": item.get("name"),
        "local_name": item.get("local_name"),
        "kind": item.get("kind"),
        "early_close_time": item.get("early_close_time"),
        "source": provider_name(raw_source),
        "source_ref": dict(raw_source) if isinstance(raw_source, dict) else None,
    }


def _date_value(value: Any) -> str | None:
    """Return an ISO 8601 string for any date-like value.

    BugHunt 2026-05-24: yfinance often hands back calendar values as
    single-element lists like ``[datetime.date(2026, 7, 30)]``. The previous
    implementation fell through to ``str(value)`` and emitted the literal
    Python repr ``"[datetime.date(2026, 7, 30)]"`` into the UI. We now unwrap
    one-element list/tuple/set/Series values and ISO-format each candidate
    before stringifying.
    """
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        for item in value:
            if item is None:
                continue
            converted = _date_value(item)
            if converted:
                return converted
        return None
    if hasattr(value, "tolist"):
        try:
            unwrapped = value.tolist()
        except Exception:
            unwrapped = None
        if isinstance(unwrapped, list):
            return _date_value(unwrapped)
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text or None


def _scalar_value(value: Any) -> Any:
    if isinstance(value, (list, tuple, set)):
        # BugHunt 2026-05-24: yfinance calendar values are wrapped in
        # single-element lists. Returning them raw made the UI render the
        # literal Python repr instead of a usable scalar/date. Try to ISO
        # the inner date(s) if any; otherwise return the list of normalised
        # scalars so downstream JSON encoding stays safe.
        converted = [_scalar_value(item) for item in value]
        if len(converted) == 1:
            return converted[0]
        return converted
    if isinstance(value, dict):
        return value
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        return _date_value(value)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value
