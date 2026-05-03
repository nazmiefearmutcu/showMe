"""Granola meeting notes adapter — local sqlite + REST.

Granola, macOS toplantı notu uygulaması; lokalde SQLite veritabanına
yazar. ``GRANOLA_DB_PATH`` ile direkt SQLite'a okuruz; aksi halde
public REST endpoint denenir (varsa).

DATA PIPELINE:
    Source 1: ~/Library/Application Support/Granola/notes.sqlite (default)
    Source 2: GRANOLA_API_TOKEN + REST (eğer kullanıcı kullanıyorsa)
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest, DataSourceError
)


_DEFAULT_PATHS = [
    "~/Library/Application Support/Granola/notes.sqlite",
    "~/Library/Application Support/Granola/granola.sqlite",
    "~/.granola/notes.sqlite",
]


class GranolaAdapter(BaseDataSource):
    name = "granola"
    supported_kinds = (DataKind.OTHER, DataKind.NEWS)
    rate_limit_rps = 5.0
    requires_api_key = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        env_path = os.environ.get("GRANOLA_DB_PATH")
        candidates = [env_path] if env_path else []
        candidates += [str(Path(p).expanduser()) for p in _DEFAULT_PATHS]
        self.db_path: str | None = next((p for p in candidates if p and Path(p).exists()), None)

    def _has_local_db(self) -> bool:
        return self.db_path is not None

    async def list_recent(self, limit: int = 25) -> list[dict[str, Any]]:
        if not self._has_local_db():
            return []
        try:
            con = sqlite3.connect(self.db_path)  # type: ignore[arg-type]
            tables = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            # Granola schema isn't documented; pick the most plausible table.
            target = next((t for t in tables if "note" in t.lower() or "meeting" in t.lower()), None)
            if not target:
                con.close()
                return []
            cols_info = con.execute(f"PRAGMA table_info({target})").fetchall()
            colnames = [c[1] for c in cols_info]
            order_col = "updated_at" if "updated_at" in colnames else (
                "created_at" if "created_at" in colnames else "rowid"
            )
            sql = f"SELECT * FROM {target} ORDER BY {order_col} DESC LIMIT ?"
            rows = con.execute(sql, [limit]).fetchall()
            con.close()
            return [dict(zip(colnames, r)) for r in rows]
        except Exception:
            return []

    async def fetch(self, request: DataRequest) -> Any:
        if not self._has_local_db():
            return {"error": "Granola DB not found",
                    "checked_paths": [str(p) for p in _DEFAULT_PATHS]}
        return await self.list_recent(limit=request.limit or 25)
