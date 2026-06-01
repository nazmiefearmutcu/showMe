"""Saved-articles reading-list persistence (SQLite).

Backs the READ ("Reading List") function. Articles are saved from CN / NI /
NSE / TOP via a "Save" action; READ surfaces the queue with read/unread state
and tag/symbol filters.

This is real, durable CRUD persistence — the same on-disk pattern used by the
watchlist store (``showme.engine.services.watchlist_store``): connections go
through ``persistence_helpers.open_sqlite`` (WAL + busy_timeout) and the DB
file is resolved via ``showme.app_paths.runtime_path`` so dev / tests / the
packaged bundle all agree on where state lives.

Single-user server-side store (``user_id="local"``). Multi-tenant variant
comes after auth, mirroring the watchlist store.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from showme.app_paths import runtime_path
from showme.persistence_helpers import open_sqlite

_VALID_STATUSES = ("unread", "in_progress", "read", "archived")
_MAX_LIMIT = 200
_MAX_TITLE_LEN = 500
_MAX_TAGS = 24


def _db_file():
    return runtime_path("reading_list.sqlite")


def _db() -> sqlite3.Connection:
    con = open_sqlite(_db_file())
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS saved_articles (
            user_id        TEXT NOT NULL,
            article_id     TEXT NOT NULL,
            url            TEXT,
            title          TEXT NOT NULL,
            source         TEXT,
            matched_symbol TEXT,
            published_utc  TEXT,
            tags           TEXT NOT NULL DEFAULT '[]',
            status         TEXT NOT NULL DEFAULT 'unread',
            saved_utc      TEXT NOT NULL,
            read_utc       TEXT,
            saved_ts       INTEGER NOT NULL,
            PRIMARY KEY (user_id, article_id)
        )
        """
    )
    con.commit()
    return con


@dataclass
class SavedArticle:
    """A single saved reading-list item."""

    article_id: str
    url: str | None
    title: str
    source: str | None = None
    matched_symbol: str | None = None
    published_utc: str | None = None
    tags: list[str] = field(default_factory=list)
    status: str = "unread"
    saved_utc: str | None = None
    read_utc: str | None = None

    def to_row(self) -> dict[str, Any]:
        return {
            "article_id": self.article_id,
            "url": self.url,
            "title": self.title,
            "source": self.source,
            "matched_symbol": self.matched_symbol,
            "published_utc": self.published_utc,
            "tags": list(self.tags or []),
            "status": self.status,
            "saved_utc": self.saved_utc,
            "read_utc": self.read_utc,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_article_id(url: str | None, title: str) -> str:
    """Stable id from the url (preferred) or the title — dedupes re-saves."""
    seed = (url or title or "").strip().lower()
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _normalize_status(status: str | None) -> str:
    s = (status or "unread").strip().lower()
    return s if s in _VALID_STATUSES else "unread"


def _normalize_tags(tags: Any) -> list[str]:
    if not tags:
        return []
    if isinstance(tags, str):
        items = [t.strip() for t in tags.split(",")]
    else:
        try:
            items = [str(t).strip() for t in tags]
        except TypeError:
            return []
    out: list[str] = []
    seen: set[str] = set()
    for t in items:
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
        if len(out) >= _MAX_TAGS:
            break
    return out


class ReadingListStore:
    """SQLite-backed saved-articles store for the READ function."""

    def __init__(self, user_id: str = "local") -> None:
        self.user_id = user_id

    # ── write side ──
    def save(self, article: SavedArticle) -> SavedArticle:
        """Insert (or update-in-place) a saved article. Returns the stored row."""
        title = (article.title or "").strip()[:_MAX_TITLE_LEN]
        if not title:
            raise ValueError("saved article requires a non-empty title")
        aid = article.article_id or _make_article_id(article.url, title)
        tags = _normalize_tags(article.tags)
        status = _normalize_status(article.status)
        saved_utc = article.saved_utc or _now_iso()
        con = _db()
        try:
            existing = con.execute(
                "SELECT saved_utc, saved_ts FROM saved_articles WHERE user_id=? AND article_id=?",
                [self.user_id, aid],
            ).fetchone()
            if existing:
                saved_utc = existing[0]
                saved_ts = int(existing[1])
            else:
                saved_ts = int(time.time())
            con.execute(
                """
                INSERT OR REPLACE INTO saved_articles
                    (user_id, article_id, url, title, source, matched_symbol,
                     published_utc, tags, status, saved_utc, read_utc, saved_ts)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    self.user_id, aid, article.url, title, article.source,
                    (article.matched_symbol or None),
                    article.published_utc, json.dumps(tags), status,
                    saved_utc, article.read_utc, saved_ts,
                ],
            )
            con.commit()
        finally:
            con.close()
        return SavedArticle(
            article_id=aid, url=article.url, title=title, source=article.source,
            matched_symbol=article.matched_symbol, published_utc=article.published_utc,
            tags=tags, status=status, saved_utc=saved_utc, read_utc=article.read_utc,
        )

    def mark(self, article_id: str, status: str) -> bool:
        """Transition an item's status. Returns True if a row was updated."""
        status = _normalize_status(status)
        read_utc = _now_iso() if status in ("read", "archived") else None
        con = _db()
        try:
            cur = con.execute(
                "UPDATE saved_articles SET status=?, read_utc=? WHERE user_id=? AND article_id=?",
                [status, read_utc, self.user_id, article_id],
            )
            con.commit()
            return cur.rowcount > 0
        finally:
            con.close()

    def delete(self, article_id: str) -> bool:
        con = _db()
        try:
            cur = con.execute(
                "DELETE FROM saved_articles WHERE user_id=? AND article_id=?",
                [self.user_id, article_id],
            )
            con.commit()
            return cur.rowcount > 0
        finally:
            con.close()

    # ── read side ──
    def list(
        self,
        *,
        status: list[str] | None = None,
        tags: list[str] | None = None,
        symbols: list[str] | None = None,
        limit: int = 50,
    ) -> list[SavedArticle]:
        """Return saved articles (saved-time desc), applying the given filters."""
        limit = max(1, min(int(limit or 50), _MAX_LIMIT))
        con = _db()
        try:
            rows = con.execute(
                "SELECT article_id, url, title, source, matched_symbol, published_utc, "
                "tags, status, saved_utc, read_utc FROM saved_articles "
                "WHERE user_id=? ORDER BY saved_ts DESC",
                [self.user_id],
            ).fetchall()
        finally:
            con.close()

        status_set = {s.strip().lower() for s in status} if status else None
        symbol_set = {s.strip().upper() for s in symbols} if symbols else None
        tag_set = {t.strip().lower() for t in tags} if tags else None

        out: list[SavedArticle] = []
        for r in rows:
            row_tags = json.loads(r[6] or "[]")
            row_status = r[7]
            row_symbol = (r[4] or "").upper()
            if status_set and row_status not in status_set:
                continue
            if symbol_set and row_symbol not in symbol_set:
                continue
            if tag_set and not ({t.lower() for t in row_tags} & tag_set):
                continue
            out.append(
                SavedArticle(
                    article_id=r[0], url=r[1], title=r[2], source=r[3],
                    matched_symbol=r[4], published_utc=r[5], tags=row_tags,
                    status=row_status, saved_utc=r[8], read_utc=r[9],
                )
            )
            if len(out) >= limit:
                break
        return out

    def counts(self) -> dict[str, int]:
        """Return per-status counts over the WHOLE queue (unfiltered)."""
        con = _db()
        try:
            rows = con.execute(
                "SELECT status, COUNT(*) FROM saved_articles WHERE user_id=? GROUP BY status",
                [self.user_id],
            ).fetchall()
        finally:
            con.close()
        out = {s: 0 for s in _VALID_STATUSES}
        for status, n in rows:
            out[status if status in out else "unread"] = int(n)
        return out

    def clear(self) -> int:
        con = _db()
        try:
            cur = con.execute("DELETE FROM saved_articles WHERE user_id=?", [self.user_id])
            con.commit()
            return cur.rowcount
        finally:
            con.close()


__all__ = ["ReadingListStore", "SavedArticle"]
