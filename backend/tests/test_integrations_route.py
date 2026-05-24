"""FastAPI route tests for /api/integrations/*."""
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
    from showme.integrations import github as gh, hf as hf
    gh._CACHE.clear()
    hf._HF_CACHE.clear()
    hf._PIPELINE = None
    app = build_app(engine_root=None)
    return TestClient(app, headers={"X-ShowMe-Token": "test-token"})


def test_github_search_rejects_empty_q(client):
    r = client.get("/api/integrations/github/search?q=")
    assert r.status_code == 400


def test_github_search_returns_hits(client, monkeypatch):
    from showme.integrations.github import CodeHit
    async def _fake(q, language=None, limit=10):
        return [CodeHit(repo="a/b", path="x.py", url="u", snippet="s", score=1.0)]
    monkeypatch.setattr("showme.integrations.github.search_code", _fake)
    r = client.get("/api/integrations/github/search?q=rsi&language=python&limit=5")
    assert r.status_code == 200
    body = r.json()
    assert body["q"] == "rsi"
    assert len(body["hits"]) == 1
    assert body["hits"][0]["repo"] == "a/b"


def test_hf_classify_rejects_empty_text(client):
    r = client.post("/api/integrations/hf/classify", json={"text": ""})
    assert r.status_code == 400
    r = client.post("/api/integrations/hf/classify", json={})
    assert r.status_code == 400


def test_hf_classify_returns_unknown_when_model_unavailable(client, monkeypatch):
    import showme.integrations.hf as hf_mod
    monkeypatch.setattr(hf_mod, "_get_pipeline", lambda: None)
    r = client.post("/api/integrations/hf/classify", json={"text": "hello"})
    assert r.status_code == 200
    assert r.json()["label"] == "unknown"


def test_hf_explain_with_inline_spec(client):
    spec = {"name": "X", "timeframe": "1h",
            "indicators": [], "entry_rules": [], "exit_rules": [], "position": {}}
    r = client.post("/api/integrations/hf/explain", json={"spec": spec})
    assert r.status_code == 200
    assert "X" in r.json()["explanation"]


def test_hf_explain_strategy_id_404(client):
    r = client.post("/api/integrations/hf/explain", json={"strategy_id": "missing"})
    assert r.status_code == 404


def test_hf_explain_strategy_id_path(client):
    # Save a strategy then explain by id:
    spec_body = {
        "name": "RSI-revert",
        "indicators": [{"alias": "rsi14", "id": "rsi", "params": {"period": 14}}],
        "entry_rules": [{"kind": "crosses_below", "left": "rsi14", "right": "literal:30"}],
        "exit_rules": [{"kind": "crosses_above", "left": "rsi14", "right": "literal:70"}],
    }
    create_r = client.post("/api/strategies", json=spec_body)
    sid = create_r.json()["id"]
    r = client.post("/api/integrations/hf/explain", json={"strategy_id": sid})
    assert r.status_code == 200
    assert "RSI-revert" in r.json()["explanation"]


def test_hf_explain_requires_spec_or_id(client):
    r = client.post("/api/integrations/hf/explain", json={})
    assert r.status_code == 400
