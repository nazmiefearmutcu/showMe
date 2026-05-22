"""FastAPI route tests for /api/strategies/*."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from showme.server import build_app


_SPEC = {
    "name": "RSI-revert",
    "indicators": [{"alias": "rsi14", "id": "rsi", "params": {"period": 14}}],
    "entry_rules": [{"kind": "crosses_below", "left": "rsi14", "right": "literal:30"}],
    "exit_rules": [{"kind": "crosses_above", "left": "rsi14", "right": "literal:70"}],
    "exit_logic": "any",
}


@pytest.fixture
def client(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.setenv("SHOWME_AUTH_TOKEN", "test-token")
    app = build_app(engine_root=None)
    return TestClient(app, headers={"X-ShowMe-Token": "test-token"})


def test_list_starts_empty(client):
    r = client.get("/api/strategies")
    assert r.status_code == 200
    assert r.json() == {"records": []}


def test_post_creates_and_get_round_trip(client):
    r = client.post("/api/strategies", json=_SPEC)
    assert r.status_code == 200, r.text
    body = r.json()
    sid = body["id"]
    assert body["name"] == "RSI-revert"
    g = client.get(f"/api/strategies/{sid}")
    assert g.status_code == 200
    assert g.json()["id"] == sid


def test_post_rejects_unknown_indicator(client):
    bad = dict(_SPEC)
    bad["indicators"] = [{"alias": "x", "id": "not-real-indicator"}]
    r = client.post("/api/strategies", json=bad)
    assert r.status_code == 400


def test_put_preserves_created_at(client):
    r = client.post("/api/strategies", json=_SPEC)
    sid = r.json()["id"]
    original_created = r.json()["created_at"]
    update = dict(_SPEC); update["name"] = "RSI-v2"
    p = client.put(f"/api/strategies/{sid}", json=update)
    assert p.status_code == 200, p.text
    assert p.json()["created_at"] == original_created
    assert p.json()["name"] == "RSI-v2"


def test_delete_round_trip(client):
    r = client.post("/api/strategies", json=_SPEC)
    sid = r.json()["id"]
    d = client.delete(f"/api/strategies/{sid}")
    assert d.status_code == 200
    g = client.get(f"/api/strategies/{sid}")
    assert g.status_code == 404


def test_preview_returns_events(client):
    r = client.post("/api/strategies", json=_SPEC)
    sid = r.json()["id"]
    p = client.post(f"/api/strategies/{sid}/preview?limit=200")
    assert p.status_code == 200, p.text
    body = p.json()
    assert body["strategy_id"] == sid
    assert body["bars"] == 200
    assert isinstance(body["events"], list)
    assert body["source"] == "synthetic_random_walk"


def test_preview_unknown_404(client):
    p = client.post("/api/strategies/no-such-id/preview")
    assert p.status_code == 404
