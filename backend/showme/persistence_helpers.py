"""Shared SQLite + JSON persistence helpers (per ARCH-09 P1/P2).

Centralises three concerns previously copy-pasted across persistence modules:

1. ``open_sqlite(path)`` — opens a SQLite connection in WAL mode with a
   sensible ``busy_timeout``. WAL gives readers a consistent view while a
   writer is committing; ``busy_timeout`` makes concurrent writers retry
   instead of crashing with ``database is locked``.
2. ``atomic_write_json(path, payload)`` — write-via-temp-rename so a crash
   mid-write cannot corrupt the file. Also chmods to ``0o600`` for
   secrets-adjacent state.
3. ``ensure_schema_version(conn, current)`` — creates a small
   ``schema_version`` table on first use and writes the version number so
   future migrations can branch cleanly.

These helpers are intentionally dependency-free (stdlib only) so any
persistence module under ``backend/showme/`` can import them without
pulling in optional packages.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any


_SECURE_MODE = 0o600


def open_sqlite(
    path: str | Path,
    *,
    busy_timeout_ms: int = 5000,
    isolation_level: str | None = "DEFERRED",
    detect_types: int = 0,
) -> sqlite3.Connection:
    """Open ``path`` with WAL journaling and ``busy_timeout``.

    The first call against a database file flips ``journal_mode`` to WAL;
    subsequent calls just verify the pragma. The connection is returned in
    the standard ``sqlite3`` "legacy" autocommit style honored by the
    caller's ``with conn:`` blocks.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(p),
        isolation_level=isolation_level,
        detect_types=detect_types,
        check_same_thread=False,
    )
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_schema_version(
    conn: sqlite3.Connection,
    current: int,
    *,
    table: str = "schema_version",
) -> int:
    """Create ``table`` if missing and stamp ``current`` as the active version.

    Returns the version that was previously stored (``0`` on first init).
    Subsequent callers can compare ``previous < current`` to decide whether
    to apply migrations.
    """
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {table} ("
        " id INTEGER PRIMARY KEY CHECK (id = 1),"
        " version INTEGER NOT NULL,"
        " stamped_at TEXT NOT NULL DEFAULT (datetime('now'))"
        ")"
    )
    row = conn.execute(f"SELECT version FROM {table} WHERE id = 1").fetchone()
    previous = int(row[0]) if row else 0
    conn.execute(
        f"INSERT INTO {table} (id, version) VALUES (1, ?)"
        f" ON CONFLICT(id) DO UPDATE SET version = excluded.version,"
        f" stamped_at = datetime('now')",
        (int(current),),
    )
    conn.commit()
    return previous


def atomic_write_json(
    path: str | Path,
    payload: Mapping[str, Any] | list[Any],
    *,
    secure: bool = False,
    indent: int | None = 2,
) -> Path:
    """Atomically replace ``path`` with the JSON-encoded ``payload``.

    Writes to ``<path>.tmp.<pid>.<seq>`` first, ``fsync``s, then ``os.replace``
    onto the final path so a crash mid-write cannot leave a half-encoded
    file. When ``secure=True`` the resulting file is chmod ``0o600``.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", dir=str(target.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=indent, default=str)
            fh.flush()
            os.fsync(fh.fileno())
        if secure:
            try:
                os.chmod(tmp, _SECURE_MODE)
            except OSError:
                # Best-effort on platforms where chmod is restricted (e.g. Windows).
                pass
        os.replace(tmp, target)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    if secure:
        try:
            os.chmod(target, _SECURE_MODE)
        except OSError:
            pass
    return target


def secure_chmod(path: str | Path) -> None:
    """Best-effort ``chmod 0o600`` so persistence files are user-only."""
    try:
        os.chmod(Path(path), _SECURE_MODE)
    except OSError:
        pass


__all__ = [
    "atomic_write_json",
    "ensure_schema_version",
    "open_sqlite",
    "secure_chmod",
]
