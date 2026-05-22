"""FastAPI route tests for /api/templates/*."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from showme.server import build_app


@pytest.fixture
def client(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.setenv("SHOWME_AUTH_TOKEN", "test-token")
    # Reset singleton
    import showme.server_routes.templates as tmod
    tmod._CATALOG = None
    app = build_app(engine_root=None)
    return TestClient(app, headers={"X-ShowMe-Token": "test-token"})


def test_list_returns_12(client):
    r = client.get("/api/templates")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) >= 12
    ids = {e["id"] for e in body}
    assert {"rsi-mean-revert", "macd-cross", "ema-crossover", "golden-cross"}.issubset(ids)


def test_detail_returns_entry(client):
    r = client.get("/api/templates/rsi-mean-revert")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "rsi-mean-revert"
    assert body["uses_indicators"] == ["rsi"]
    assert "spec_template" in body


def test_detail_unknown_404(client):
    r = client.get("/api/templates/not-real")
    assert r.status_code == 404


def test_instantiate_creates_strategy(client):
    r = client.post("/api/templates/rsi-mean-revert/instantiate",
                    json={"name": "My RSI", "symbol": "ETH/USDT"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["template_id"] == "rsi-mean-revert"
    spec = body["strategy"]
    assert spec["name"] == "My RSI"
    assert spec["asset_filter"]["symbols"] == ["ETH/USDT"]
    # Now confirm it persisted:
    listed = client.get("/api/strategies").json()
    ids = {r["id"] for r in listed["records"]}
    assert spec["id"] in ids


def test_instantiate_unknown_404(client):
    r = client.post("/api/templates/not-real/instantiate", json={})
    assert r.status_code == 404


def test_instantiate_default_name_used_when_no_override(client):
    r = client.post("/api/templates/macd-cross/instantiate", json={})
    assert r.status_code == 200, r.text
    spec = r.json()["strategy"]
    assert spec["name"] == "MACD Crossover"  # template's default name
