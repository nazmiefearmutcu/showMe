"""Filesystem CRUD for strategy specs.

Storage layout: $SHOWME_HOME/strategies/{id}.json. Index re-built from disk
on every `list()` — small directory, no separate index file needed.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .spec import StrategySpec

LOG = logging.getLogger("showme.strategies.store")


class UnknownStrategy(KeyError):
    """Raised when an id is not in the store."""


@dataclass(frozen=True)
class StrategyMeta:
    id: str
    name: str
    description: str
    timeframe: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "timeframe": self.timeframe,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }


class StrategyStore:
    def __init__(self, dir_path: Path) -> None:
        self._dir = dir_path
        self._dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def fresh(cls) -> "StrategyStore":
        from showme.app_paths import app_home
        return cls(app_home() / "strategies")

    def _path(self, strategy_id: str) -> Path:
        return self._dir / f"{strategy_id}.json"

    def _iter_files(self) -> Iterator[Path]:
        if not self._dir.exists():
            return iter(())
        return self._dir.glob("*.json")

    def list(self) -> list[StrategyMeta]:
        out: list[StrategyMeta] = []
        for f in self._iter_files():
            try:
                d = json.loads(f.read_text())
            except Exception as exc:  # noqa: BLE001
                LOG.warning("skip corrupt %s: %s", f.name, exc)
                continue
            out.append(StrategyMeta(
                id=d.get("id") or f.stem,
                name=d.get("name") or "",
                description=d.get("description") or "",
                timeframe=d.get("timeframe") or "1h",
                created_at=d.get("created_at") or "",
                updated_at=d.get("updated_at") or "",
            ))
        return sorted(out, key=lambda m: m.updated_at, reverse=True)

    def get(self, strategy_id: str) -> StrategySpec:
        p = self._path(strategy_id)
        if not p.exists():
            raise UnknownStrategy(strategy_id)
        return StrategySpec.from_json(p.read_text())

    def save(self, spec: StrategySpec) -> StrategySpec:
        p = self._path(spec.id)
        now = datetime.now(tz=timezone.utc).isoformat()
        if p.exists():
            try:
                existing = StrategySpec.from_json(p.read_text())
                spec = spec.model_copy(update={
                    "created_at": existing.created_at,
                    "updated_at": now,
                })
            except Exception:  # noqa: BLE001
                spec = spec.model_copy(update={"updated_at": now})
        else:
            spec = spec.model_copy(update={"created_at": now, "updated_at": now})
        p.write_text(spec.to_json())
        return spec

    def delete(self, strategy_id: str) -> bool:
        p = self._path(strategy_id)
        if not p.exists():
            return False
        p.unlink()
        return True
