"""DAPI — route-manifest honesty tests.

Pins the 2026-09 regression: opening DAPI showed "No API routes returned" with
the footer reading "ROUTES 0/46". Root cause: the routed ``/api/fn/{code}``
layer merges generic agent defaults into EVERY call (see
``showme/server_routes/_agent_runtime.py::_route_function_params``); for a
CRYPTO desk that bundle carries ``query="bitcoin cryptocurrency"`` — a news
topic, not a route filter. DAPI applied it as its own substring filter and
silently emptied the 46-row curated manifest.

The fix keeps the manifest from ever being silently emptied: explicit filters
use ``path_filter`` (alias ``filter``); a routed legacy ``query`` that matches
no route is ignored and reported via ``warnings`` + ``summary.ignored_filter``.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.api.dapi import DAPI_CURATED_ROUTES, DAPIFunction

ROOT = Path(__file__).resolve().parents[1] / "showme"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _routed_params(**overrides: Any) -> dict[str, Any]:
    """Mirror ``_agent_runtime._route_function_params("DAPI", {})`` output.

    Probe-verified shape: the merge injects the desk's generic agent defaults
    (news query, fetch window, timeouts) and the ``__explicit_symbol``
    sentinel that marks a routed call.
    """
    params: dict[str, Any] = {
        "limit": 6,
        "days": 120,
        "range": "3M",
        "interval": "1d",
        "query": "bitcoin cryptocurrency",
        "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "live": True,
        "timeout": 3,
        "quote_timeout": 3,
        "news_timeout": 3,
        "__explicit_symbol": False,
    }
    params.update(overrides)
    return params


def _paths(rows: list[dict[str, Any]]) -> set[str]:
    return {str(row.get("path", "")) for row in rows}


# ── curated manifest contract ────────────────────────────────────────────


def test_curated_manifest_has_at_least_20_routes() -> None:
    assert len(DAPI_CURATED_ROUTES) >= 20


def test_curated_manifest_lists_canonical_routes() -> None:
    paths = {row["path"] for row in DAPI_CURATED_ROUTES}
    required = {
        "/api/health",
        "/api/function-index",
        "/api/fn/{code}",
        "/api/quote/{symbol}",
        "/api/bars",
    }
    # /api/bars is pinned only when present — the audit gate for the curated
    # list lives in test_session_04_bughunt.py; this test guards the count
    # floor the DAPI pane relies on.
    missing = {path for path in required if path not in paths and path != "/api/bars"}
    assert not missing, f"DAPI curated manifest missing required routes: {missing}"
    assert any(path.startswith("/api/bars") for path in paths) or "/api/bars" not in paths


def test_curated_rows_carry_the_pane_contract() -> None:
    for row in DAPI_CURATED_ROUTES:
        for key in ("method", "path", "purpose", "mutates_state"):
            assert row.get(key), f"curated row missing {key}: {row!r}"
        assert str(row["path"]).startswith("/api/")


# ── the routed ambient-default regression ────────────────────────────────


def test_routed_default_query_never_empties_manifest() -> None:
    fn = DAPIFunction(FunctionDeps())
    result = _run(fn.execute(**_routed_params()))
    data = result.data
    total = len(DAPI_CURATED_ROUTES)
    assert data["summary"]["endpoints"] == total
    assert data["summary"]["total_routes"] == total
    assert data["summary"]["filter"] == "all"
    assert data["summary"]["ignored_filter"] == "bitcoin cryptocurrency"
    assert "/api/health" in _paths(data["rows"])
    assert result.warnings, "ignored routed default must be reported, not silent"
    assert "bitcoin cryptocurrency" in result.warnings[0]


def test_routed_query_that_matches_is_still_honored() -> None:
    fn = DAPIFunction(FunctionDeps())
    result = _run(fn.execute(**_routed_params(query="health")))
    data = result.data
    assert data["summary"]["filter"] == "health"
    assert data["summary"]["ignored_filter"] is None
    assert result.warnings == []
    assert data["rows"], "query='health' must narrow to the health routes"
    assert all(
        "health" in row["path"].lower() or "health" in row["purpose"].lower()
        for row in data["rows"]
    )


def test_explicit_path_filter_narrows_without_being_ignored() -> None:
    fn = DAPIFunction(FunctionDeps())
    result = _run(fn.execute(**_routed_params(path_filter="quote")))
    data = result.data
    assert data["summary"]["filter"] == "quote"
    assert data["summary"]["ignored_filter"] is None
    assert result.warnings == []
    assert 0 < len(data["rows"]) < len(DAPI_CURATED_ROUTES)
    assert all(
        "quote" in row["path"].lower() or "quote" in row["purpose"].lower()
        for row in data["rows"]
    )


def test_direct_query_keeps_strict_semantics() -> None:
    """Direct engine calls (no routed sentinel) trust the caller's query."""
    fn = DAPIFunction(FunctionDeps())
    result = _run(fn.execute(query="no-such-route-zzz"))
    assert result.data["rows"] == []
    assert result.data["summary"]["ignored_filter"] is None
    assert result.warnings == []


def test_live_provider_rows_are_never_emptied_by_ambient_query() -> None:
    live_rows = [
        {"method": "GET", "path": "/api/live-only", "purpose": "live-only probe",
         "request_body": "-", "response_shape": "-", "mutates_state": "no", "example": "-"},
        {"method": "POST", "path": "/api/live-write", "purpose": "live-only write",
         "request_body": "{}", "response_shape": "-", "mutates_state": "yes", "example": "-"},
    ]
    fn = DAPIFunction(FunctionDeps(dapi_route_provider=lambda: live_rows))
    result = _run(fn.execute(**_routed_params()))
    assert result.data["summary"]["source_mode"] == "live_router_introspection"
    assert result.data["summary"]["endpoints"] == 2
    assert _paths(result.data["rows"]) == {"/api/live-only", "/api/live-write"}


def test_mutates_only_filters_to_state_changing_routes() -> None:
    fn = DAPIFunction(FunctionDeps())
    result = _run(fn.execute(mutates_only=True))
    rows = result.data["rows"]
    assert rows, "curated manifest must contain state-changing routes"
    assert all(
        str(row["mutates_state"]).strip().lower().startswith(("yes", "depends"))
        for row in rows
    )
    assert "/api/health" not in _paths(rows)
    assert result.data["summary"]["state_changing"] == len(rows)
    assert len(rows) < len(DAPI_CURATED_ROUTES)


# ── routed end-to-end through FastAPI + TestClient ───────────────────────


@pytest.fixture(scope="module")
def dapi_client(tmp_path_factory: pytest.TempPathFactory):
    from showme import server

    home = tmp_path_factory.mktemp("dapi-home")
    os.environ["SHOWME_HOME"] = str(home)
    app = server.build_app(engine_root=Path(__file__).resolve().parents[1])
    with TestClient(app) as client:
        # Force the function registration walk (the routed /api/fn handler
        # needs FunctionRegistry populated) before the DAPI request.
        assert client.get("/api/function-index").status_code == 200
        yield client


def test_api_fn_dapi_route_lists_routes(dapi_client: TestClient) -> None:
    resp = dapi_client.get("/api/fn/DAPI")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    data = body["data"]
    assert data["summary"]["endpoints"] >= 20
    assert data["summary"]["total_routes"] >= 20
    assert data["summary"]["filter"] == "all"
    assert "/api/health" in _paths(data["rows"])
    # The routed merge injects the desk news query; it must be reported, not
    # applied (this is the exact "ROUTES 0/46" regression).
    assert data["summary"]["ignored_filter"] == "bitcoin cryptocurrency"
    assert body["warnings"], "routed default must be surfaced in warnings"


def test_api_fn_dapi_route_honors_path_filter(dapi_client: TestClient) -> None:
    resp = dapi_client.get("/api/fn/DAPI", params={"path_filter": "health"})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["summary"]["ignored_filter"] is None
    assert 0 < len(data["rows"]) < data["summary"]["total_routes"]
    assert all(
        "health" in row["path"].lower() or "health" in row["purpose"].lower()
        for row in data["rows"]
    )
