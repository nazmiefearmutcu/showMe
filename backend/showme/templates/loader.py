"""Template strategy catalog loader.

Sub-system G. Mirrors brokers/catalog/loader pattern.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class TemplateCatalogError(RuntimeError):
    """Raised when the YAML is malformed or required fields are missing."""


@dataclass(frozen=True)
class TemplateEntry:
    id: str
    name: str
    description: str
    uses_indicators: tuple[str, ...]
    recommended_timeframe: str
    recommended_symbols: tuple[str, ...]
    applicability: str
    natural_language_explanation: str
    math: str
    spec_template: dict[str, Any]
    family: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "uses_indicators": list(self.uses_indicators),
            "recommended_timeframe": self.recommended_timeframe,
            "recommended_symbols": list(self.recommended_symbols),
            "applicability": self.applicability,
            "natural_language_explanation": self.natural_language_explanation,
            "math": self.math,
            "spec_template": dict(self.spec_template),
            "family": self.family,
        }

    def matches_query(self, q: str) -> bool:
        q = q.strip().lower()
        if not q:
            return True
        return (q in self.id.lower() or q in self.name.lower()
                or any(q in i.lower() for i in self.uses_indicators)
                or q in self.family.lower())


@dataclass(frozen=True)
class TemplateCatalog:
    entries: tuple[TemplateEntry, ...] = field(default_factory=tuple)

    def by_id(self, template_id: str) -> TemplateEntry:
        for e in self.entries:
            if e.id == template_id:
                return e
        raise KeyError(f"unknown template: {template_id}")

    def search(self, q: str) -> list[TemplateEntry]:
        return [e for e in self.entries if e.matches_query(q)]

    def filter(self, *, indicator: str | None = None) -> list[TemplateEntry]:
        if not indicator:
            return list(self.entries)
        return [e for e in self.entries if indicator in e.uses_indicators]

    def to_payload(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.entries]


_REQUIRED_KEYS = {"id", "name", "uses_indicators", "spec_template"}


def _coerce_entry(raw: dict[str, Any]) -> TemplateEntry:
    missing = _REQUIRED_KEYS - raw.keys()
    if missing:
        raise TemplateCatalogError(
            f"entry missing required keys: {sorted(missing)}: id={raw.get('id')}",
        )
    return TemplateEntry(
        id=str(raw["id"]),
        name=str(raw["name"]),
        description=str(raw.get("description") or ""),
        uses_indicators=tuple(raw["uses_indicators"]),
        recommended_timeframe=str(raw.get("recommended_timeframe") or "1h"),
        recommended_symbols=tuple(raw.get("recommended_symbols") or []),
        applicability=str(raw.get("applicability") or ""),
        natural_language_explanation=str(raw.get("natural_language_explanation") or ""),
        math=str(raw.get("math") or ""),
        spec_template=dict(raw["spec_template"]),
        family=str(raw.get("family") or ""),
    )


def load_template_catalog(path: str | Path) -> TemplateCatalog:
    p = Path(path)
    if not p.exists():
        raise TemplateCatalogError(f"template catalog not found: {p}")
    try:
        raw_list = yaml.safe_load(p.read_text()) or []
    except yaml.YAMLError as exc:
        raise TemplateCatalogError(f"YAML parse error: {exc}") from exc
    if not isinstance(raw_list, list):
        raise TemplateCatalogError("catalog must be a YAML list")
    return TemplateCatalog(entries=tuple(_coerce_entry(r) for r in raw_list))
