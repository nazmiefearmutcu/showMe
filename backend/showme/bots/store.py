"""Filesystem CRUD for BotRecord.

Storage: $SHOWME_HOME/bots/{id}.json. Mirrors strategies/store.py.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .record import BotRecord

LOG = logging.getLogger("showme.bots.store")


# Faz 2 / S7 — Path-traversal hardening. We accept only ids that are
# alphanumeric, underscore, or hyphen, capped at 64 chars. uuid4().hex
# (the default factory in BotRecord) is 32 hex chars so this is generous
# while still rejecting "../escape" or "..%2Fetc%2Fpasswd"-style URLs.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _validate_id(bot_id: str) -> str:
    if not isinstance(bot_id, str) or not _ID_RE.fullmatch(bot_id):
        raise ValueError("invalid id")
    return bot_id


class UnknownBot(KeyError):
    """Raised when a bot id is not in the store."""


@dataclass(frozen=True)
class BotMeta:
    id: str
    strategy_id: str
    credential_id: str
    exchange_id: str
    symbol: str
    timeframe: str
    mode: str
    enabled: bool
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "id": self.id, "strategy_id": self.strategy_id,
            "credential_id": self.credential_id, "exchange_id": self.exchange_id,
            "symbol": self.symbol, "timeframe": self.timeframe,
            "mode": self.mode, "enabled": self.enabled,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }


class BotStore:
    def __init__(self, dir_path: Path) -> None:
        self._dir = dir_path
        self._dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def fresh(cls) -> "BotStore":
        from showme.app_paths import app_home
        return cls(app_home() / "bots")

    def _path(self, bot_id: str) -> Path:
        # Faz 2 / S7 — validate before composing the on-disk path.
        _validate_id(bot_id)
        return self._dir / f"{bot_id}.json"

    def _iter_files(self) -> Iterator[Path]:
        if not self._dir.exists():
            return iter(())
        # Skip half-written ``*.json.tmp`` files left by an aborted save.
        return (p for p in self._dir.glob("*.json") if not p.name.endswith(".tmp"))

    def list(self) -> list[BotMeta]:
        out: list[BotMeta] = []
        for f in self._iter_files():
            try:
                raw = f.read_text()
                if not raw.strip():
                    # Faz 2 / S6 — defensive: skip a 0-byte file with a
                    # WARNING instead of silently dropping the record.
                    LOG.warning("skip empty bot file %s (possible crashed write)", f.name)
                    continue
                d = json.loads(raw)
            except Exception as exc:  # noqa: BLE001
                LOG.warning("skip corrupt %s: %s", f.name, exc)
                continue
            out.append(BotMeta(
                id=f.stem,
                strategy_id=d.get("strategy_id") or "",
                credential_id=d.get("credential_id") or "",
                exchange_id=d.get("exchange_id") or "",
                symbol=d.get("symbol") or "",
                timeframe=d.get("timeframe") or "1h",
                mode=d.get("mode") or "shadow",
                enabled=bool(d.get("enabled", False)),
                created_at=d.get("created_at") or "",
                updated_at=d.get("updated_at") or "",
            ))
        return sorted(out, key=lambda m: m.updated_at, reverse=True)

    def get(self, bot_id: str) -> BotRecord:
        p = self._path(bot_id)
        if not p.exists():
            raise UnknownBot(bot_id)
        rec = BotRecord.from_json(p.read_text())
        if rec.id != bot_id:
            rec = rec.model_copy(update={"id": bot_id})
            try:
                self.save(rec)
            except Exception as exc:  # noqa: BLE001
                LOG.warning("auto-heal failed for bot %s: %s", bot_id, exc)
        return rec

    def save(self, rec: BotRecord) -> BotRecord:
        p = self._path(rec.id)
        now = datetime.now(tz=timezone.utc).isoformat()
        if p.exists():
            try:
                existing = BotRecord.from_json(p.read_text())
                rec = rec.model_copy(update={
                    "created_at": existing.created_at,
                    "updated_at": now,
                })
            except Exception:  # noqa: BLE001
                rec = rec.model_copy(update={"updated_at": now})
        else:
            rec = rec.model_copy(update={"created_at": now, "updated_at": now})
        # Faz 2 / S6 — atomic write: tmp file + fsync + os.replace. A
        # mid-write SIGKILL now leaves either the previous version intact
        # OR a *.tmp sibling that ``_iter_files`` skips; never a 0-byte
        # corruption masquerading as a live record.
        tmp = p.with_suffix(p.suffix + ".tmp")
        data = rec.to_json()
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
        return rec

    def delete(self, bot_id: str) -> bool:
        p = self._path(bot_id)
        if not p.exists():
            return False
        p.unlink()
        return True
