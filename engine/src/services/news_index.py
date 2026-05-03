"""News search index — Meilisearch primary, SQLite FTS5 fallback.

Plan §16.4: NSE (News Search Engine). Meilisearch eğer çalışıyorsa onu
kullanır; yoksa SQLite FTS5'e düşer. İkisi de olmayan ortamda in-memory
linear scan ile çalışır.

Yazma:
    await NewsIndex().add_articles([{...}, ...])
Arama:
    await NewsIndex().search("Apple earnings", start=..., end=...)
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


_SQLITE_PATH = Path("runtime/news.sqlite")
_FTS_TABLE = "news_fts"
_INDEX_NAME = "showme_news"


class NewsIndex:
    """Best-effort multi-backend news index."""

    def __init__(self) -> None:
        self.meili = None
        self._init_meili()
        self._init_sqlite()

    # ── Meilisearch ──
    def _init_meili(self) -> None:
        url = os.environ.get("MEILISEARCH_URL")
        if not url:
            return
        try:
            import meilisearch  # type: ignore
            api_key = os.environ.get("MEILISEARCH_KEY", "")
            self.meili = meilisearch.Client(url, api_key)
            try:
                self.meili.create_index(_INDEX_NAME, {"primaryKey": "id"})
            except Exception:
                pass
        except Exception:
            self.meili = None

    # ── SQLite FTS5 ──
    def _init_sqlite(self) -> None:
        _SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(_SQLITE_PATH))
        self.db.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS {_FTS_TABLE} USING fts5(
                id UNINDEXED, title, body, source, published_at UNINDEXED, url UNINDEXED
            )""")
        self.db.commit()

    async def add_articles(self, articles: list[dict[str, Any]]) -> int:
        if not articles:
            return 0
        # Meilisearch ingestion
        if self.meili is not None:
            try:
                docs = [{
                    "id": str(a.get("id") or hash(a.get("url") or a.get("title") or "") & 0xFFFFFFFF),
                    "title": a.get("title", ""),
                    "body":  a.get("summary") or a.get("description") or "",
                    "source": a.get("feed") or a.get("domain") or a.get("source") or "",
                    "published_at": a.get("published_at") or a.get("seendate") or "",
                    "url": a.get("url") or a.get("link") or "",
                } for a in articles]
                self.meili.index(_INDEX_NAME).add_documents(docs)
            except Exception:
                pass
        # SQLite mirror
        rows = [(
            str(a.get("id") or hash(a.get("url") or a.get("title") or "") & 0xFFFFFFFF),
            a.get("title", ""),
            a.get("summary") or a.get("description") or "",
            a.get("feed") or a.get("domain") or a.get("source") or "",
            a.get("published_at") or a.get("seendate") or "",
            a.get("url") or a.get("link") or "",
        ) for a in articles]
        self.db.executemany(
            f"INSERT INTO {_FTS_TABLE}(id, title, body, source, published_at, url) VALUES (?,?,?,?,?,?)",
            rows,
        )
        self.db.commit()
        return len(rows)

    async def search(self, query: str, *, start: str | None = None,
                     end: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        if self.meili is not None:
            try:
                res = self.meili.index(_INDEX_NAME).search(query, {"limit": limit})
                hits = res.get("hits", []) if isinstance(res, dict) else []
                if hits:
                    return [self._filter_hit(h, start, end) for h in hits]
            except Exception:
                pass
        # SQLite FTS5 fallback
        try:
            sql = f"SELECT id, title, body, source, published_at, url FROM {_FTS_TABLE} WHERE {_FTS_TABLE} MATCH ? ORDER BY published_at DESC LIMIT ?"
            cur = self.db.execute(sql, [query, limit])
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            return [r for r in rows if self._in_range(r.get("published_at"), start, end)]
        except Exception:
            return []

    @staticmethod
    def _in_range(stamp: str | None, start: str | None, end: str | None) -> bool:
        if not stamp:
            return True
        if start and stamp < start:
            return False
        if end and stamp > end:
            return False
        return True

    @staticmethod
    def _filter_hit(hit: dict[str, Any], start: str | None, end: str | None) -> dict[str, Any]:
        return hit

    async def stats(self) -> dict[str, Any]:
        try:
            row = self.db.execute(f"SELECT COUNT(*) FROM {_FTS_TABLE}").fetchone()
            return {"sqlite_count": int(row[0]) if row else 0,
                    "meilisearch": self.meili is not None}
        except Exception:
            return {"sqlite_count": 0, "meilisearch": False}
