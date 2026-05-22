"""FastAPI route tests for /api/indicators/*."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from showme.server import build_app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.setenv("SHOWME_AUTH_TOKEN", "test-token")
    # Reset module singleton so each test gets a fresh load:
    import showme.server_routes.indicators as ind_mod
    ind_mod._CATALOG = None
    app = build_app(engine_root=None)
    return TestClient(app, headers={"X-ShowMe-Token": "test-token"})


def test_catalog_returns_at_least_15(client):
    r = client.get("/api/indicators/catalog")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) >= 15
    ids = {e["id"] for e in body}
    assert {"rsi", "macd", "ema", "sma", "bollinger_bands"}.issubset(ids)


def test_detail_returns_one_entry(client):
    r = client.get("/api/indicators/rsi")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "rsi"
    assert body["family"] == "momentum"
    assert body["confidence"] == 9
    assert isinstance(body["parameters"], list)


def test_detail_unknown_404(client):
    r = client.get("/api/indicators/not-an-indicator")
    assert r.status_code == 404
    assert "not-an-indicator" in r.json()["detail"]
