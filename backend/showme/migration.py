"""Faz B — ShowMe state importer.

One-shot copy of an external paper-book snapshot into the showMe SQLite
store under ``~/Library/Application Support/showMe/data/portfolio.db``.
By default the importer runs in **read-only mirror** mode: positions and
trades are loaded into ShowMe's tables but the source ``runtime/state.json``
is never written. Pass ``--writable`` to mark the rows as
`mode='writable'`; otherwise they stay frozen as a snapshot.

The importer is idempotent: re-running over an existing portfolio.db
upserts on `(symbol, side, opened_at)` so reimporting after a source
session restart doesn't double-count.

CLI:

    python -m showme.migration --engine ~/path/to/source \\
                               --to ~/Library/Application\\ Support/showMe/data/portfolio.db
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

LOG = logging.getLogger("showme.migration")


# ── Schema ───────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL,
    entry_price REAL,
    current_price REAL,
    unrealized_pnl REAL,
    realized_pnl REAL,
    leverage INTEGER,
    stop_loss REAL,
    take_profit REAL,
    trailing_stop_price REAL,
    opened_at TEXT,
    mode TEXT NOT NULL DEFAULT 'read_only',
    raw_json TEXT,
    imported_at TEXT NOT NULL,
    source TEXT NOT NULL,
    UNIQUE(symbol, side, opened_at)
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL,
    entry_price REAL,
    exit_price REAL,
    realized_pnl REAL,
    opened_at TEXT,
    closed_at TEXT,
    mode TEXT NOT NULL DEFAULT 'read_only',
    raw_json TEXT,
    imported_at TEXT NOT NULL,
    source TEXT NOT NULL,
    UNIQUE(trade_id, symbol)
);

CREATE TABLE IF NOT EXISTS migrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    summary_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
"""


@dataclass
class MigrationSummary:
    source: str
    target: str
    started_at: str
    finished_at: str
    positions_imported: int
    positions_skipped: int
    trades_imported: int
    trades_skipped: int
    daily_pnl: float | None
    paper_balance: float | None
    bot_start_time: str | None
    mode: str
    warnings: list[str]


# ── Helpers ──────────────────────────────────────────────────────────────

def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _iso_from_epoch(value: Any) -> str | None:
    if value is None:
        return None
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return str(value)
    if ts > 1e12:  # ms epoch
        ts = ts / 1000.0
    if ts < 10**8:
        # Looks like a duration in seconds, not a timestamp.
        return None
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def load_state(state_json: Path) -> dict[str, Any]:
    return json.loads(state_json.read_text())


def import_state(
    state: dict[str, Any],
    db_path: Path,
    *,
    source: str = "showme_import",
    writable: bool = False,
) -> MigrationSummary:
    """Insert positions + trades into the portfolio DB. Returns a summary."""
    started = time.time()
    conn = _connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO migrations(source, started_at) VALUES (?, ?)",
        (source, _iso_from_epoch(started) or ""),
    )
    migration_id = cur.lastrowid

    mode = "writable" if writable else "read_only"
    warnings: list[str] = []
    positions = state.get("positions") or {}
    trades = state.get("trade_history") or state.get("trades") or []
    pos_done = pos_skip = 0
    tr_done = tr_skip = 0
    now_iso = _iso_from_epoch(started) or ""

    items = (
        positions.items()
        if isinstance(positions, dict)
        else [(str(p.get("symbol")), p) for p in positions if isinstance(p, dict)]
    )
    for sym, pos in items:
        if not isinstance(pos, dict):
            warnings.append(f"position {sym} unexpected shape: {type(pos).__name__}")
            pos_skip += 1
            continue
        opened_at = _iso_from_epoch(pos.get("open_time")) or _iso_from_epoch(
            pos.get("opened_at")
        )
        try:
            cur.execute(
                "INSERT INTO positions(symbol, side, quantity, entry_price, "
                "current_price, unrealized_pnl, realized_pnl, leverage, "
                "stop_loss, take_profit, trailing_stop_price, opened_at, "
                "mode, raw_json, imported_at, source) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(symbol, side, opened_at) DO UPDATE SET "
                "quantity=excluded.quantity, "
                "current_price=excluded.current_price, "
                "unrealized_pnl=excluded.unrealized_pnl, "
                "realized_pnl=excluded.realized_pnl, "
                "stop_loss=excluded.stop_loss, "
                "take_profit=excluded.take_profit, "
                "trailing_stop_price=excluded.trailing_stop_price, "
                "raw_json=excluded.raw_json, "
                "imported_at=excluded.imported_at",
                (
                    str(pos.get("symbol") or sym),
                    str(pos.get("side") or "LONG").upper(),
                    pos.get("quantity"),
                    pos.get("entry_price"),
                    pos.get("current_price"),
                    pos.get("unrealized_pnl"),
                    pos.get("realized_pnl"),
                    pos.get("leverage"),
                    pos.get("stop_loss"),
                    pos.get("take_profit"),
                    pos.get("trailing_stop_price"),
                    opened_at,
                    mode,
                    json.dumps(pos, default=str),
                    now_iso,
                    source,
                ),
            )
            pos_done += 1
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"position {sym}: {exc}")
            pos_skip += 1

    if not isinstance(trades, list):
        warnings.append(f"trade_history unexpected shape: {type(trades).__name__}")
        trades = []
    for trade in trades:
        if not isinstance(trade, dict):
            tr_skip += 1
            continue
        try:
            tid = str(
                trade.get("trade_id")
                or trade.get("id")
                or f"{trade.get('symbol')}-{trade.get('opened_at') or trade.get('open_time')}"
            )
            cur.execute(
                "INSERT INTO trades(trade_id, symbol, side, quantity, "
                "entry_price, exit_price, realized_pnl, opened_at, closed_at, "
                "mode, raw_json, imported_at, source) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(trade_id, symbol) DO UPDATE SET "
                "raw_json=excluded.raw_json, imported_at=excluded.imported_at",
                (
                    tid,
                    str(trade.get("symbol") or "?"),
                    str(trade.get("side") or "LONG").upper(),
                    trade.get("quantity"),
                    trade.get("entry_price"),
                    trade.get("exit_price"),
                    trade.get("realized_pnl"),
                    _iso_from_epoch(trade.get("opened_at") or trade.get("open_time")),
                    _iso_from_epoch(trade.get("closed_at") or trade.get("close_time")),
                    mode,
                    json.dumps(trade, default=str),
                    now_iso,
                    source,
                ),
            )
            tr_done += 1
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"trade {trade.get('symbol')}: {exc}")
            tr_skip += 1

    finished = time.time()
    summary = MigrationSummary(
        source=source,
        target=str(db_path),
        started_at=_iso_from_epoch(started) or "",
        finished_at=_iso_from_epoch(finished) or "",
        positions_imported=pos_done,
        positions_skipped=pos_skip,
        trades_imported=tr_done,
        trades_skipped=tr_skip,
        daily_pnl=state.get("daily_pnl"),
        paper_balance=state.get("paper_balance"),
        bot_start_time=_iso_from_epoch(state.get("bot_start_time")),
        mode=mode,
        warnings=warnings,
    )
    cur.execute(
        "UPDATE migrations SET finished_at=?, summary_json=? WHERE id=?",
        (summary.finished_at, json.dumps(asdict(summary), default=str), migration_id),
    )
    conn.commit()
    conn.close()
    return summary


def default_target() -> Path:
    return Path.home() / "Library/Application Support/showMe/data/portfolio.db"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="showme.migration")
    parser.add_argument(
        "--engine",
        type=Path,
        default=Path(os.environ.get("SHOWME_ENGINE_PATH", default_target().parents[1])),
        help="Path containing runtime/state.json.",
    )
    parser.add_argument(
        "--to",
        type=Path,
        default=default_target(),
        help="Target SQLite path (default: portfolio.db under app data).",
    )
    parser.add_argument(
        "--writable",
        action="store_true",
        help="Mark imported rows as mode=writable (default read_only mirror).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level="INFO",
        format="[showme.migration] %(levelname)s %(message)s",
    )
    state_json = args.engine / "runtime" / "state.json"
    if not state_json.exists():
        LOG.error("state.json not found at %s", state_json)
        return 2
    LOG.info("loading %s", state_json)
    state = load_state(state_json)
    summary = import_state(state, args.to, source="showme_import", writable=args.writable)
    LOG.info("→ %d positions, %d trades imported (%d skipped)",
             summary.positions_imported,
             summary.trades_imported,
             summary.positions_skipped + summary.trades_skipped)
    print(json.dumps(asdict(summary), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
