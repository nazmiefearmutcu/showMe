"""Production-fakery ban: source-tree guard for showMe.

Contract
--------
The rebuild forbids production-path dependencies on three fakery
modules — ``ui/src/panes/FunctionStub.tsx``, ``ui/src/templates/*`` (via
``TemplateRenderer``), and ``ui/src/design-export/*``. The matching
backend production registration is ``server_routes/templates.py`` being
wired into ``server_routes/__init__.py``.

These modules may continue to exist as files in the working tree (the
rebuild is incremental), but no NEW production code is allowed to
import or reference them. This test enforces that direction without
breaking the suite today by means of a **baseline file**:

* On first run, the test scans the tree and WRITES
  ``tests/_fakery_baseline.json`` with the current totals + per-file
  line locations. The test PASSES.
* On every subsequent run, the test re-scans and compares. If totals
  EXCEED the baseline (any pattern, anywhere), the test FAILS with a
  diff of new violations.
* If totals are AT OR BELOW the baseline, the test PASSES and prints a
  one-line summary, hinting at how much fakery has shrunk since the
  baseline was seeded.

Definition modules — the FunctionStub file, the design-export folder,
the templates folder, and ``__pycache__`` — are excluded from the scan
so the test only flags consumers, never the (still-existing)
definitions. Test files (``*.test.tsx`` / ``*.test.ts`` /
``backend/tests/`` / ``tests/``) are also excluded because they
legitimately exercise the fakery modules to keep the existing suite
green during the rebuild.

A companion strict test (skipped by default) asserts the totals are
zero — flip it on once the rebuild has fully eliminated fakery.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
UI_SRC = REPO_ROOT / "ui" / "src"
BACKEND_SHOWME = REPO_ROOT / "backend" / "showme"
BACKEND_ROUTES = BACKEND_SHOWME / "server_routes"
BASELINE_PATH = Path(__file__).resolve().parent / "_fakery_baseline.json"


# ---------------------------------------------------------------------------
# Exclusions — definitions, tests, cache, vendored artifacts
# ---------------------------------------------------------------------------

# Path-prefix excludes (relative to REPO_ROOT). Any file whose absolute
# path starts with these is skipped — they are the legitimate homes of
# the fakery code (definitions) or are out-of-scope (tests, build, deps).
_EXCLUDE_PREFIXES: tuple[Path, ...] = (
    UI_SRC / "design-export",
    UI_SRC / "templates",
    UI_SRC / "panes" / "FunctionStub.tsx",
    UI_SRC / "panes" / "function_stub",
    BACKEND_SHOWME / "templates",
    REPO_ROOT / "tests",
    REPO_ROOT / "backend" / "tests",
    REPO_ROOT / "node_modules",
    REPO_ROOT / "ui" / "node_modules",
    REPO_ROOT / "ui" / "dist",
    REPO_ROOT / "ui" / ".vite",
    REPO_ROOT / "backend" / "build",
    REPO_ROOT / "backend" / "dist",
    REPO_ROOT / "artifacts",
    REPO_ROOT / "test-results",
    REPO_ROOT / "runtime",
)

# Filename-substring excludes — co-located unit tests.
_EXCLUDE_NAME_SUBSTRINGS: tuple[str, ...] = (
    ".test.tsx",
    ".test.ts",
)


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Each pattern is (label, compiled regex). Labels are stable identifiers
# written into the baseline JSON — renaming a label invalidates the
# baseline. Patterns intentionally err on the side of being permissive
# enough to catch consumers without requiring perfect grammar; the
# baseline mechanism absorbs the initial population.

_TS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Static spelling: `import { FunctionStub } from "..."` — anything
    # whose source string ends in `FunctionStub` before the closing
    # quote.
    (
        "ts_import_FunctionStub",
        re.compile(
            r"""^[ \t]*import\b[^\n]*?\bfrom\s+['"][^'"\n]*FunctionStub[^'"\n]*['"]""",
            re.MULTILINE,
        ),
    ),
    # Dynamic spelling: `import("@/panes/FunctionStub")` inside a
    # `lazy(() => …)` (or any other async loader). This is the spelling
    # Workspace.tsx actually uses today — without it the ban would miss
    # the only consumer worth catching.
    (
        "ts_dynamic_import_FunctionStub",
        re.compile(r"""\bimport\s*\(\s*['"][^'"\n]*FunctionStub[^'"\n]*['"]\s*\)"""),
    ),
    # Static spelling for TemplateRenderer.
    (
        "ts_import_TemplateRenderer",
        re.compile(
            r"""^[ \t]*import\b[^\n]*?\bfrom\s+['"][^'"\n]*templates/TemplateRenderer[^'"\n]*['"]""",
            re.MULTILINE,
        ),
    ),
    # Dynamic spelling for TemplateRenderer.
    (
        "ts_dynamic_import_TemplateRenderer",
        re.compile(
            r"""\bimport\s*\(\s*['"][^'"\n]*templates/TemplateRenderer[^'"\n]*['"]\s*\)""",
        ),
    ),
    # Any STATIC import that pulls from `design-export/...` — e.g. the
    # SettingsDesignExportRenderer entry point.
    (
        "ts_import_design_export",
        re.compile(
            r"""^[ \t]*import\b[^\n]*?\bfrom\s+['"][^'"\n]*design-export[^'"\n]*['"]""",
            re.MULTILINE,
        ),
    ),
    # Dynamic spelling for design-export modules.
    (
        "ts_dynamic_import_design_export",
        re.compile(r"""\bimport\s*\(\s*['"][^'"\n]*design-export[^'"\n]*['"]\s*\)"""),
    ),
    # Static import that pulls from `templates/...` (other than the
    # TemplateRenderer entry, already counted above). Catches
    # `from "@/templates/primitives"`, `from "@/templates/registry"`, etc.
    (
        "ts_import_templates_dir",
        re.compile(
            r"""^[ \t]*import\b[^\n]*?\bfrom\s+['"][^'"\n]*?/templates/(?!TemplateRenderer\b)[^'"\n]+['"]""",
            re.MULTILINE,
        ),
    ),
    # Dynamic import for any other templates/ entry.
    (
        "ts_dynamic_import_templates_dir",
        re.compile(
            r"""\bimport\s*\(\s*['"][^'"\n]*?/templates/(?!TemplateRenderer\b)[^'"\n]+['"]\s*\)""",
        ),
    ),
    # JSX usage: `<FunctionStub …` / `<FunctionStub/>` / `<FunctionStub>`.
    (
        "ts_jsx_FunctionStub",
        re.compile(r"<FunctionStub\b"),
    ),
    # JSX usage: `<TemplateRenderer …`.
    (
        "ts_jsx_TemplateRenderer",
        re.compile(r"<TemplateRenderer\b"),
    ),
)

# Backend Python patterns — production registrations that wire the
# template subsystem (or any fakery handler family) into FastAPI.
_PY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # `templates.register(app, deps)` or `templates.register(app)` —
    # registers the /api/templates/* family. This stays in the baseline
    # until the rebuild deletes the family or replaces it with a real
    # data-backed implementation.
    (
        "py_template_registration",
        re.compile(r"\btemplates\.register\s*\("),
    ),
)


# ---------------------------------------------------------------------------
# Scan helpers
# ---------------------------------------------------------------------------


def _is_excluded(path: Path) -> bool:
    """True iff ``path`` lives under a definition / out-of-scope tree."""
    # Filename-substring excludes (covers co-located unit tests with the
    # rest of the source — e.g. ui/src/panes/Welcome.test.tsx).
    name = path.name
    for needle in _EXCLUDE_NAME_SUBSTRINGS:
        if needle in name:
            return True
    # Prefix excludes — resolve once so symlinks don't sneak past the
    # comparison. ``is_relative_to`` is the cleanest match here.
    try:
        resolved = path.resolve()
    except OSError:
        return True
    for prefix in _EXCLUDE_PREFIXES:
        try:
            if resolved.is_relative_to(prefix):
                return True
        except (AttributeError, ValueError):
            # Python < 3.9 fallback shouldn't trigger on 3.11+, but stays
            # defensive in case of cross-platform path quirks.
            if str(resolved).startswith(str(prefix)):
                return True
    # __pycache__ anywhere on the path.
    if "__pycache__" in resolved.parts:
        return True
    return False


def _iter_files(
    root: Path,
    suffixes: Iterable[str],
) -> Iterable[Path]:
    """Yield every file under ``root`` with a suffix in ``suffixes`` that
    is not excluded by ``_is_excluded``."""
    suffix_set = {s.lower() for s in suffixes}
    if not root.exists():
        return
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in suffix_set:
            continue
        if _is_excluded(path):
            continue
        yield path


def _scan(
    files: Iterable[Path],
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
) -> dict[str, list[dict[str, Any]]]:
    """Return {file_path: [{line, pattern}, ...]} for matches under ``files``."""
    violations: dict[str, list[dict[str, Any]]] = {}
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        path_key = str(path)
        for label, pat in patterns:
            for match in pat.finditer(text):
                line = text[: match.start()].count("\n") + 1
                violations.setdefault(path_key, []).append(
                    {"line": line, "pattern": label},
                )
    # Sort entries within each file so the baseline is stable across runs.
    for entries in violations.values():
        entries.sort(key=lambda e: (e["line"], e["pattern"]))
    return violations


def _totals_by_pattern(
    violations: dict[str, list[dict[str, Any]]],
) -> dict[str, int]:
    """Aggregate per-pattern counts across every flagged file."""
    counts: dict[str, int] = {}
    for entries in violations.values():
        for entry in entries:
            counts[entry["pattern"]] = counts.get(entry["pattern"], 0) + 1
    # Sort for deterministic JSON output.
    return dict(sorted(counts.items()))


def _scan_everything() -> dict[str, Any]:
    """Run every configured scan and return a baseline-shaped dict."""
    ts_files = list(_iter_files(UI_SRC, (".ts", ".tsx")))
    py_files = list(_iter_files(BACKEND_SHOWME, (".py",)))
    ts_violations = _scan(ts_files, _TS_PATTERNS)
    py_violations = _scan(py_files, _PY_PATTERNS)
    combined: dict[str, list[dict[str, Any]]] = {}
    combined.update(ts_violations)
    # Merge per-file entries from the Python pass on top of the TS pass.
    # No overlap is expected (different suffixes), but stay defensive.
    for path_key, entries in py_violations.items():
        combined.setdefault(path_key, []).extend(entries)
    # Re-sort entries inside any file that received both TS and PY hits.
    for entries in combined.values():
        entries.sort(key=lambda e: (e["line"], e["pattern"]))
    return {
        "root": str(REPO_ROOT),
        "totals_by_pattern": _totals_by_pattern(combined),
        "violations": dict(sorted(combined.items())),
    }


# ---------------------------------------------------------------------------
# Baseline I/O
# ---------------------------------------------------------------------------


def _load_baseline() -> dict[str, Any] | None:
    """Return the parsed baseline JSON, or None if absent / unreadable."""
    if not BASELINE_PATH.exists():
        return None
    try:
        return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_baseline(payload: dict[str, Any]) -> None:
    """Persist ``payload`` to ``_fakery_baseline.json`` deterministically."""
    serialised = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    BASELINE_PATH.write_text(serialised, encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_production_fakery_baseline_seed_or_no_growth(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Seed the baseline (first run) or assert violations have not grown."""
    current = _scan_everything()
    current_totals = current["totals_by_pattern"]

    baseline = _load_baseline()
    if baseline is None:
        _write_baseline(current)
        message = (
            f"[fakery-ban] Seeded baseline at {BASELINE_PATH.name} with "
            f"{sum(current_totals.values())} violation(s) across "
            f"{len(current['violations'])} file(s). Totals by pattern: "
            f"{current_totals}."
        )
        # ``print`` so the seeded line shows up in -v / -s pytest output.
        print(message)
        # On the seed run the test passes by definition — there is
        # nothing to compare against yet.
        return

    baseline_totals = dict(baseline.get("totals_by_pattern", {}))

    # 1. Per-pattern growth check. Any pattern whose current count
    #    exceeds the baseline count is a regression.
    grew: dict[str, dict[str, int]] = {}
    for pattern in sorted(set(baseline_totals) | set(current_totals)):
        before = int(baseline_totals.get(pattern, 0))
        after = int(current_totals.get(pattern, 0))
        if after > before:
            grew[pattern] = {"before": before, "after": after}

    if grew:
        # Surface the offending file+line entries so the failure is
        # immediately actionable. We diff per-pattern violations; if the
        # diff is empty (e.g. the baseline JSON was hand-edited to a
        # smaller total without removing the line entries), we fall
        # back to listing every current line for the grown pattern(s).
        baseline_violations = _flatten(baseline.get("violations", {}))
        current_violations = _flatten(current["violations"])
        new_hits = sorted(current_violations - baseline_violations)
        msg_lines = ["[fakery-ban] new violations detected:"]
        for pattern, before_after in grew.items():
            msg_lines.append(
                f"  {pattern}: {before_after['before']} -> {before_after['after']}",
            )
        if new_hits:
            msg_lines.append("  new entries (file:line:pattern):")
            for hit in new_hits[:50]:
                msg_lines.append(f"    {hit}")
            if len(new_hits) > 50:
                msg_lines.append(f"    ... and {len(new_hits) - 50} more")
        else:
            # Pattern totals grew but no NEW lines appear in the current
            # scan — typically means the baseline JSON's totals were
            # hand-edited below reality. Dump every current entry for
            # the grown pattern(s) so the operator can either reseed or
            # explain.
            grown_patterns = set(grew.keys())
            relevant = sorted(
                hit for hit in current_violations
                if hit.rsplit(":", 1)[-1] in grown_patterns
            )
            msg_lines.append(
                "  no new file:line entries vs. baseline (totals diverged "
                "from recorded lines — was the baseline hand-edited?). "
                "Current entries for grown pattern(s):",
            )
            for hit in relevant[:50]:
                msg_lines.append(f"    {hit}")
            if len(relevant) > 50:
                msg_lines.append(f"    ... and {len(relevant) - 50} more")
        msg_lines.append(
            "If this is intentional (e.g. you legitimately need to "
            "extend a still-existing fakery surface during the rebuild), "
            f"delete {BASELINE_PATH.name} and rerun this test to reseed.",
        )
        raise AssertionError("\n".join(msg_lines))

    # 2. Shrink-aware reporting. Compute the delta to give a healthy
    #    nudge: every successful run logs how much progress has been
    #    made vs. the baseline.
    delta = sum(baseline_totals.values()) - sum(current_totals.values())
    if delta > 0:
        print(
            f"[fakery-ban] PASS — violations decreased by {delta} since "
            f"baseline ({sum(baseline_totals.values())} -> "
            f"{sum(current_totals.values())}). Reseed by deleting "
            f"{BASELINE_PATH.name} to lock in the new ceiling.",
        )
    else:
        print(
            f"[fakery-ban] PASS — at baseline "
            f"({sum(current_totals.values())} total violation(s)).",
        )
    # Suppress unused-fixture warning if `-s` is not in use.
    _ = capsys


def _flatten(
    violations_by_file: dict[str, list[dict[str, Any]]],
) -> set[str]:
    """Hashable per-violation set for diffing baseline vs. current scans."""
    out: set[str] = set()
    for path_key, entries in violations_by_file.items():
        for entry in entries:
            out.add(f"{path_key}:{entry.get('line')}:{entry.get('pattern')}")
    return out


def test_production_fakery_strict_zero() -> None:
    """Strict gate: zero violations everywhere.

    Flipped on 2026-05-24 after the rebuild drove the baseline to zero.
    Now the permanent ban — any new violation fails CI immediately.
    """
    current = _scan_everything()
    totals = current["totals_by_pattern"]
    grand_total = sum(totals.values())
    assert grand_total == 0, (
        f"production-fakery ban is strict-mode: expected 0 violations, "
        f"found {grand_total} ({totals}). Offending files: "
        f"{sorted(current['violations'].keys())}"
    )
