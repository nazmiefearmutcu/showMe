"""Audit-event log for state-changing operations.

Every row is one user-attributable mutation: who (``actor``), what kind
(``kind``), against which thing (``target``), and the payload of the
change. The payload is stored as a JSON string so it stays grep-friendly
in the DuckDB shell.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .duck import connection


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def record_event(
    actor: str,
    kind: str,
    target: str,
    payload: dict[str, Any],
) -> str:
    """Persist an audit row and return its assigned ``event_id``."""
    event_id = uuid.uuid4().hex
    con = connection()
    con.execute(
        "INSERT INTO audit.events "
        "(event_id, timestamp, actor, kind, target, payload_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            event_id,
            _utcnow(),
            actor,
            kind,
            target,
            json.dumps(payload, sort_keys=True, default=str),
        ],
    )
    return event_id


def list_events(
    kind: Optional[str] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return up to ``limit`` most-recent audit rows, optionally filtered by kind."""
    con = connection()
    if kind is None:
        rows = con.execute(
            "SELECT event_id, timestamp, actor, kind, target, payload_json "
            "FROM audit.events "
            "ORDER BY timestamp DESC LIMIT ?",
            [int(limit)],
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT event_id, timestamp, actor, kind, target, payload_json "
            "FROM audit.events "
            "WHERE kind = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            [kind, int(limit)],
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "event_id": row[0],
                "timestamp": row[1].isoformat() if row[1] is not None else None,
                "actor": row[2],
                "kind": row[3],
                "target": row[4],
                "payload": json.loads(row[5]),
            }
        )
    return out


__all__ = ["record_event", "list_events"]
