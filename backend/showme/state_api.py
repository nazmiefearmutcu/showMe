"""Round 25 — read-side endpoints over the Faz B portfolio.db.

The Round 22 importer writes positions + trades into a SQLite database
under ``~/Library/Application Support/showMe/data/portfolio.db``. The
TRAN native pane and the watchlist/blotter need read-only access to
those rows without having to re-import every refresh; this module
exposes them through three small endpoints:

  * ``GET /api/state/positions`` — current snapshot, newest-first.
  * ``GET /api/state/trades?limit=200`` — trade blotter, closed-first.
  * ``GET /api/state/migrations`` — audit log (most-recent first).

The functions are deliberately framework-light so they can be unit
tested without spinning up FastAPI: they take a ``Path`` to the DB and
return plain dicts.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .migration import default_target


@dataclass
class StateRead:
    rows: list[dict[str, Any]]
    total: int
    source: str


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(str(db_path))
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    raw = out.pop("raw_json", None)
    if raw:
        try:
            out["raw"] = json.loads(raw)
        except Exception:  # noqa: BLE001 — keep the original blob on parse failure
            out["raw"] = raw
    return out


def list_positions(db_path: Path | None = None) -> StateRead:
    target = db_path or default_target()
    if not target.exists():
        return StateRead(rows=[], total=0, source=str(target))
    conn = _connect(target)
    try:
        rows = [
            _decode_row(r)
            for r in conn.execute(
                "SELECT id, symbol, side, quantity, entry_price, current_price, "
                "unrealized_pnl, realized_pnl, leverage, stop_loss, take_profit, "
                "trailing_stop_price, opened_at, mode, raw_json, imported_at, source "
                "FROM positions ORDER BY (unrealized_pnl IS NULL), unrealized_pnl DESC, "
                "imported_at DESC"
            ).fetchall()
        ]
    finally:
        conn.close()
    return StateRead(rows=rows, total=len(rows), source=str(target))


def list_trades(
    db_path: Path | None = None,
    *,
    limit: int = 200,
    symbol: str | None = None,
) -> StateRead:
    target = db_path or default_target()
    if not target.exists():
        return StateRead(rows=[], total=0, source=str(target))
    conn = _connect(target)
    try:
        sql = (
            "SELECT id, trade_id, symbol, side, quantity, entry_price, exit_price, "
            "realized_pnl, opened_at, closed_at, mode, raw_json, imported_at, source "
            "FROM trades"
        )
        params: list[Any] = []
        if symbol:
            sql += " WHERE symbol = ?"
            params.append(symbol.upper())
        sql += (
            " ORDER BY (closed_at IS NULL), closed_at DESC, "
            "(opened_at IS NULL), opened_at DESC LIMIT ?"
        )
        params.append(int(limit))
        rows = [_decode_row(r) for r in conn.execute(sql, params).fetchall()]
        total = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    finally:
        conn.close()
    return StateRead(rows=rows, total=int(total), source=str(target))


def list_migrations(db_path: Path | None = None, *, limit: int = 50) -> StateRead:
    target = db_path or default_target()
    if not target.exists():
        return StateRead(rows=[], total=0, source=str(target))
    conn = _connect(target)
    try:
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT id, source, started_at, finished_at, summary_json "
                "FROM migrations ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        ]
        for r in rows:
            blob = r.pop("summary_json", None)
            if blob:
                try:
                    r["summary"] = json.loads(blob)
                except Exception:  # noqa: BLE001
                    r["summary"] = blob
    finally:
        conn.close()
    return StateRead(rows=rows, total=len(rows), source=str(target))
