"""READ — Reading List (saved-articles store).

Persistent reading list backed by the internal saved-articles store
(``showme.engine.services.reading_list_store.ReadingListStore``). Users save
articles from CN / NI / NSE / TOP via a Save action; READ surfaces the
in-progress queue, the read/unread state per item, optional symbol/status/tag
filters, and a one-click open-back-in-source link.

This is *real* CRUD-backed persistence (SQLite via the shared persistence
helpers + ``app_paths`` — the same on-disk pattern used by the watchlist
store) — not synthetic placeholder rows. When the store is empty READ returns
``rows=[]`` / ``articles=[]`` with a clear setup-hint warning rather than
fabricating headlines.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument

_VALID_STATUSES = ("unread", "in_progress", "read", "archived")

_FIELD_DICTIONARY: dict[str, str] = {
    "saved_utc": "ISO-8601 timestamp recording when the article was added to the queue.",
    "status": "Read state: unread / in_progress / read / archived.",
    "title": "Headline as captured at save time.",
    "matched_symbol": "Symbol tag carried in from the originating feed.",
    "source": "Publisher domain.",
    "tags": "User-supplied tags for the article.",
    "published_utc": "Original publish time (ISO-8601) when known.",
    "link": "Direct link to the source article (open-back-in-source action).",
    "article_id": "Stable url-hash id used to mark status / delete an item.",
    "read_utc": "When the item transitioned to read/archived, if applicable.",
}

_METHODOLOGY = (
    "READ is backed by the internal saved-articles store "
    "(showme.engine.services.reading_list_store.ReadingListStore), a SQLite database "
    "persisted via the shared persistence helpers (WAL + busy_timeout) and resolved through "
    "app_paths — the same on-disk CRUD pattern used by the watchlist store. Articles are "
    "saved from CN / NI / NSE / TOP via a Save action that writes "
    "{url, title, source, published_utc, matched_symbol, tags, status}. READ reads the store, "
    "applies the input filters (watchlist/symbols, status, tags), and returns rows in "
    "saved-time-descending order. Status transitions (unread -> in_progress -> read -> "
    "archived) are recorded server-side; READ surfaces the current status. When the store is "
    "empty, articles=[] with a setup-hint warning — no synthetic placeholder rows."
)


@FunctionRegistry.register
class READFunction(BaseFunction):
    code = "READ"
    name = "Reading List"
    category = "news"

    def _resolve_store(self) -> Any:
        """Return a ReadingListStore.

        Prefer an injected store on ``self.deps`` (so tests/mocks can swap it),
        otherwise build the default on-disk store, which resolves its own path
        via ``app_paths`` exactly like the watchlist store.
        """
        injected = getattr(self.deps, "reading_list_store", None)
        if injected is not None:
            return injected
        from showme.engine.services.reading_list_store import ReadingListStore

        return ReadingListStore()

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        as_of = datetime.now(timezone.utc).isoformat()

        # Filters: accept both the manifest `watchlist` and the standard
        # `symbols` alias; status/tags multiselect; limit 1..200.
        symbols = _parse_list(
            params.get("symbols") if params.get("symbols") is not None else params.get("watchlist")
        )
        status_filter = [s for s in _parse_list(params.get("status"), upper=False)
                         if s in _VALID_STATUSES] or None
        tags_filter = _parse_list(params.get("tags"), upper=False) or None
        limit = _int_param(params.get("limit", 50), default=50, min_value=1, max_value=200)

        base_meta = {
            "watchlist": symbols,
            "status_filter": status_filter,
            "tags_filter": tags_filter,
            "limit": limit,
            "data_mode": "cached_snapshot",
            "persistence": "sqlite_reading_list_v1",
        }

        try:
            store = self._resolve_store()
            items = store.list(
                status=status_filter,
                tags=tags_filter,
                symbols=symbols or None,
                limit=limit,
            )
            counts = store.counts()
        except Exception as exc:  # genuine I/O / DB failure — graceful fallback
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "as_of": as_of,
                    "rows": [],
                    "articles": [],
                    "article_count": 0,
                    "unread_count": 0,
                    "in_progress_count": 0,
                    "cards": _cards(0, 0, 0, as_of),
                    "summary": "Could not read the saved-articles store.",
                    "methodology": _METHODOLOGY,
                    "field_dictionary": _FIELD_DICTIONARY,
                    "next_actions": [
                        "Retry; if it persists, check reading_list.sqlite permissions.",
                    ],
                },
                sources=["no_live_source"],
                warnings=[f"Saved-articles store read failed: {exc!r}"],
                metadata={**base_meta, "store_present": False},
            )

        rows = [_serialize(a) for a in items]
        unread_count = int(counts.get("unread", 0))
        in_progress_count = int(counts.get("in_progress", 0))
        total_count = sum(int(v) for v in counts.values())

        warnings: list[str] = []
        if total_count == 0:
            warnings.append(
                "Reading list is empty — save articles from CN / NI / NSE / TOP "
                "to populate your queue."
            )
        elif not rows:
            warnings.append(
                "No saved articles match the current filters; clear the status/tag/symbol "
                "filters to see the full queue."
            )

        status = "ok" if rows else "empty"
        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": status,
                "as_of": as_of,
                "rows": rows,
                "articles": rows,
                "article_count": len(rows),
                "unread_count": unread_count,
                "in_progress_count": in_progress_count,
                "cards": _cards(len(rows), unread_count, in_progress_count, as_of),
                "summary": (
                    f"{len(rows)} saved article(s) in view "
                    f"({unread_count} unread, {in_progress_count} in progress)."
                ),
                "methodology": _METHODOLOGY,
                "field_dictionary": _FIELD_DICTIONARY,
                "next_actions": [
                    "Open an item in its source via the link action.",
                    "Mark progress (unread -> in_progress -> read -> archived).",
                ],
            },
            sources=["internal_reading_list"],
            warnings=warnings,
            metadata={
                **base_meta,
                "store_present": True,
                "store_total": total_count,
                "counts": counts,
            },
        )


def _serialize(article: Any) -> dict[str, Any]:
    """Map a SavedArticle dataclass into the manifest table row shape."""
    return {
        "article_id": getattr(article, "article_id", None),
        "saved_utc": getattr(article, "saved_utc", None),
        "status": getattr(article, "status", "unread"),
        "title": getattr(article, "title", ""),
        "matched_symbol": getattr(article, "matched_symbol", None),
        "source": getattr(article, "source", None),
        "tags": list(getattr(article, "tags", []) or []),
        "published_utc": getattr(article, "published_utc", None),
        "link": getattr(article, "url", None),
        "read_utc": getattr(article, "read_utc", None),
    }


def _cards(article_count: int, unread: int, in_progress: int, as_of: str) -> dict[str, Any]:
    return {
        "article_count": article_count,
        "unread_count": unread,
        "in_progress_count": in_progress,
        "data_mode": "cached_snapshot",
        "as_of": as_of,
    }


def _parse_list(value: Any, *, upper: bool = True) -> list[str]:
    """Normalize a CSV string / iterable into a clean list of tokens."""
    if value is None:
        return []
    if isinstance(value, str):
        parts = [s.strip() for s in value.split(",") if s.strip()]
    elif isinstance(value, (list, tuple, set)):
        parts = [str(item or "").strip() for item in value]
        parts = [p for p in parts if p]
    else:
        text = str(value).strip()
        parts = [text] if text else []
    return [p.upper() for p in parts] if upper else parts


def _int_param(value: Any, *, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(min_value, min(parsed, max_value))


def _parse_symbol_list(value: Any) -> list[str]:
    """Back-compat alias for the upper-cased symbol parser.

    Kept so existing callers / regression tests that imported the old name
    keep working after the de-garbage rewrite (READ now backs a saved-articles
    reading list rather than a live watchlist fetch).
    """
    return _parse_list(value, upper=True)
