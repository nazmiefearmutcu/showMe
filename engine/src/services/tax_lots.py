"""Tax lot ledger + FIFO / LIFO / HIFO / specific-id selection.

Lot = (symbol, qty, price, opened_at, lot_id).
Sale ile lot'lar tüketilir; gerçekleşen kazanç/zarar kaydedilir.

State: ``runtime/tax_lots.sqlite``.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


_DB = Path("runtime/tax_lots.sqlite")
_LT_THRESHOLD_DAYS = 365


def _db() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_DB))
    con.execute("""
        CREATE TABLE IF NOT EXISTS lots (
            lot_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            quantity REAL NOT NULL,
            price REAL NOT NULL,
            opened_at INTEGER NOT NULL,
            account TEXT DEFAULT 'main',
            closed_qty REAL DEFAULT 0
        )""")
    con.execute("""
        CREATE TABLE IF NOT EXISTS realized (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            sold_lot TEXT NOT NULL,
            qty REAL NOT NULL,
            sale_price REAL NOT NULL,
            cost_basis REAL NOT NULL,
            realized_pnl REAL NOT NULL,
            holding_days INTEGER NOT NULL,
            term TEXT NOT NULL  -- 'long' or 'short'
        )""")
    con.commit()
    return con


def open_lot(*, symbol: str, quantity: float, price: float,
             opened_at: datetime | None = None,
             account: str = "main") -> str:
    lot_id = uuid.uuid4().hex[:12]
    con = _db()
    con.execute(
        "INSERT INTO lots(lot_id, symbol, quantity, price, opened_at, account, closed_qty) VALUES (?,?,?,?,?,?,0)",
        [lot_id, symbol.upper(), float(quantity), float(price),
         int((opened_at or datetime.utcnow()).timestamp()), account],
    )
    con.commit(); con.close()
    return lot_id


def list_open_lots(*, symbol: str | None = None,
                   account: str | None = None) -> list[dict[str, Any]]:
    con = _db()
    sql = ("SELECT lot_id, symbol, quantity, price, opened_at, account, closed_qty "
           "FROM lots WHERE quantity > closed_qty")
    params: list[Any] = []
    if symbol:
        sql += " AND symbol = ?"; params.append(symbol.upper())
    if account:
        sql += " AND account = ?"; params.append(account)
    sql += " ORDER BY opened_at"
    rows = con.execute(sql, params).fetchall()
    con.close()
    return [{"lot_id": r[0], "symbol": r[1], "quantity": r[2],
             "price": r[3], "opened_at": r[4], "account": r[5],
             "closed_qty": r[6], "remaining": r[2] - r[6]}
            for r in rows]


def _sort_lots(lots: list[dict[str, Any]], method: str) -> list[dict[str, Any]]:
    method = method.upper()
    if method == "FIFO":
        return sorted(lots, key=lambda l: l["opened_at"])
    if method == "LIFO":
        return sorted(lots, key=lambda l: -l["opened_at"])
    if method == "HIFO":
        return sorted(lots, key=lambda l: -l["price"])
    if method == "LOFO":
        return sorted(lots, key=lambda l: l["price"])
    return lots


def sell(*, symbol: str, quantity: float, price: float,
         method: str = "FIFO", account: str | None = None,
         specific_lot_ids: Iterable[str] | None = None) -> dict[str, Any]:
    """Consume open lots. Returns realized P&L breakdown.

    method ∈ {FIFO, LIFO, HIFO, LOFO, SPECIFIC}
    specific_lot_ids only used when method == "SPECIFIC".
    """
    con = _db()
    sym = symbol.upper()
    rows = con.execute(
        "SELECT lot_id, quantity, price, opened_at, closed_qty FROM lots "
        "WHERE symbol = ? AND quantity > closed_qty"
        + (" AND account = ?" if account else ""),
        [sym] + ([account] if account else []),
    ).fetchall()
    open_lots = [{"lot_id": r[0], "quantity": r[1], "price": r[2],
                   "opened_at": r[3], "closed_qty": r[4]} for r in rows]
    if method.upper() == "SPECIFIC":
        keep = set(specific_lot_ids or [])
        ordered = [l for l in open_lots if l["lot_id"] in keep]
    else:
        ordered = _sort_lots(open_lots, method)
    remaining_to_sell = float(quantity)
    consumed = []
    realized_pnl = 0.0
    cost_basis_total = 0.0
    sale_proceeds = 0.0
    now_ts = int(time.time())
    for lot in ordered:
        if remaining_to_sell <= 0:
            break
        avail = lot["quantity"] - lot["closed_qty"]
        if avail <= 0:
            continue
        take = min(avail, remaining_to_sell)
        cost = lot["price"] * take
        proceed = price * take
        pnl = proceed - cost
        days = max(0, (now_ts - lot["opened_at"]) // 86400)
        term = "long" if days >= _LT_THRESHOLD_DAYS else "short"
        # Update lot closed_qty
        con.execute("UPDATE lots SET closed_qty = closed_qty + ? WHERE lot_id = ?",
                    [take, lot["lot_id"]])
        con.execute(
            "INSERT INTO realized(ts, symbol, sold_lot, qty, sale_price, cost_basis, realized_pnl, holding_days, term) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [now_ts, sym, lot["lot_id"], take, price, cost, pnl, int(days), term],
        )
        consumed.append({
            "lot_id": lot["lot_id"], "qty": take,
            "lot_price": lot["price"], "cost_basis": cost,
            "proceeds": proceed, "pnl": pnl,
            "holding_days": int(days), "term": term,
        })
        cost_basis_total += cost
        sale_proceeds += proceed
        realized_pnl += pnl
        remaining_to_sell -= take
    con.commit(); con.close()
    return {
        "method": method,
        "symbol": sym,
        "qty_requested": quantity,
        "qty_filled": float(quantity) - remaining_to_sell,
        "qty_short": remaining_to_sell,
        "consumed_lots": consumed,
        "cost_basis_total": cost_basis_total,
        "sale_proceeds": sale_proceeds,
        "realized_pnl_total": realized_pnl,
    }


def realized_summary(*, year: int | None = None) -> dict[str, Any]:
    con = _db()
    sql = ("SELECT term, SUM(realized_pnl), SUM(qty), COUNT(*) "
           "FROM realized WHERE 1=1")
    params: list[Any] = []
    if year:
        start = datetime(year, 1, 1).timestamp()
        end = datetime(year + 1, 1, 1).timestamp()
        sql += " AND ts >= ? AND ts < ?"; params += [int(start), int(end)]
    sql += " GROUP BY term"
    rows = con.execute(sql, params).fetchall()
    con.close()
    out: dict[str, Any] = {"long": {"pnl": 0, "qty": 0, "n": 0},
                            "short": {"pnl": 0, "qty": 0, "n": 0}}
    for term, pnl, qty, n in rows:
        out[term] = {"pnl": float(pnl or 0), "qty": float(qty or 0), "n": int(n or 0)}
    out["total_pnl"] = out["long"]["pnl"] + out["short"]["pnl"]
    return out
