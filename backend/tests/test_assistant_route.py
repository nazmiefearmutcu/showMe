"""POST /api/assistant/* route tests."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from showme.server import build_app


@pytest.fixture
def client(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.setenv("SHOWME_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")
    import showme.bots.lifespan as lifespan
    lifespan._RUNNER = None
    app = build_app(engine_root=None)
    return TestClient(app, headers={"X-ShowMe-Token": "test-token"})


def test_strategy_from_text_rejects_empty(client):
    r = client.post("/api/assistant/strategy-from-text", json={"text": ""})
    assert r.status_code == 400


def test_strategy_from_text_returns_spec(client):
    r = client.post("/api/assistant/strategy-from-text",
                    json={"text": "RSI 30 altında al, 70 üstünde sat"})
    assert r.status_code == 200
    body = r.json()
    assert body["spec"] is not None
    assert body["spec"]["indicators"][0]["id"] == "rsi"
    assert body["saved_id"] is None
    assert len(body["notes"]) > 0


def test_strategy_from_text_save_persists(client):
    r = client.post("/api/assistant/strategy-from-text",
                    json={"text": "MACD strategy", "save": True})
    assert r.status_code == 200
    body = r.json()
    assert body["saved_id"] is not None
    # Should appear in /api/strategies:
    lr = client.get("/api/strategies")
    ids = {rec["id"] for rec in lr.json()["records"]}
    assert body["saved_id"] in ids


def test_strategy_from_text_unknown_indicator(client):
    r = client.post("/api/assistant/strategy-from-text",
                    json={"text": "gibberish text without indicators"})
    assert r.status_code == 200
    body = r.json()
    assert body["spec"] is None
    assert body["saved_id"] is None
    assert len(body["notes"]) > 0


def test_explain_requires_strategy_id(client):
    r = client.post("/api/assistant/explain-strategy", json={})
    assert r.status_code == 400


def test_explain_404_on_unknown(client):
    r = client.post("/api/assistant/explain-strategy", json={"strategy_id": "missing"})
    assert r.status_code == 404


def test_explain_real_strategy(client):
    create = client.post("/api/strategies", json={
        "name": "RSI test",
        "indicators": [{"alias": "rsi14", "id": "rsi", "params": {"period": 14}}],
        "entry_rules": [{"kind": "crosses_below", "left": "rsi14", "right": "literal:30"}],
        "exit_rules": [{"kind": "crosses_above", "left": "rsi14", "right": "literal:70"}],
    })
    sid = create.json()["id"]
    r = client.post("/api/assistant/explain-strategy", json={"strategy_id": sid})
    assert r.status_code == 200
    assert "RSI test" in r.json()["explanation"]
