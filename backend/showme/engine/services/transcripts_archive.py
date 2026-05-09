"""Transcripts archive — SQLite (with FTS5 fallback) for earnings call transcripts.

Schema:
    transcripts(id PK, symbol, company, quarter, fiscal_year, event_date,
                source, url, content, summary, sentiment, ingested_at)
    transcripts_fts (FTS5 virtual table over content+summary)

Search returns ranked matches with snippet().
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

DB_PATH = Path("runtime/transcripts.sqlite")
_LOCK = threading.RLock()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _has_fts5(conn: sqlite3.Connection) -> bool:
    """Per-connection FTS5 capability probe — no module-level cache."""
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS _fts_check USING fts5(x);"
        )
        conn.execute("DROP TABLE IF EXISTS _fts_check;")
        return True
    except sqlite3.OperationalError:
        return False


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS transcripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            company TEXT,
            quarter TEXT,
            fiscal_year INTEGER,
            event_date TEXT,
            source TEXT,
            url TEXT,
            content TEXT,
            summary TEXT,
            sentiment REAL,
            ingested_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_transcripts_symbol ON transcripts(symbol);
        CREATE INDEX IF NOT EXISTS idx_transcripts_event_date ON transcripts(event_date);
        """
    )
    if _has_fts5(conn):
        # Self-contained FTS5 (no external-content mode → simpler upsert).
        conn.executescript(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts
            USING fts5(symbol, company, quarter, content, summary,
                       tokenize='porter');
            """
        )


def upsert(
    *,
    symbol: str,
    company: str | None = None,
    quarter: str | None = None,
    fiscal_year: int | None = None,
    event_date: str | None = None,
    source: str | None = None,
    url: str | None = None,
    content: str = "",
    summary: str | None = None,
    sentiment: float | None = None,
) -> int:
    with _LOCK, _connect() as conn:
        _ensure_schema(conn)
        # Idempotent: same (symbol, quarter, fiscal_year, event_date) → upsert.
        row = conn.execute(
            "SELECT id FROM transcripts WHERE symbol=? AND quarter IS ? "
            "AND fiscal_year IS ? AND event_date IS ?",
            (symbol, quarter, fiscal_year, event_date),
        ).fetchone()
        if row:
            tid = row["id"]
            conn.execute(
                "UPDATE transcripts SET company=?, source=?, url=?, "
                "content=?, summary=?, sentiment=?, ingested_at=? WHERE id=?",
                (company, source, url, content, summary, sentiment,
                 datetime.utcnow().isoformat(), tid),
            )
        else:
            cur = conn.execute(
                "INSERT INTO transcripts(symbol, company, quarter, fiscal_year, "
                "event_date, source, url, content, summary, sentiment) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (symbol, company, quarter, fiscal_year, event_date,
                 source, url, content, summary, sentiment),
            )
            tid = cur.lastrowid
        if _has_fts5(conn):
            conn.execute(
                "DELETE FROM transcripts_fts WHERE rowid=?", (tid,)
            )
            conn.execute(
                "INSERT INTO transcripts_fts(rowid, symbol, company, quarter, content, summary) "
                "VALUES (?,?,?,?,?,?)",
                (tid, symbol, company or "", quarter or "", content, summary or ""),
            )
        conn.commit()
        return tid


def get(transcript_id: int) -> dict[str, Any] | None:
    with _LOCK, _connect() as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT * FROM transcripts WHERE id=?", (transcript_id,)
        ).fetchone()
        return dict(row) if row else None


def list_for_symbol(symbol: str, *, limit: int = 50) -> list[dict[str, Any]]:
    with _LOCK, _connect() as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT id, symbol, company, quarter, fiscal_year, event_date, "
            "source, url, summary, sentiment, ingested_at "
            "FROM transcripts WHERE symbol=? ORDER BY event_date DESC LIMIT ?",
            (symbol, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def search(
    query: str,
    *,
    symbol: str | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Full-text search. Falls back to LIKE if FTS5 unavailable."""
    with _LOCK, _connect() as conn:
        _ensure_schema(conn)
        if _has_fts5(conn) and query.strip():
            try:
                where_sym = ""
                bind: list[Any] = [query]
                if symbol:
                    where_sym = " AND t.symbol=?"
                    bind.append(symbol)
                bind.append(limit)
                rows = conn.execute(
                    "SELECT t.id, t.symbol, t.company, t.quarter, t.fiscal_year, "
                    "t.event_date, t.source, t.url, t.summary, t.sentiment, "
                    "snippet(transcripts_fts, 3, '[', ']', '…', 20) AS snippet, "
                    "bm25(transcripts_fts) AS rank "
                    "FROM transcripts_fts JOIN transcripts t ON t.id = transcripts_fts.rowid "
                    "WHERE transcripts_fts MATCH ?" + where_sym +
                    " ORDER BY rank LIMIT ?",
                    bind,
                ).fetchall()
                return [dict(r) for r in rows]
            except sqlite3.OperationalError:
                pass
        # Fallback: LIKE
        where_sym = ""
        like = f"%{query}%"
        bind = [like, like]
        if symbol:
            where_sym = " AND symbol=?"
            bind.append(symbol)
        bind.append(limit)
        rows = conn.execute(
            "SELECT id, symbol, company, quarter, fiscal_year, event_date, "
            "source, url, summary, sentiment, "
            "substr(content, max(1, instr(lower(content), lower(?))-50), 200) AS snippet "
            "FROM transcripts WHERE (content LIKE ? OR summary LIKE ?)" + where_sym +
            " ORDER BY event_date DESC LIMIT ?",
            [query, *bind],
        ).fetchall()
        return [dict(r) for r in rows]


def stats() -> dict[str, Any]:
    with _LOCK, _connect() as conn:
        _ensure_schema(conn)
        n = conn.execute("SELECT COUNT(*) AS n FROM transcripts").fetchone()["n"]
        symbols = conn.execute(
            "SELECT COUNT(DISTINCT symbol) AS n FROM transcripts"
        ).fetchone()["n"]
        latest = conn.execute(
            "SELECT MAX(ingested_at) AS t FROM transcripts"
        ).fetchone()["t"]
    with _LOCK, _connect() as conn:
        fts5_active = _has_fts5(conn)
    return {
        "n_transcripts": n,
        "n_symbols": symbols,
        "latest_ingest": latest,
        "fts5": fts5_active,
        "db_path": str(DB_PATH),
    }


def delete(transcript_id: int) -> bool:
    with _LOCK, _connect() as conn:
        _ensure_schema(conn)
        cur = conn.execute("DELETE FROM transcripts WHERE id=?", (transcript_id,))
        if _has_fts5(conn):
            conn.execute("DELETE FROM transcripts_fts WHERE rowid=?", (transcript_id,))
        conn.commit()
        return cur.rowcount > 0
