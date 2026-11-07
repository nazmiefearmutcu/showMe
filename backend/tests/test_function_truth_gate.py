"""Offline truth gate (B1c): no new placeholder defaults, asset mismatches or
template help text may enter the function catalog.

Runs T4 (AST scan of every registered function's module), T5 (catalog
example vs declared asset classes) and T6 (help text) with no sidecar and no
network, then compares per-function counts to ``tests/_truth_baseline.json``.
Counts may only go down. When a fix lowers them, refresh the baseline with::

    SHOWME_UPDATE_TRUTH_BASELINE=1 pytest tests/test_function_truth_gate.py

which refuses to raise any count. Live checks (T2/T3/T7/T8) run in
``scripts/showme_function_audit.py --strict``.
"""
from __future__ import annotations

import os

import pytest

from showme.audit import gate, truth


@pytest.fixture(scope="module")
def current_counts():
    cfg = truth.load_config()
    sources = gate.registry_sources()
    findings = gate.collect_offline_findings(gate.catalog_entries(), sources.get, cfg)
    return gate.to_counts(findings)


def test_catalog_and_sources_are_scanned(current_counts):
    entries = gate.catalog_entries()
    assert len(entries) >= 141
    assert len(gate.registry_sources()) >= 130


def test_no_new_offline_truth_findings(current_counts):
    baseline = gate.load_baseline()
    if baseline is None:
        gate.write_baseline(current_counts)
        pytest.skip(f"seeded {gate.BASELINE_PATH.name}; re-run to enforce")
    if os.environ.get("SHOWME_UPDATE_TRUTH_BASELINE") == "1":
        gate.write_baseline(gate.lowered_baseline(current_counts, baseline))
        baseline = gate.load_baseline()
    rises = gate.regressions(current_counts, baseline)
    assert not rises, (
        "new offline truth findings (fix them; the baseline only goes down):\n  " + "\n  ".join(rises)
    )


# ── ratchet mechanics ─────────────────────────────────────────────────────


def test_regressions_flags_only_increases():
    baseline = {"PSC": {"T4:placeholder_default": 2}, "MARS": {"T6:empty_description": 1}}
    current = {"PSC": {"T4:placeholder_default": 1}, "MARS": {"T6:empty_description": 1},
               "NEW": {"T6:template_purpose": 1}}
    assert gate.regressions(current, baseline) == ["NEW T6:template_purpose: 1 > baseline 0"]


def test_lowered_baseline_refuses_to_raise():
    baseline = {"PSC": {"T4:placeholder_default": 1}}
    with pytest.raises(ValueError, match="refusing to raise"):
        gate.lowered_baseline({"PSC": {"T4:placeholder_default": 2}}, baseline)
    assert gate.lowered_baseline({}, baseline) == {}
