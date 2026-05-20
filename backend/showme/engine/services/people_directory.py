"""People directory — local SQLite store for executives/analysts/investors.

Used by PEOP and CONTACTS functions. Best-effort enrichment from open
sources (OpenCorporates, SEC EDGAR insider filings, manual entries).

Schema:
    people(id PK, full_name, role, company, email, linkedin, twitter,
            bio, tags JSON, ingested_at)
    people_roles(id PK, person_id, company, title, start_date, end_date, source)
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from showme.app_paths import runtime_path

_LOCK = threading.RLock()


def _db_path():
    return runtime_path("people.sqlite")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS people (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            role TEXT,
            company TEXT,
            email TEXT,
            linkedin TEXT,
            twitter TEXT,
            bio TEXT,
            tags_json TEXT DEFAULT '[]',
            ingested_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_people_name ON people(full_name);
        CREATE INDEX IF NOT EXISTS idx_people_company ON people(company);
        CREATE TABLE IF NOT EXISTS people_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id INTEGER NOT NULL,
            company TEXT,
            title TEXT,
            start_date TEXT,
            end_date TEXT,
            source TEXT,
            FOREIGN KEY (person_id) REFERENCES people(id)
        );
        """
    )


def upsert_person(
    *,
    full_name: str,
    role: str | None = None,
    company: str | None = None,
    email: str | None = None,
    linkedin: str | None = None,
    twitter: str | None = None,
    bio: str | None = None,
    tags: list[str] | None = None,
) -> int:
    with _LOCK, _connect() as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT id FROM people WHERE full_name=? AND COALESCE(company,'')=COALESCE(?,'')",
            (full_name, company),
        ).fetchone()
        if row:
            pid = row["id"]
            conn.execute(
                "UPDATE people SET role=?, email=?, linkedin=?, twitter=?, "
                "bio=?, tags_json=?, ingested_at=? WHERE id=?",
                (role, email, linkedin, twitter, bio,
                 json.dumps(tags or []), datetime.now(timezone.utc).isoformat(), pid),
            )
        else:
            cur = conn.execute(
                "INSERT INTO people(full_name, role, company, email, linkedin, twitter, bio, tags_json) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (full_name, role, company, email, linkedin, twitter, bio,
                 json.dumps(tags or [])),
            )
            pid = cur.lastrowid
        conn.commit()
        return pid


def add_role(
    person_id: int, *, company: str, title: str,
    start_date: str | None = None, end_date: str | None = None,
    source: str | None = None,
) -> int:
    with _LOCK, _connect() as conn:
        _ensure_schema(conn)
        cur = conn.execute(
            "INSERT INTO people_roles(person_id, company, title, start_date, end_date, source) "
            "VALUES (?,?,?,?,?,?)",
            (person_id, company, title, start_date, end_date, source),
        )
        conn.commit()
        return cur.lastrowid


def search(query: str, *, limit: int = 25) -> list[dict[str, Any]]:
    with _LOCK, _connect() as conn:
        _ensure_schema(conn)
        like = f"%{query}%"
        rows = conn.execute(
            "SELECT * FROM people "
            "WHERE full_name LIKE ? OR company LIKE ? OR role LIKE ? OR bio LIKE ? "
            "ORDER BY ingested_at DESC LIMIT ?",
            (like, like, like, like, limit),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["tags"] = json.loads(d.pop("tags_json", "[]") or "[]")
            d["roles"] = [
                dict(rr) for rr in conn.execute(
                    "SELECT company, title, start_date, end_date, source "
                    "FROM people_roles WHERE person_id=? ORDER BY start_date DESC",
                    (d["id"],),
                ).fetchall()
            ]
            out.append(d)
        return out


def get(person_id: int) -> dict[str, Any] | None:
    with _LOCK, _connect() as conn:
        _ensure_schema(conn)
        row = conn.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["tags"] = json.loads(d.pop("tags_json", "[]") or "[]")
        d["roles"] = [
            dict(r) for r in conn.execute(
                "SELECT company, title, start_date, end_date, source "
                "FROM people_roles WHERE person_id=? ORDER BY start_date DESC",
                (person_id,),
            ).fetchall()
        ]
        return d


def list_for_company(company: str, *, limit: int = 50) -> list[dict[str, Any]]:
    with _LOCK, _connect() as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT * FROM people WHERE company LIKE ? ORDER BY full_name LIMIT ?",
            (f"%{company}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]


def stats() -> dict[str, Any]:
    with _LOCK, _connect() as conn:
        _ensure_schema(conn)
        n = conn.execute("SELECT COUNT(*) AS n FROM people").fetchone()["n"]
        nc = conn.execute(
            "SELECT COUNT(DISTINCT company) AS n FROM people"
        ).fetchone()["n"]
        return {"n_people": n, "n_companies": nc, "db_path": str(_db_path())}


def delete(person_id: int) -> bool:
    with _LOCK, _connect() as conn:
        _ensure_schema(conn)
        cur = conn.execute("DELETE FROM people WHERE id=?", (person_id,))
        conn.execute("DELETE FROM people_roles WHERE person_id=?", (person_id,))
        conn.commit()
        return cur.rowcount > 0
