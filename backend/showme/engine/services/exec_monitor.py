"""VWAP / TWAP execution monitor.

Tracks slice-by-slice fill quality vs benchmark over the lifetime of a
parent order. Used by the execution algos (algo_engine + algo_backtest)
and exposed via /api/v1/exec.

Metrics:
- twap_target = arrival_price (or user override) — TWAP benchmark.
- vwap_running = Σ(px × vol) / Σ vol — running VWAP across all market trades
  observed since order start. Optional (caller passes ticks).
- slippage_per_slice = signed (vs benchmark) basis points.
- fill_rate = filled_qty / target_qty so far.
- pace = (filled_qty / target_qty) − (elapsed_t / horizon_t).
        positive = ahead of schedule, negative = behind.
- residual = remaining qty / total.
- impact_estimate = avg_fill - decision_price (vs original arrival).

Persistence: ``runtime/exec_monitor.sqlite``.
    Tables: parent_orders, slices.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path("runtime/exec_monitor.sqlite")
_LOCK = threading.RLock()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS parent_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_id TEXT UNIQUE,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            target_qty REAL NOT NULL,
            arrival_price REAL,
            algo TEXT,
            horizon_seconds INTEGER,
            started_at INTEGER,
            ended_at INTEGER,
            status TEXT DEFAULT 'live',
            metadata_json TEXT DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_parent_orders_symbol
            ON parent_orders(symbol);
        CREATE INDEX IF NOT EXISTS idx_parent_orders_status
            ON parent_orders(status);
        CREATE TABLE IF NOT EXISTS slices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_id TEXT NOT NULL,
            slice_idx INTEGER NOT NULL,
            ts INTEGER NOT NULL,
            qty REAL NOT NULL,
            avg_px REAL NOT NULL,
            benchmark_px REAL,
            vwap_running REAL,
            FOREIGN KEY (parent_id) REFERENCES parent_orders(parent_id)
        );
        CREATE INDEX IF NOT EXISTS idx_slices_parent ON slices(parent_id);
        """
    )


def open_parent(
    parent_id: str, *, symbol: str, side: str, target_qty: float,
    arrival_price: float | None = None, algo: str = "TWAP",
    horizon_seconds: int = 600,
    metadata: dict[str, Any] | None = None,
) -> int:
    with _LOCK, _connect() as conn:
        _ensure_schema(conn)
        try:
            cur = conn.execute(
                "INSERT INTO parent_orders(parent_id, symbol, side, target_qty, "
                "arrival_price, algo, horizon_seconds, started_at, metadata_json) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (parent_id, symbol.upper(), side.upper(), float(target_qty),
                 arrival_price, algo, int(horizon_seconds), int(time.time()),
                 json.dumps(metadata or {})),
            )
            conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return -1   # parent_id already exists


def record_slice(
    parent_id: str, *,
    slice_idx: int, qty: float, avg_px: float,
    benchmark_px: float | None = None, vwap_running: float | None = None,
) -> int:
    with _LOCK, _connect() as conn:
        _ensure_schema(conn)
        cur = conn.execute(
            "INSERT INTO slices(parent_id, slice_idx, ts, qty, avg_px, "
            "benchmark_px, vwap_running) VALUES (?,?,?,?,?,?,?)",
            (parent_id, int(slice_idx), int(time.time()),
             float(qty), float(avg_px), benchmark_px, vwap_running),
        )
        conn.commit()
        return cur.lastrowid


def close_parent(parent_id: str, status: str = "complete") -> bool:
    with _LOCK, _connect() as conn:
        _ensure_schema(conn)
        cur = conn.execute(
            "UPDATE parent_orders SET ended_at=?, status=? WHERE parent_id=?",
            (int(time.time()), status, parent_id),
        )
        conn.commit()
        return cur.rowcount > 0


def get_parent(parent_id: str) -> dict[str, Any] | None:
    with _LOCK, _connect() as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT * FROM parent_orders WHERE parent_id=?",
            (parent_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["metadata"] = json.loads(d.pop("metadata_json", "{}") or "{}")
        except Exception:
            d["metadata"] = {}
        _add_time_labels(d)
        slices = [dict(r) for r in conn.execute(
            "SELECT slice_idx, ts, qty, avg_px, benchmark_px, vwap_running "
            "FROM slices WHERE parent_id=? ORDER BY slice_idx",
            (parent_id,)
        ).fetchall()]
        d["slices"] = slices
        d["metrics"] = compute_metrics(d, slices)
        _decorate_execution_status(d)
        return d


def list_parents(*, status: str | None = None, symbol: str | None = None,
                 limit: int = 50) -> list[dict[str, Any]]:
    with _LOCK, _connect() as conn:
        _ensure_schema(conn)
        sql = "SELECT * FROM parent_orders WHERE 1=1"
        params: list[Any] = []
        if status:
            sql += " AND status=?"; params.append(status)
        if symbol:
            sql += " AND symbol=?"; params.append(symbol.upper())
        sql += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["metadata"] = json.loads(d.pop("metadata_json", "{}") or "{}")
        except Exception:
            d["metadata"] = {}
        _add_time_labels(d)
        slices = [dict(rr) for rr in _connect().execute(
            "SELECT slice_idx, ts, qty, avg_px, benchmark_px, vwap_running "
            "FROM slices WHERE parent_id=? ORDER BY slice_idx",
            (d["parent_id"],)).fetchall()]
        d["metrics"] = compute_metrics(d, slices)
        _decorate_execution_status(d)
        out.append(d)
    return out


def compute_metrics(parent: dict[str, Any], slices: list[dict[str, Any]]) -> dict[str, Any]:
    target = float(parent.get("target_qty") or 0)
    arrival = parent.get("arrival_price")
    side = (parent.get("side") or "BUY").upper()
    sign = +1 if side in ("BUY", "LONG") else -1
    started = parent.get("started_at") or 0
    horizon = int(parent.get("horizon_seconds") or 0) or 1
    now = parent.get("ended_at") or int(time.time())
    elapsed = max(0, now - started)
    filled_qty = sum(float(s["qty"]) for s in slices)
    notional = sum(float(s["qty"]) * float(s["avg_px"]) for s in slices)
    avg_fill = (notional / filled_qty) if filled_qty else None
    fill_rate = filled_qty / target if target else 0
    residual_qty = max(target - filled_qty, 0)
    fully_filled = target > 0 and filled_qty >= target and residual_qty <= 1e-9
    pace = 0.0 if fully_filled else fill_rate - (elapsed / horizon)
    is_per_share = (sign * (avg_fill - arrival)) if (avg_fill and arrival) else None
    is_bps = (is_per_share / arrival * 1e4) if (is_per_share is not None and arrival) else None
    stored_status = parent.get("status")
    computed_status = (
        "filled_not_closed"
        if stored_status == "live" and fully_filled and not parent.get("ended_at")
        else stored_status
    )
    # Per-slice slippage vs benchmark.
    per_slice = []
    for s in slices:
        bench = s.get("benchmark_px") or arrival
        slip = sign * (float(s["avg_px"]) - bench) if bench else None
        per_slice.append({
            "slice_idx": s["slice_idx"], "ts": s["ts"],
            "qty": s["qty"], "avg_px": s["avg_px"],
            "benchmark_px": bench, "slippage_per_share": slip,
            "slippage_bps": (slip / bench * 1e4) if (slip is not None and bench) else None,
            "vwap_running": s.get("vwap_running"),
        })
    return {
        "target_qty": target, "filled_qty": filled_qty,
        "residual_qty": residual_qty, "avg_fill": avg_fill,
        "arrival_price": arrival, "is_per_share": is_per_share,
        "is_bps": is_bps, "fill_rate_pct": fill_rate * 100,
        "elapsed_seconds": elapsed, "horizon_seconds": horizon,
        "pace_pct": pace * 100,
        "n_slices": len(slices),
        "per_slice": per_slice,
        "status": computed_status,
        "stored_status": stored_status,
        "next_action": (
            "Close the parent order with action=close after confirming all fills."
            if computed_status == "filled_not_closed"
            else None
        ),
    }


def _iso_ts(value: Any) -> str | None:
    try:
        ts = int(value)
    except Exception:
        return None
    if ts <= 0:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _add_time_labels(row: dict[str, Any]) -> None:
    row["started_at_iso"] = _iso_ts(row.get("started_at"))
    row["ended_at_iso"] = _iso_ts(row.get("ended_at"))


def _decorate_execution_status(row: dict[str, Any]) -> None:
    metrics = row.get("metrics") or {}
    computed = metrics.get("status")
    if computed and computed != row.get("status"):
        row["stored_status"] = row.get("status")
        row["status"] = computed
    if metrics.get("next_action"):
        row["next_action"] = metrics["next_action"]
