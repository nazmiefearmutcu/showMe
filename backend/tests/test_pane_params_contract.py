"""contracts/pane_params.json must match what the UI panes actually send.

The T9b truth check reads this file (generated from the TypeScript sources by
``node scripts/extract_pane_params.mjs``) so the offline gate stays
deterministic without Node. When a pane changes its params, regenerate::

    node scripts/extract_pane_params.mjs > contracts/pane_params.json
"""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from showme.audit import gate, truth

SCRIPT = truth.REPO_ROOT / "scripts" / "extract_pane_params.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_pane_params_contract_is_fresh():
    proc = subprocess.run(["node", str(SCRIPT)], cwd=truth.REPO_ROOT, capture_output=True,
                          text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
    current = json.loads(proc.stdout)
    committed = json.loads(gate.PANE_PARAMS_PATH.read_text(encoding="utf-8"))
    assert current == committed, (
        "contracts/pane_params.json is stale; regenerate with "
        "`node scripts/extract_pane_params.mjs > contracts/pane_params.json`"
    )


def test_pane_params_contract_covers_most_panes():
    committed = json.loads(gate.PANE_PARAMS_PATH.read_text(encoding="utf-8"))
    assert len(committed["codes"]) >= 120
    for code in ("YAS", "TLH", "GREEKS", "PSC"):
        assert code in committed["codes"]
