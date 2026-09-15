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


# ---- POST /api/portfolio/positions (manual add — Welcome exposure) ---------


def test_add_position_ok(client):
    r = client.post(
        "/api/portfolio/positions",
        json={"symbol": "aapl", "quantity": 10, "avg_cost": 195.5},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    pos = body["position"]
    assert pos["instrument"]["symbol"] == "AAPL"
    assert pos["instrument"]["asset_class"] == "EQUITY"
    assert pos["quantity"] == 10
    assert pos["avg_cost"] == 195.5
    assert pos["account"] == "main"
    # Fixture imports one legacy position, so the fresh book now has two.
    assert body["positions_count"] == 2


def test_add_position_crypto_infers_asset_class(client):
    r = client.post(
        "/api/portfolio/positions",
        json={"symbol": "SOLUSDT", "quantity": 3, "avg_cost": 210.0},
    )
    assert r.status_code == 200
    pos = r.json()["position"]
    assert pos["instrument"]["asset_class"] == "CRYPTO"
    assert pos["currency"] == "USDT"


def test_add_position_duplicate_conflict(client):
    # The fixture's legacy mirror already carries 4USDT.
    r = client.post(
        "/api/portfolio/positions",
        json={"symbol": "4USDT", "quantity": 1, "avg_cost": 1.0},
    )
    assert r.status_code == 409
    assert "already exists" in r.json()["detail"]


def test_add_position_rejects_invalid_payload(client):
    bad_symbol = client.post(
        "/api/portfolio/positions",
        json={"symbol": "bad symbol!", "quantity": 1, "avg_cost": 1.0},
    )
    assert bad_symbol.status_code == 400

    missing_symbol = client.post(
        "/api/portfolio/positions", json={"quantity": 1, "avg_cost": 1.0}
    )
    assert missing_symbol.status_code == 400

    negative_qty = client.post(
        "/api/portfolio/positions",
        json={"symbol": "TSLA", "quantity": -1, "avg_cost": 1.0},
    )
    assert negative_qty.status_code == 400
    assert "positive" in negative_qty.json()["detail"]

    nan_cost = client.post(
        "/api/portfolio/positions",
        json={"symbol": "TSLA", "quantity": 1, "avg_cost": "nan"},
    )
    assert nan_cost.status_code == 400
    assert "finite" in nan_cost.json()["detail"]

    bad_class = client.post(
        "/api/portfolio/positions",
        json={"symbol": "TSLA", "quantity": 1, "avg_cost": 1.0, "asset_class": "ALIEN"},
    )
    assert bad_class.status_code == 400
