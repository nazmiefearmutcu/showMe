"""Immutable content-addressed releases and independent fetch state in SQLite."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import InputError, utcnow


def data_directory() -> Path:
    override = os.environ.get("SHOWME_VCAP_DIR")
    if override:
        return Path(override)
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "ShowMe" / "vcap"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "showme" / "vcap"


class SnapshotStore:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or data_directory()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "snapshots.sqlite3"
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    snapshot_id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
                    published_at TEXT, retrieved_at TEXT NOT NULL, origin TEXT NOT NULL,
                    dataset TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS source_release ON snapshots(source_id, published_at, retrieved_at);
                CREATE TABLE IF NOT EXISTS fetch_state (
                    source_id TEXT PRIMARY KEY, last_attempt TEXT NOT NULL,
                    last_success TEXT, error TEXT
                );
            """)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["dataset"] = json.loads(data["dataset"])
        return data

    def save(self, dataset: dict[str, Any], origin: str = "imported", retrieved_at: str | None = None) -> dict[str, Any]:
        # retrieval time belongs to the release, not its content. Repeated identical
        # downloads/imports share one immutable release without changing its timestamp.
        canonical = json.dumps(dataset, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        sid = hashlib.sha256((origin + "\n" + canonical).encode("utf-8")).hexdigest()
        with self._connect() as conn:
            conn.execute("INSERT OR IGNORE INTO snapshots VALUES(?,?,?,?,?,?)",
                         (sid, dataset["source_id"], dataset.get("published_at"), retrieved_at or utcnow(), origin, canonical))
            row = conn.execute("SELECT * FROM snapshots WHERE snapshot_id=?", (sid,)).fetchone()
        return self._decode(row)

    def all_latest(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            ids = [row[0] for row in conn.execute("SELECT DISTINCT source_id FROM snapshots ORDER BY source_id")]
        return self.selected(ids)

    def latest(self, source: str, origin: str | None = None) -> dict[str, Any] | None:
        with self._connect() as conn:
            sql = "SELECT * FROM snapshots WHERE source_id=?"
            args: list[Any] = [source]
            if origin:
                sql += " AND origin=?"
                args.append(origin)
            row = conn.execute(sql + " ORDER BY published_at DESC, retrieved_at DESC, snapshot_id DESC LIMIT 1", args).fetchone()
        return self._decode(row) if row else None

    def selected(self, sources: list[str] | tuple[str, ...], vintage: str | None = None) -> list[dict[str, Any]]:
        pinned = None
        if vintage:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM snapshots WHERE snapshot_id=?", (vintage,)).fetchone()
            if not row:
                raise InputError("vintage snapshot_id was not found")
            pinned = self._decode(row)
            if pinned["source_id"] not in sources:
                raise InputError("vintage belongs to a source outside source_ids")
        selected = []
        for source in sorted(sources):
            release = pinned if pinned and pinned["source_id"] == source else self.latest(source)
            if release:
                selected.append(release)
        return selected

    def versions(self, source: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM snapshots" + (" WHERE source_id=?" if source else "") + " ORDER BY source_id, published_at DESC, retrieved_at DESC, snapshot_id DESC", (source,) if source else ()).fetchall()
        return [{"snapshot_id": row["snapshot_id"], "vintage": row["snapshot_id"],
                 "source_id": row["source_id"], "source_name": (data := json.loads(row["dataset"]))["source_name"],
                 "published_at": row["published_at"], "retrieved_at": row["retrieved_at"],
                 "data_mode": row["origin"], "observation_count": len(data["observations"]),
                 "methodology_version": data["methodology_version"]} for row in rows]

    def fetch_state(self, source: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM fetch_state WHERE source_id=?", (source,)).fetchone()
        return dict(row) if row else {}

    def record_fetch(self, source: str, success: bool, error: str | None = None) -> None:
        now = utcnow()
        with self._connect() as conn:
            previous = conn.execute("SELECT last_success FROM fetch_state WHERE source_id=?", (source,)).fetchone()
            conn.execute("INSERT OR REPLACE INTO fetch_state VALUES(?,?,?,?)",
                         (source, now, now if success else (previous[0] if previous else None), error))
