"""Multi-watchlist + saved searches persistence (SQLite).

Server-side single-user store. Multi-tenant variant comes after auth.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


_DB = Path("runtime/userdata.sqlite")


def _db() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_DB))
    con.execute("""
        CREATE TABLE IF NOT EXISTS watchlists (
            user_id TEXT NOT NULL,
            name    TEXT NOT NULL,
            symbols TEXT NOT NULL,
            updated INTEGER NOT NULL,
            PRIMARY KEY (user_id, name)
        )""")
    con.execute("""
        CREATE TABLE IF NOT EXISTS saved_searches (
            user_id TEXT NOT NULL,
            name    TEXT NOT NULL,
            query   TEXT NOT NULL,
            asset_class TEXT NOT NULL,
            updated INTEGER NOT NULL,
            PRIMARY KEY (user_id, name)
        )""")
    con.commit()
    return con


# ── Watchlists ──
def list_watchlists(user_id: str = "local") -> list[dict[str, Any]]:
    con = _db()
    rows = con.execute(
        "SELECT name, symbols, updated FROM watchlists WHERE user_id = ? ORDER BY updated DESC",
        [user_id],
    ).fetchall()
    con.close()
    return [{"name": r[0], "symbols": json.loads(r[1] or "[]"), "updated": r[2]}
            for r in rows]


def save_watchlist(name: str, symbols: list[str], user_id: str = "local") -> None:
    con = _db()
    con.execute(
        "INSERT OR REPLACE INTO watchlists(user_id, name, symbols, updated) VALUES (?,?,?,?)",
        [user_id, name, json.dumps([s.upper() for s in symbols]), int(time.time())],
    )
    con.commit(); con.close()


def delete_watchlist(name: str, user_id: str = "local") -> bool:
    con = _db()
    cur = con.execute("DELETE FROM watchlists WHERE user_id = ? AND name = ?",
                       [user_id, name])
    con.commit()
    n = cur.rowcount
    con.close()
    return n > 0


# ── Saved searches ──
def list_saved_searches(user_id: str = "local") -> list[dict[str, Any]]:
    con = _db()
    rows = con.execute(
        "SELECT name, query, asset_class, updated FROM saved_searches WHERE user_id = ? ORDER BY updated DESC",
        [user_id],
    ).fetchall()
    con.close()
    return [{"name": r[0], "query": r[1], "asset_class": r[2], "updated": r[3]}
            for r in rows]


def save_search(name: str, query: str, asset_class: str = "equity",
                user_id: str = "local") -> None:
    con = _db()
    con.execute(
        "INSERT OR REPLACE INTO saved_searches(user_id, name, query, asset_class, updated) VALUES (?,?,?,?,?)",
        [user_id, name, query, asset_class, int(time.time())],
    )
    con.commit(); con.close()


def delete_saved_search(name: str, user_id: str = "local") -> bool:
    con = _db()
    cur = con.execute("DELETE FROM saved_searches WHERE user_id = ? AND name = ?",
                       [user_id, name])
    con.commit()
    n = cur.rowcount
    con.close()
    return n > 0
