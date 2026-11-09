"""EXEC#6 follow-up: ``action=open`` must refuse a non-finite or non-positive target_qty.

The plan branch already requires a finite positive ``target_qty``. The open
branch only checked presence, so ``nan``, ``inf``, ``-5`` and ``0`` were stored
as the parent quantity and every later pace figure was computed against them.

No network: the monitor store lives in a temporary SHOWME_HOME.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from showme.engine.functions.trade.exec import EXECFunction
from showme.engine.services import exec_monitor


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    yield


def _open(parent_id: str, target_qty):
    return asyncio.run(EXECFunction().execute(
        action="open", parent_id=parent_id, symbol="AAPL", side="buy",
        target_qty=target_qty, algo="TWAP",
    ))


@pytest.mark.parametrize("bad_qty", ["nan", "inf", "-inf", "-5", "0"])
def test_open_refuses_non_finite_or_non_positive_target_qty(bad_qty: str) -> None:
    parent_id = f"p-bad-{bad_qty}"
    result = _open(parent_id, bad_qty)
    assert result.data.get("status") == "invalid_request", result.data
    assert "invalid field value" in result.data["reason"], result.data
    # Nothing is persisted for a refused open.
    assert exec_monitor.get_parent(parent_id) is None


def test_open_accepts_a_finite_positive_target_qty() -> None:
    result = _open("p-good", 250)
    assert result.data.get("status") in (None, "ok"), result.data
    assert "id" in result.data
    parent = exec_monitor.get_parent("p-good")
    assert parent is not None
    assert float(parent["target_qty"]) == 250.0
