"""Queries preserve source boundaries and observation vintages."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from itertools import combinations
import os
from typing import Any

from .catalog import SOURCE_CATALOG, catalogue
from .models import InputError, Query, source_id, validate_dataset
from .providers import Providers
from .store import SnapshotStore

METHODOLOGY = (
    "Source-specific reported observations only. Countries are never summed to a world total; "
    "Turkey and crypto are not added to global totals. No source splicing, interpolation or missing-to-zero conversion. "
    "Investment in companies, number of deals and fund fundraising are distinct. "
    "Independent publishers can be displayed side by side, but percentage gaps require verified matching methodologies. "
    "Publication, retrieval and measurement period dates remain distinct. No derived TTM/annualization is performed. "
    "DefiLlama all_raises means reported crypto financing (incl token sales); it is not strict VC."
)
SIGNATURE = ("scope", "geography", "metric", "frequency", "stage", "unit", "sector", "geography_basis", "date_basis", "financing_scope")


def _mode(releases: list[dict[str, Any]]) -> str:
    modes = {"imported" if r["origin"] == "imported" else "official" for r in releases}
    return "mixed" if len(modes) > 1 else next(iter(modes), "unavailable")


class VCAPService:
    def __init__(self, store: SnapshotStore | None = None, providers: Providers | None = None) -> None:
        self.store = store or SnapshotStore()
        self.providers = providers or Providers(self.store)

    def base(self, access: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
        latest = self.store.all_latest()
        return {"status": "empty", "rows": [], "sources": catalogue(latest, access),
                "snapshots": self.store.versions(), "series": [],
                "available_geographies": sorted({r["geography"] for s in latest for r in s["dataset"]["observations"]}),
                "summary": {"observation_count": 0, "missing_count": 0, "total": None,
                            "note": "No cross-source or cross-geography total is calculated."},
                "comparison": {"comparable_pairs": [], "blocked_pairs": []},
                "methodology": METHODOLOGY}

    def import_dataset(self, raw: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        dataset = validate_dataset(raw)
        before = {v["snapshot_id"] for v in self.store.versions(dataset["source_id"])}
        release = self.store.save(dataset)
        data = self.base()
        data.update(status="ok", action="import", snapshot_id=release["snapshot_id"],
                    imported_snapshot=next(s for s in data["snapshots"] if s["snapshot_id"] == release["snapshot_id"]),
                    idempotent=release["snapshot_id"] in before,
                    reason="Dataset validated and stored locally as an immutable release.")
        return data, {"data_mode": "imported", "cached": False, "stale": False}

    def versions(self, source: Any = None) -> tuple[dict[str, Any], dict[str, Any]]:
        if source is not None:
            source = source_id(source)
        data = self.base()
        data.update(status="ok", action="versions", snapshots=self.store.versions(source))
        return data, {"data_mode": _mode(self.store.all_latest()), "cached": True, "stale": False}

    async def query(self, query: Query) -> tuple[dict[str, Any], dict[str, Any]]:
        access: dict[str, dict[str, Any]] = {}
        known = set(SOURCE_CATALOG) | {s["source_id"] for s in self.store.versions()}
        unknown = set(query.source_ids) - known
        if unknown:
            raise InputError("Unknown source_ids; import custom sources first: " + ", ".join(sorted(unknown)))
        # Validate vintage before any fetch. It pins only its owning source;
        # other selected sources keep their independently latest release.
        self.store.selected(query.source_ids, query.vintage)
        pinned_source = next((s["source_id"] for s in self.store.versions() if s["snapshot_id"] == query.vintage), None)
        for sid in query.source_ids:
            if sid not in {"oecd", "defillama"} or sid == pinned_source:
                continue
            if sid == "oecd" and (query.scope != "countries" or query.metric != "investment" or query.frequency != "annual" or query.unit not in {"USD", "PERCENT_GDP"}):
                access[sid] = {"access_status": "unsupported", "status": "unsupported", "reason": "OECD supports annual country investment in USD or percent GDP; no automated Turkey/world total."}
                continue
            if sid == "defillama" and (query.scope != "crypto" or query.metric == "fundraising" or query.stage != "total" or query.unit == "PERCENT_GDP" or query.geographies != ("WORLD",)):
                access[sid] = {"access_status": "unsupported", "status": "unsupported", "reason": "DefiLlama supports worldwide announced raises, total stage, investment/deals; no company-HQ geography or fund fundraising."}
                continue
            if sid == "defillama" and query.financing_scope == "vc":
                access[sid] = {"access_status": "unsupported" if self.store.latest(sid) else "not_configured" if not os.environ.get("SHOWME_DEFILLAMA_API_KEY") else "unsupported",
                    "status": "unsupported", "reason": "Strict VC is unavailable from the documented raises schema (no equity/token classification). Select all_raises for reported crypto financing incl token sales, or import a classified series."}
                continue
            access[sid] = await self.providers.ensure(sid, query.refresh)
        releases = self.store.selected(query.source_ids, query.vintage)
        data = self.base(access)
        rows: list[dict[str, Any]] = []
        used = []
        for release in releases:
            dataset = release["dataset"]
            selected = []
            for observation in dataset["observations"]:
                if (observation["scope"] != query.scope or observation["geography"] not in query.geographies
                        or observation["metric"] != query.metric or observation["stage"] != query.stage
                        or observation["frequency"] != query.frequency or observation["unit"] != query.unit
                        or observation.get("financing_scope", "vc") != query.financing_scope
                        or not query.start_year <= int(observation["period"][:4]) <= query.end_year):
                    continue
                selected.append({**observation,
                    **{key: dataset.get(key) for key in ("source_id", "source_name", "published_at", "methodology_version", "geography_basis", "date_basis", "sector", "source_url")},
                    "retrieved_at": release["retrieved_at"], "snapshot_id": release["snapshot_id"],
                    "vintage": release["snapshot_id"], "coverage_note": observation.get("coverage_note"),
                    "data_mode": "imported" if release["origin"] == "imported" else "official",
                    "methodology": dataset["methodology"]})
            if selected:
                used.append(release)
                rows.extend(selected)
        rows.sort(key=lambda r: (r["source_id"], r["geography"], r["period_start"], r["stage"], r["metric"], r["unit"]))
        series = _series(rows)
        warnings = [f"{sid}: {value['reason']}" for sid, value in sorted(access.items()) if value.get("reason")]
        stale = any(v.get("stale") for v in access.values())
        cached = any(v.get("cached") for v in access.values()) or bool(used) and not any(s in access and not access[s].get("cached", True) for s in query.source_ids)
        status = "ok" if rows else "provider_unavailable" if access and all(v.get("access_status") in {"provider_unavailable", "not_configured"} for v in access.values()) else "empty"
        data.update(status=status, action="query", query=asdict(query), rows=rows, series=series,
            comparison=_comparison(series), warnings=warnings,
            summary={"observation_count": len(rows), "missing_count": sum(r["value"] is None for r in rows),
                     "series_count": len(series), "total": None,
                     "latest_period": max((r["period"] for r in rows), default=None),
                     "note": "No cross-source or cross-geography total is calculated."})
        if not rows:
            data.update(reason="; ".join(warnings) or "No saved observations match the requested source, scope, geography and measurement semantics.",
                next_actions=["Select an available source/geography/period combination, or import an owned/licensed dataset using schema version 1."])
        if stale:
            data["cache_note"] = "Cached release is stale after provider failure or cache expiry; observation and publication dates are unchanged."
        return data, {"data_mode": _mode(used), "cached": bool(cached), "stale": stale,
                      "source_access": access, "provider_errors": warnings}


def _series(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[tuple(str(row.get(field, "")) for field in ("source_id",) + SIGNATURE)].append(row)
    result = []
    for key, group in sorted(groups.items()):
        first = group[0]
        result.append({"id": "|".join(key),
            **{field: first.get(field) for field in ("source_id", "source_name", "methodology_version", "methodology", "snapshot_id") + SIGNATURE},
            "points": [{field: row.get(field) for field in ("period", "period_start", "period_end", "value", "status", "coverage_note")} for row in group]})
    return result


def _comparison(series: list[dict[str, Any]]) -> dict[str, Any]:
    comparable, blocked = [], []
    for left, right in combinations(series, 2):
        reasons = [f"Different {field}" for field in SIGNATURE if left[field] != right[field]]
        if (left["source_id"] != right["source_id"] or left["methodology_version"] != right["methodology_version"] or left["methodology"] != right["methodology"]):
            reasons.append("Independent or incompatible methodologies; normalized percentage gap is blocked.")
        item = {"left": left["id"], "right": right["id"]}
        if reasons:
            blocked.append({**item, "reasons": reasons})
        else:
            comparable.append({**item, "reason": "Matching measurement semantics and source methodology."})
    return {"comparable_pairs": comparable, "blocked_pairs": blocked}
