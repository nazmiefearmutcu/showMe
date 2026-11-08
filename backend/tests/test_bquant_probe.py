"""BQUANT readiness must rest on evidence, not on flags (BQUANT#1).

Pre-fix, BQUANT reported status ok whenever the caller passed
jupyter_running=true or two example paths existed relative to the CWD, and
hard-coded the route and module availability. These tests pin the probe-based
behaviour. No network: httpx is replaced with a MockTransport.
"""

from __future__ import annotations

import asyncio
import importlib.util
from typing import Any

import httpx
import pytest

from showme.engine.functions.api import bquant as bquant_mod
from showme.engine.functions.api.bquant import BQuantFunction


LOOPBACK_BASE = "http://127.0.0.1:8899"


def _run(**params: Any) -> dict[str, Any]:
    out = asyncio.run(BQuantFunction().execute(**params))
    return out.data


def _rows_by_component(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["component"]: row for row in data["rows"]}


@pytest.fixture()
def probe_status(monkeypatch: pytest.MonkeyPatch):
    """Route every httpx request to a handler; record the requested URLs."""
    seen: list[str] = []
    state = {"status": 404}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(state["status"], request=request)

    real_client = httpx.AsyncClient

    class _MockedClient(real_client):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _MockedClient)
    monkeypatch.delenv("SHOWME_JUPYTER_URL", raising=False)
    return {"seen": seen, "state": state}


def test_jupyter_hint_alone_does_not_mark_ready(probe_status: dict[str, Any]) -> None:
    """Pre-fix: jupyter_running=True flipped status to ok with no server at all."""
    data = _run(jupyter_running=True)
    assert data["status"] == "not_configured"
    assert data["summary"]["notebook_ready"] is False
    assert data["summary"]["probe_result"] == "no_target"
    assert probe_status["seen"] == []


def test_unanswered_notebook_route_is_not_ready(
    probe_status: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The live route answers 404 (verifier evidence): BQUANT must not report ready."""
    monkeypatch.setenv("SHOWME_JUPYTER_URL", LOOPBACK_BASE)
    probe_status["state"]["status"] = 404
    data = _run(jupyter_running=True)

    assert data["status"] == "not_configured"
    assert data["summary"]["probe_result"] == "unreachable"
    assert probe_status["seen"] == [LOOPBACK_BASE + "/notebook"]
    assert "HTTP 404" in data["reason"]


def test_answering_notebook_route_marks_ready(
    probe_status: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SHOWME_JUPYTER_URL", LOOPBACK_BASE)
    probe_status["state"]["status"] = 200
    out = asyncio.run(BQuantFunction().execute())

    assert out.data["status"] == "ok"
    assert out.data["summary"]["notebook_ready"] is True
    assert out.data["summary"]["probe_result"] == "reachable"
    assert out.data["next_actions"] == []
    assert "jupyter_http_probe" in out.sources


def test_non_loopback_target_is_refused_without_a_request(
    probe_status: dict[str, Any],
) -> None:
    """The sidecar must not probe arbitrary hosts on the user's behalf."""
    data = _run(notebook_url="https://example.com/notebook")
    assert data["status"] == "not_configured"
    assert data["summary"]["probe_result"] == "no_target"
    assert "not a loopback host" in data["reason"]
    assert probe_status["seen"] == []


def test_kernel_module_row_reflects_real_imports(probe_status: dict[str, Any]) -> None:
    """Kernel modules are 'available' only if every named module actually imports."""
    data = _run()
    row = _rows_by_component(data)["Kernel modules"]
    expected_all = all(importlib.util.find_spec(name) is not None for name in bquant_mod._KERNEL_MODULES)
    assert row["status"] == ("available" if expected_all else "missing")
    found = sum(1 for name in bquant_mod._KERNEL_MODULES if importlib.util.find_spec(name) is not None)
    assert data["summary"]["preloaded_modules"] == found


def test_examples_are_scanned_from_examples_dir(tmp_path, probe_status: dict[str, Any]) -> None:
    empty = _run(examples_dir=str(tmp_path))
    assert empty["summary"]["examples_found"] == 0
    assert _rows_by_component(empty)["Examples"]["status"] == "missing"

    (tmp_path / "a.ipynb").write_text("{}", encoding="utf-8")
    (tmp_path / "b.ipynb").write_text("{}", encoding="utf-8")
    found = _run(examples_dir=str(tmp_path))
    assert found["summary"]["examples_found"] == 2
    assert _rows_by_component(found)["Examples"]["status"] == "found"


def test_redirect_is_not_a_notebook_answer(
    probe_status: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 3xx (for example a login redirect) proves a server exists, not that the notebook route answers."""
    monkeypatch.setenv("SHOWME_JUPYTER_URL", LOOPBACK_BASE)
    probe_status["state"]["status"] = 302
    data = _run()

    assert data["status"] == "not_configured"
    assert data["summary"]["notebook_ready"] is False
    assert data["summary"]["probe_result"] == "unreachable"
    assert "302" in data["reason"]
