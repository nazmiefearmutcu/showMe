"""ALRT honesty regressions (p2a-g02).

Covers the ALRT function's data-honesty defects:

* ALRT#1 — a rule stored by ``add`` must not report success as if it fires;
  the response says it is stored but not armed (no evaluator in this build).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from showme.engine.functions.misc.alrt import ALRTFunction, _store  # noqa: E402


@pytest.fixture
def alrt_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    yield tmp_path


@pytest.mark.asyncio
async def test_add_reports_stored_not_armed(alrt_home: Path) -> None:
    """ALRT#1: add must say the rule is not armed, not a plain success."""
    fn = ALRTFunction()
    res = await fn.execute(action="add", condition="AAPL.price > 200")

    assert res.data["armed"] is False, res.data
    assert res.data["status"] == "stored_not_armed", res.data
    assert any("not armed" in w for w in res.warnings), res.warnings
