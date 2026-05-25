"""DuckDB connection pool for the showMe analytical core.

Single in-process DuckDB connection; DuckDB does not tolerate multiple
processes writing to the same database file simultaneously, so we coordinate
all callers through one pool object guarded by ``threading.Lock``. The pool
lazily creates the database file under ``app_paths``' state directory and
applies the ``IF NOT EXISTS`` schema bootstrap on first use.

Public API
==========

>>> from showme.analytical.duck import connection, close
>>> con = connection()
>>> con.execute("SELECT 1").fetchone()
(1,)
>>> close()

The schema bootstrap covers the four logical buckets used by the analytical
core: ``cache`` (provider response cache), ``snapshot`` (research artifacts),
``audit`` (state-change log), and ``research`` (reserved for future work).
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

import duckdb

try:  # pragma: no cover - import resolution shim
    from showme import app_paths as _app_paths
except ImportError:  # pragma: no cover - dev/test paths without package install
    _app_paths = None


_SCHEMA_BOOTSTRAP = """
CREATE SCHEMA IF NOT EXISTS cache;
CREATE SCHEMA IF NOT EXISTS snapshot;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS research;

CREATE TABLE IF NOT EXISTS cache.provider_responses (
    provider TEXT NOT NULL,
    op TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    payload BLOB NOT NULL,
    mode TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    expires_at TIMESTAMP,
    latency_ms INTEGER,
    PRIMARY KEY (provider, op, input_hash)
);

CREATE TABLE IF NOT EXISTS snapshot.pane_outputs (
    snapshot_id TEXT PRIMARY KEY,
    function_code TEXT NOT NULL,
    inputs_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    label TEXT
);

CREATE TABLE IF NOT EXISTS audit.events (
    event_id TEXT PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    actor TEXT NOT NULL,
    kind TEXT NOT NULL,
    target TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
"""


def _data_dir() -> Path:
    """Resolve the directory the analytical DuckDB file lives in.

    Prefers ``showme.app_paths.state_path`` so dev/tests/packaged builds all
    agree on the same location, but tolerates a missing ``app_paths`` import
    (e.g. in stripped-down test contexts) by falling back to the macOS
    Application Support default.
    """
    if _app_paths is not None and hasattr(_app_paths, "state_path"):
        # state_path returns a *file* path with the parent ensured; we want
        # the parent directory itself.
        return _app_paths.state_path("analytical.duckdb").parent
    fallback = Path.home() / "Library" / "Application Support" / "showMe" / "state"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


class DuckPool:
    """Process-wide DuckDB connection holder.

    The pool guards a single ``duckdb.DuckDBPyConnection``. Callers must
    not close the returned connection themselves; use :meth:`close` to
    tear it down on shutdown.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._conn: Optional[duckdb.DuckDBPyConnection] = None
        self._db_path: Optional[Path] = None

    @property
    def db_path(self) -> Path:
        """The on-disk path to the DuckDB file."""
        if self._db_path is None:
            self._db_path = _data_dir() / "analytical.duckdb"
        return self._db_path

    def connection(self) -> duckdb.DuckDBPyConnection:
        """Return the singleton DuckDB connection, creating it if needed."""
        with self._lock:
            if self._conn is None:
                path = self.db_path
                path.parent.mkdir(parents=True, exist_ok=True)
                self._conn = duckdb.connect(str(path))
                self._conn.execute(_SCHEMA_BOOTSTRAP)
            return self._conn

    def close(self) -> None:
        """Close and clear the underlying connection."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                finally:
                    self._conn = None
                    # Allow a future call to ``connection()`` to re-resolve
                    # the path; helps tests that monkeypatch ``app_paths``
                    # after the pool was first imported.
                    self._db_path = None


POOL = DuckPool()


def connection() -> duckdb.DuckDBPyConnection:
    """Module-level shortcut for :meth:`DuckPool.connection`."""
    return POOL.connection()


def close() -> None:
    """Module-level shortcut for :meth:`DuckPool.close`."""
    POOL.close()


__all__ = ["DuckPool", "POOL", "connection", "close"]
