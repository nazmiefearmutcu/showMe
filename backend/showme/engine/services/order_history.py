"""Persistent order history (cross-broker SQLite log).

Plan §18.2 AIM derinleştirme. Her placeOrder çağrısı buraya append'lenir;
EMSXFunction +1 satır eklemekle entegrasyon tamamlanır.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import Any

from showme.app_paths import runtime_path

LOG = logging.getLogger("showme.engine.services.order_history")


def _db_file():
    return runtime_path("orders.sqlite")


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(str(_db_file()))
    con.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            broker TEXT, order_id TEXT,
            symbol TEXT, asset_class TEXT, side TEXT,
            quantity REAL, price REAL, leverage INTEGER,
            type TEXT, tif TEXT, status TEXT,
            metadata TEXT
        )""")
    con.commit()
    return con


def record_order(*, broker: str, order_id: str, symbol: str,
                 side: str, quantity: float, asset_class: str = "",
                 price: float | None = None, leverage: int | None = None,
                 type: str = "MARKET", tif: str = "GTC",
                 status: str = "submitted",
                 metadata: dict[str, Any] | None = None) -> int:
    con = _db()
    cur = con.execute(
        "INSERT INTO orders(ts, broker, order_id, symbol, asset_class, side, quantity, price, leverage, type, tif, status, metadata)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [int(time.time()), broker, order_id, symbol, asset_class, side,
         float(quantity), price, leverage, type, tif, status,
         json.dumps(metadata or {})],
    )
    con.commit()
    rid = cur.lastrowid
    con.close()
    return rid


def list_orders(*, broker: str | None = None,
                symbol: str | None = None,
                limit: int = 200) -> list[dict[str, Any]]:
    con = _db()
    sql = "SELECT id, ts, broker, order_id, symbol, asset_class, side, quantity, price, leverage, type, tif, status, metadata FROM orders WHERE 1=1"
    params: list[Any] = []
    if broker:
        sql += " AND broker = ?"; params.append(broker)
    if symbol:
        sql += " AND symbol = ?"; params.append(symbol.upper())
    sql += " ORDER BY ts DESC LIMIT ?"
    params.append(limit)
    rows = con.execute(sql, params).fetchall()
    cols = ["id", "ts", "broker", "order_id", "symbol", "asset_class", "side",
            "quantity", "price", "leverage", "type", "tif", "status", "metadata"]
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(zip(cols, r))
        try:
            d["metadata"] = json.loads(d["metadata"] or "{}")
        except Exception as exc:  # noqa: BLE001
            # QA-fix: log corrupt metadata so silent parse failures are
            # visible. Keep the row in the result with the raw text so the
            # UI still gets an audit trail.
            LOG.warning(
                "order_history: metadata json decode failed for order_id=%s: %s",
                d.get("order_id"),
                exc,
            )
        out.append(d)
    con.close()
    return out


def update_status(order_id: str, status: str) -> bool:
    con = _db()
    cur = con.execute("UPDATE orders SET status = ? WHERE order_id = ?",
                       [status, order_id])
    con.commit()
    n = cur.rowcount
    con.close()
    return n > 0
