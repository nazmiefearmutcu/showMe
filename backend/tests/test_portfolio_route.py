"""FastAPI route tests for /api/portfolio/positions/{symbol}/close."""
from __future__ import annotations

import json
import pytest
from fastapi.testclient import TestClient

from showme.server import build_app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.setenv("SHOWME_IMPORT_LEGACY_TBV3", "1")
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")

    # Create dummy state.json in the runtime directory relative to SHOWME_HOME
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    state_file = runtime_dir / "state.json"
    state_file.write_text(json.dumps({
        "positions": {
            "4USDT": {
                "symbol": "4USDT",
                "entry_price": 0.010289,
                "quantity": 100.0,
                "current_price": 0.01231,
                "open_time": "2026-04-27T15:44:27.267875+00:00",
                "current_signal": "NEUTRAL",
            },
        },
    }))

    app = build_app(engine_root=None)
    return TestClient(app)


def test_close_position_not_found(client):
    r = client.post("/api/portfolio/positions/nonexistent/close", json={"exit_price": 10.0, "dry_run": True})
    assert r.status_code == 404
    assert "position not found" in r.json()["detail"]


def test_close_position_invalid_exit_price(client):
    r = client.post("/api/portfolio/positions/4USDT/close", json={"exit_price": "invalid", "dry_run": True})
    assert r.status_code == 400
    assert "exit_price must be numeric" in r.json()["detail"]


def test_close_position_dry_run(client):
    # Close 4USDT position in dry_run mode
    r = client.post("/api/portfolio/positions/4usdt/close", json={"exit_price": 0.012, "dry_run": True})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["dry_run"] is True
    assert body["record"]["symbol"] == "4USDT"
    assert body["remaining_positions"] == 1


def test_close_position_real(client):
    # Close 4USDT position for real
    r = client.post("/api/portfolio/positions/4usdt/close", json={"exit_price": 0.012, "dry_run": False})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["dry_run"] is False
    assert body["remaining_positions"] == 0
