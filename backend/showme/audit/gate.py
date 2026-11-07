"""Offline truth gate: collect T4-AST/T5-catalog/T6 findings and ratchet them.

No sidecar and no network: the catalog comes from
``showme.server._load_function_index`` and sources from the function
registry. The baseline (``tests/_truth_baseline.json``) stores, per function,
a count per ``"<check>:<rule>"``. The gate fails when any count rises above
its baseline (a new finding); counts may only go down, and the baseline is
only ever rewritten downward (:func:`lowered_baseline` refuses increases).
"""
from __future__ import annotations

import importlib
import inspect
import json
import pkgutil
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from showme.audit import truth

BASELINE_PATH = truth.REPO_ROOT / "tests" / "_truth_baseline.json"

Counts = dict[str, dict[str, int]]


def catalog_entries() -> list[dict[str, Any]]:
    from showme import server

    out = []
    for entry in server._load_function_index():
        out.append(entry.model_dump() if hasattr(entry, "model_dump") else dict(entry))
    return out


# Functions implemented inside the server itself rather than as engine
# classes (no registry entry, so no source to scan).
SERVER_NATIVE_CODES = frozenset({"GP", "HP"})

Source = tuple[str, str, str]  # (source text, "file.py", class name)


def registry_sources() -> tuple[dict[str, Source], dict[str, str]]:
    """``({CODE: (text, "file.py", ClassName)}, {module: import error})``.

    Import errors are returned, not swallowed: a module that stops importing
    would otherwise silently drop its findings from the ratchet.
    """
    import showme.engine.functions as functions_pkg
    from showme.engine.core.base_function import FunctionRegistry

    errors: dict[str, str] = {}
    for mod in pkgutil.walk_packages(functions_pkg.__path__, functions_pkg.__name__ + "."):
        try:
            importlib.import_module(mod.name)
        except Exception as exc:  # noqa: BLE001 - reported to the caller
            errors[mod.name] = f"{type(exc).__name__}: {exc}"
    files: dict[str, Source] = {}
    for code, cls in FunctionRegistry._instances.items():
        try:
            path = Path(inspect.getsourcefile(cls) or "")
            files[code.upper()] = (path.read_text(encoding="utf-8"), path.name, cls.__name__)
        except (OSError, TypeError) as exc:
            errors[f"{cls.__module__}.{cls.__name__}"] = f"source unavailable: {exc}"
    return files, errors


def offline_findings_for(
    entry: dict[str, Any], source: Source | None, cfg: truth.TruthConfig
) -> list[truth.Finding]:
    """T5 catalog + T6 help + T4 AST (scoped to the function's class)."""
    items = truth.check_catalog_entry_assets(entry) + truth.check_help_text(entry, cfg=cfg)
    if source is not None:
        text, filename, class_name = source
        items += truth.scan_source_placeholders(text, filename, cfg=cfg, class_name=class_name)
    return items


def collect_offline_findings(
    entries: list[dict[str, Any]],
    source_lookup: Callable[[str], Source | None],
    cfg: truth.TruthConfig,
) -> dict[str, list[truth.Finding]]:
    return {
        str(entry.get("code", "")).upper(): offline_findings_for(
            entry, source_lookup(str(entry.get("code", "")).upper()), cfg
        )
        for entry in entries
    }


def to_counts(findings: dict[str, list[truth.Finding]]) -> Counts:
    out: Counts = {}
    for code, items in sorted(findings.items()):
        c = Counter(f"{f.check}:{f.rule}" for f in items)
        if c:
            out[code] = dict(sorted(c.items()))
    return out


def regressions(current: Counts, baseline: Counts) -> list[str]:
    """Human-readable list of counts that rose above the baseline."""
    out = []
    for code, rules in sorted(current.items()):
        for rule, n in sorted(rules.items()):
            allowed = baseline.get(code, {}).get(rule, 0)
            if n > allowed:
                out.append(f"{code} {rule}: {n} > baseline {allowed}")
    return out


def lowered_baseline(current: Counts, baseline: Counts) -> Counts:
    """The new baseline after improvements; refuses to raise any count."""
    rises = regressions(current, baseline)
    if rises:
        raise ValueError("refusing to raise the truth baseline:\n  " + "\n  ".join(rises))
    return current


def load_baseline(path: Path = BASELINE_PATH) -> Counts | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))["counts"]


def write_baseline(counts: Counts, path: Path = BASELINE_PATH) -> None:
    total = sum(sum(r.values()) for r in counts.values())
    doc = {
        "_doc": "Offline truth-gate ratchet (backend/showme/audit/gate.py). Per function: count per "
                "'<check>:<rule>'. Counts may only go down. Regenerate downward with "
                "SHOWME_UPDATE_TRUTH_BASELINE=1 pytest tests/test_function_truth_gate.py.",
        "total": total,
        "counts": counts,
    }
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
