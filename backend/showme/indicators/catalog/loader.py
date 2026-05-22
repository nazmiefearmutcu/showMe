"""Indicator catalog: dataclass + YAML loader.

Sub-system F. Metadata-only — computation lands in E.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class IndicatorCatalogError(RuntimeError):
    """Raised when the YAML is malformed or required fields are missing."""


@dataclass(frozen=True)
class IndicatorParam:
    name: str
    type: str
    default: Any
    min: float | None = None
    max: float | None = None
    effect: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "type": self.type, "default": self.default,
            "min": self.min, "max": self.max, "effect": self.effect,
        }


@dataclass(frozen=True)
class IndicatorEntry:
    id: str
    display_name: str
    family: str
    short_description: str
    long_description: str
    formula: str
    parameters: tuple[IndicatorParam, ...]
    confidence: int
    confidence_rationale: str
    suggested_strategy: dict[str, Any]
    references: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "family": self.family,
            "short_description": self.short_description,
            "long_description": self.long_description,
            "formula": self.formula,
            "parameters": [p.to_dict() for p in self.parameters],
            "confidence": self.confidence,
            "confidence_rationale": self.confidence_rationale,
            "suggested_strategy": dict(self.suggested_strategy),
            "references": list(self.references),
        }

    def matches_query(self, q: str) -> bool:
        q = q.strip().lower()
        if not q:
            return True
        return (q in self.id.lower()
                or q in self.display_name.lower()
                or q in self.family.lower())


@dataclass(frozen=True)
class IndicatorCatalog:
    entries: tuple[IndicatorEntry, ...] = field(default_factory=tuple)

    def by_id(self, indicator_id: str) -> IndicatorEntry:
        for e in self.entries:
            if e.id == indicator_id:
                return e
        raise KeyError(f"unknown indicator: {indicator_id}")

    def search(self, q: str) -> list[IndicatorEntry]:
        return [e for e in self.entries if e.matches_query(q)]

    def filter(self, *, family: str | None = None) -> list[IndicatorEntry]:
        if family is None:
            return list(self.entries)
        return [e for e in self.entries if e.family == family]

    def to_payload(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.entries]


_REQUIRED_KEYS = {"id", "display_name", "family", "confidence"}


def _coerce_param(raw: dict[str, Any]) -> IndicatorParam:
    if "name" not in raw:
        raise IndicatorCatalogError(f"parameter missing 'name': {raw!r}")
    return IndicatorParam(
        name=str(raw["name"]),
        type=str(raw.get("type") or "float"),
        default=raw.get("default"),
        min=float(raw["min"]) if raw.get("min") is not None else None,
        max=float(raw["max"]) if raw.get("max") is not None else None,
        effect=str(raw.get("effect") or ""),
    )


def _coerce_entry(raw: dict[str, Any]) -> IndicatorEntry:
    missing = _REQUIRED_KEYS - raw.keys()
    if missing:
        raise IndicatorCatalogError(f"entry missing required keys: {sorted(missing)}: id={raw.get('id')}")
    confidence = int(raw["confidence"])
    if not (1 <= confidence <= 10):
        raise IndicatorCatalogError(f"confidence out of range 1-10: {confidence} (id={raw.get('id')})")
    params = tuple(_coerce_param(p) for p in (raw.get("parameters") or []))
    return IndicatorEntry(
        id=str(raw["id"]),
        display_name=str(raw["display_name"]),
        family=str(raw["family"]),
        short_description=str(raw.get("short_description") or ""),
        long_description=str(raw.get("long_description") or ""),
        formula=str(raw.get("formula") or ""),
        parameters=params,
        confidence=confidence,
        confidence_rationale=str(raw.get("confidence_rationale") or ""),
        suggested_strategy=dict(raw.get("suggested_strategy") or {}),
        references=tuple(raw.get("references") or []),
    )


def load_indicator_catalog(path: str | Path) -> IndicatorCatalog:
    p = Path(path)
    if not p.exists():
        raise IndicatorCatalogError(f"indicator catalog not found: {p}")
    try:
        raw_list = yaml.safe_load(p.read_text()) or []
    except yaml.YAMLError as exc:
        raise IndicatorCatalogError(f"YAML parse error: {exc}") from exc
    if not isinstance(raw_list, list):
        raise IndicatorCatalogError("catalog must be a YAML list")
    return IndicatorCatalog(entries=tuple(_coerce_entry(r) for r in raw_list))
