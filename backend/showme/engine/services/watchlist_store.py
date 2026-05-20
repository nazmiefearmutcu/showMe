"""Multi-watchlist + saved searches persistence (SQLite).

Server-side single-user store. Multi-tenant variant comes after auth.

Per ARCH-09 P2: connections go through ``persistence_helpers.open_sqlite``
so we get WAL + busy_timeout instead of bare ``sqlite3.connect``.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from typing import Any

from showme.app_paths import runtime_path
from showme.persistence_helpers import open_sqlite


# Per FUNC-08 P1: validate watchlist symbols server-side too so a stale
# UI cannot persist broken tickers that pollute the polling loop forever.
SYMBOL_RE = re.compile(r"^[A-Z0-9.\-=^:]{1,16}$")
_MAX_SYMBOLS_PER_LIST = 200
_MAX_NAME_LEN = 64


def _db_file():
    return runtime_path("userdata.sqlite")


def _db() -> sqlite3.Connection:
    con = open_sqlite(_db_file())
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


def normalize_symbol(symbol: str) -> str | None:
    """Return ``symbol`` upper-cased if it matches :data:`SYMBOL_RE`, else ``None``."""
    if not symbol:
        return None
    cleaned = symbol.strip().upper()
    if SYMBOL_RE.match(cleaned):
        return cleaned
    return None


def normalize_symbols(symbols: list[str]) -> list[str]:
    """Drop any symbol that fails :func:`normalize_symbol`; cap at the max size."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        cleaned = normalize_symbol(str(raw))
        if cleaned is None or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
        if len(out) >= _MAX_SYMBOLS_PER_LIST:
            break
    return out


def _validate_name(name: str) -> str:
    name = (name or "").strip()
    if not name or len(name) > _MAX_NAME_LEN:
        raise ValueError("watchlist name must be 1..%d chars" % _MAX_NAME_LEN)
    return name


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


def save_watchlist(name: str, symbols: list[str], user_id: str = "local") -> list[str]:
    """Persist ``symbols`` under ``name`` and return the validated/normalised list."""
    name = _validate_name(name)
    cleaned = normalize_symbols(symbols)
    con = _db()
    con.execute(
        "INSERT OR REPLACE INTO watchlists(user_id, name, symbols, updated) VALUES (?,?,?,?)",
        [user_id, name, json.dumps(cleaned), int(time.time())],
    )
    con.commit(); con.close()
    return cleaned


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
