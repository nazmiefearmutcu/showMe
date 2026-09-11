"""G2 OPP wave — ECST compare overlay regression (backend honesty).

Audit ref A1-ECST: the backend already supports ``compare_with`` and emits
``compare_value`` / ``compare_series_name``, but the compare series' own
provenance was not exposed (and a failed compare fetch silently served the
labelled ``macro_series_baseline`` under the MAIN series' mode). These tests
pin the repaired contract:

* a successful compare fetch emits ``compare_series_id`` /
  ``compare_series_name`` / ``compare_source_mode`` + per-row
  ``compare_value``;
* a failed compare fetch falls back to the labelled baseline with an
  explicit ``compare_source_mode`` and a warning — the main series'
  ``source_mode`` is never flipped by the compare leg.

Offline: the FRED provider is injected via the module's
``fred_with_keyless_fallback`` hook (same pattern as
``test_f4_macro_fixes.py``).
"""

from __future__ import annotations

import asyncio

import pandas as pd

from showme.engine.core.base_function import FunctionDeps


def _run(coro):
    return asyncio.run(coro)


class _Fred:
    """Minimal FRED stand-in: series() serves a small frame per series id."""

    def __init__(self, fail_ids: set[str] | None = None) -> None:
        self.fail_ids = fail_ids or set()
        self.calls: list[str] = []

    async def series(self, sid, *args, **kwargs):
        self.calls.append(sid)
        if sid in self.fail_ids:
            raise RuntimeError("simulated provider outage")
        base = 4.0 if sid == "DGS10" else 3.5
        return pd.DataFrame(
            {
                "date": ["2026-01-02", "2026-01-05", "2026-01-06"],
                "value": [base, base + 0.05, base + 0.1],
            }
        )

    async def info(self, sid):
        return {"title": f"{sid} title", "units": "%", "frequency": "daily"}


def _execute_with_fred(monkeypatch, fred: _Fred, **params):
    import showme.engine.functions.macro.ecst as ecst_mod

    monkeypatch.setattr(
        ecst_mod,
        "fred_with_keyless_fallback",
        lambda deps_fred, client=None: fred,
    )
    return _run(ecst_mod.ECSTFunction(FunctionDeps()).execute(**params))


def test_ecst_compare_success_labels_both_series(monkeypatch):
    fred = _Fred()
    result = _execute_with_fred(
        monkeypatch, fred, series_id="DGS10", compare_with="DGS2"
    )
    data = result.data

    assert fred.calls == ["DGS10", "DGS2"]
    assert data["compare_series_id"] == "DGS2"
    assert data["compare_series_name"] == "DGS2 title"
    assert data["compare_source_mode"] == "fred"
    # The MAIN series' mode is not flipped by the compare leg.
    assert data["source_mode"] == "fred"
    assert result.sources == ["fred"]
    assert result.warnings == []

    rows = [row for row in data["rows"] if "compare_value" in row]
    assert rows, "paired rows must carry compare_value"
    assert all(isinstance(row["compare_value"], float) for row in rows)


def test_ecst_compare_failure_uses_labelled_baseline(monkeypatch):
    fred = _Fred(fail_ids={"DGS2"})
    result = _execute_with_fred(
        monkeypatch, fred, series_id="DGS10", compare_with="DGS2"
    )
    data = result.data

    # Main series stayed live; only the compare leg fell back.
    assert data["source_mode"] == "fred"
    assert data["compare_source_mode"] == "macro_series_baseline"
    assert any(
        "DGS2 compare series was unavailable" in warning
        for warning in result.warnings
    ), "the compare fallback must be disclosed in warnings"
    assert "macro_series_baseline" in result.sources
    # The overlay still has a comparable value on every merged row.
    assert any("compare_value" in row for row in data["rows"])
