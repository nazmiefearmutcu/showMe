"""Snapshot store for pane outputs (research artifact persistence).

A snapshot is a frozen view of a pane's inputs + payload at a moment in
time. We keep ``inputs`` and ``payload`` as JSON strings so the table
stays portable (no Python-specific blobs needed for snapshots) and queries
in the DuckDB shell stay readable.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .duck import connection


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def save_snapshot(
    function_code: str,
    inputs: dict[str, Any],
    payload: dict[str, Any],
    label: Optional[str] = None,
) -> str:
    """Persist a snapshot row and return its assigned ``snapshot_id``."""
    snapshot_id = uuid.uuid4().hex
    con = connection()
    con.execute(
        "INSERT INTO snapshot.pane_outputs "
        "(snapshot_id, function_code, inputs_json, payload_json, created_at, label) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            snapshot_id,
            function_code,
            json.dumps(inputs, sort_keys=True, default=str),
            json.dumps(payload, sort_keys=True, default=str),
            _utcnow(),
            label,
        ],
    )
    return snapshot_id


def get_snapshot(snapshot_id: str) -> Optional[dict[str, Any]]:
    """Fetch a single snapshot by id, with JSON columns already parsed."""
    con = connection()
    row = con.execute(
        "SELECT snapshot_id, function_code, inputs_json, payload_json, created_at, label "
        "FROM snapshot.pane_outputs WHERE snapshot_id = ?",
        [snapshot_id],
    ).fetchone()
    if row is None:
        return None
    return {
        "snapshot_id": row[0],
        "function_code": row[1],
        "inputs": json.loads(row[2]),
        "payload": json.loads(row[3]),
        "created_at": row[4].isoformat() if row[4] is not None else None,
        "label": row[5],
    }


def list_snapshots(
    function_code: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return up to ``limit`` most-recent snapshots, optionally filtered.

    ``inputs`` / ``payload`` are returned as parsed dicts so the caller can
    use them directly without re-decoding.
    """
    con = connection()
    if function_code is None:
        rows = con.execute(
            "SELECT snapshot_id, function_code, inputs_json, payload_json, created_at, label "
            "FROM snapshot.pane_outputs "
            "ORDER BY created_at DESC LIMIT ?",
            [int(limit)],
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT snapshot_id, function_code, inputs_json, payload_json, created_at, label "
            "FROM snapshot.pane_outputs "
            "WHERE function_code = ? "
            "ORDER BY created_at DESC LIMIT ?",
            [function_code, int(limit)],
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "snapshot_id": row[0],
                "function_code": row[1],
                "inputs": json.loads(row[2]),
                "payload": json.loads(row[3]),
                "created_at": row[4].isoformat() if row[4] is not None else None,
                "label": row[5],
            }
        )
    return out


__all__ = ["save_snapshot", "get_snapshot", "list_snapshots"]
