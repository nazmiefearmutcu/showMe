"""Exchange catalog: dataclass + YAML loader + search/filter helpers.

The catalog is loaded once at sidecar startup. Mutation belongs to the
generator (scripts/build_exchange_catalog.py), not to runtime — this
module is read-only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class CatalogError(RuntimeError):
    """Raised when the YAML is malformed or required fields are missing."""


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    display_name: str
    aliases: tuple[str, ...]
    asset_classes: tuple[str, ...]
    regions: tuple[str, ...]
    adapter: str
    requires: tuple[str, ...]
    optional: tuple[str, ...]
    capabilities: dict[str, bool]
    ccxt_id: str | None = None
    notes: str = ""

    def matches_query(self, q: str) -> bool:
        q = q.strip().lower()
        if not q:
            return True
        if q in self.id.lower() or q in self.display_name.lower():
            return True
        return any(q in a.lower() for a in self.aliases)


@dataclass(frozen=True)
class Catalog:
    entries: tuple[CatalogEntry, ...] = field(default_factory=tuple)

    def by_id(self, exchange_id: str) -> CatalogEntry:
        for e in self.entries:
            if e.id == exchange_id:
                return e
        raise KeyError(f"unknown exchange: {exchange_id}")

    def search(self, q: str) -> list[CatalogEntry]:
        return [e for e in self.entries if e.matches_query(q)]

    def filter(
        self,
        *,
        asset_classes: tuple[str, ...] | None = None,
        regions: tuple[str, ...] | None = None,
        adapter: str | None = None,
    ) -> list[CatalogEntry]:
        out: list[CatalogEntry] = []
        for e in self.entries:
            if asset_classes and not set(asset_classes) & set(e.asset_classes):
                continue
            if regions and not set(regions) & set(e.regions):
                continue
            if adapter and e.adapter != adapter:
                continue
            out.append(e)
        return out

    def to_payload(self) -> list[dict[str, Any]]:
        """JSON-serialisable form for the /api/exchange/catalog route."""
        return [
            {
                "id": e.id,
                "display_name": e.display_name,
                "aliases": list(e.aliases),
                "asset_classes": list(e.asset_classes),
                "regions": list(e.regions),
                "adapter": e.adapter,
                "requires": list(e.requires),
                "optional": list(e.optional),
                "capabilities": dict(e.capabilities),
                "ccxt_id": e.ccxt_id,
                "notes": e.notes,
            }
            for e in self.entries
        ]


_REQUIRED_KEYS = {"id", "display_name", "adapter"}


def _coerce_entry(raw: dict[str, Any]) -> CatalogEntry:
    missing = _REQUIRED_KEYS - raw.keys()
    if missing:
        raise CatalogError(f"entry missing required keys: {sorted(missing)}: {raw!r}")
    return CatalogEntry(
        id=str(raw["id"]),
        display_name=str(raw["display_name"]),
        aliases=tuple(raw.get("aliases") or []),
        asset_classes=tuple(raw.get("asset_classes") or ["spot"]),
        regions=tuple(raw.get("regions") or ["global"]),
        adapter=str(raw["adapter"]),
        requires=tuple(raw.get("requires") or []),
        optional=tuple(raw.get("optional") or []),
        capabilities={k: bool(v) for k, v in (raw.get("capabilities") or {}).items()},
        ccxt_id=str(raw["ccxt_id"]) if raw.get("ccxt_id") else None,
        notes=str(raw.get("notes") or ""),
    )


def load_catalog(path: str | Path) -> Catalog:
    p = Path(path)
    if not p.exists():
        raise CatalogError(f"catalog not found: {p}")
    try:
        raw_list = yaml.safe_load(p.read_text()) or []
    except yaml.YAMLError as exc:
        raise CatalogError(f"catalog YAML parse error: {exc}") from exc
    if not isinstance(raw_list, list):
        raise CatalogError(f"catalog must be a YAML list of entries, got {type(raw_list).__name__}")
    return Catalog(entries=tuple(_coerce_entry(r) for r in raw_list))
