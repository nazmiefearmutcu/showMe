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


def test_strategy_from_text_catalog_invalid_not_persisted(client, monkeypatch):
    """B6 — a spec referencing a non-catalog indicator returns a
    ``katalog doğrulaması`` note, ``saved_id is None``, and is NOT persisted
    (even with save=True). The keyword parser cannot emit a bogus indicator,
    so we monkeypatch ``parse_request`` to exercise the validation path."""
    bogus_spec = {
        "name": "bogus",
        "timeframe": "1h",
        "indicators": [{"alias": "x1", "id": "not_a_real_indicator", "params": {}}],
        "entry_rules": [{"kind": "greater_than", "left": "close", "right": "x1"}],
        "exit_rules": [],
        "position": {"side": "long", "sizing_kind": "fixed_quote",
                     "sizing_value": 100, "stop_loss_pct": 2.0},
    }

    def fake_parse(text):
        return bogus_spec, ["Tanınan indikatör: not_a_real_indicator"]

    import showme.assistant.parser as parser_mod
    monkeypatch.setattr(parser_mod, "parse_request", fake_parse)

    before = client.get("/api/strategies").json()["records"]
    r = client.post("/api/assistant/strategy-from-text",
                    json={"text": "anything", "save": True})
    assert r.status_code == 200
    body = r.json()
    assert body["saved_id"] is None
    assert any("katalog doğrulaması" in n for n in body["notes"])
    # Not persisted despite save=True.
    after = client.get("/api/strategies").json()["records"]
    assert len(after) == len(before)


def test_strategy_from_text_empty_catalog_skips_validation(client, monkeypatch):
    """P2-1 — when the indicator catalog cannot be loaded,
    ``_indicator_catalog_ids`` returns an EMPTY set. The route MUST treat
    that as "catalog unavailable → skip validation", NOT validate against an
    empty set (which rejects every indicator). A valid MACD strategy with
    save=True must still be saved, with NO ``katalog doğrulaması`` note."""
    import showme.server_routes.assistant as assistant_mod
    monkeypatch.setattr(assistant_mod, "_indicator_catalog_ids", lambda: set())

    before = client.get("/api/strategies").json()["records"]
    r = client.post("/api/assistant/strategy-from-text",
                    json={"text": "MACD strategy", "save": True})
    assert r.status_code == 200
    body = r.json()
    # Validation skipped, not failed-for-all → strategy IS saved.
    assert body["saved_id"] is not None
    assert not any("katalog doğrulaması" in n for n in body["notes"])
    # Actually persisted.
    after = client.get("/api/strategies").json()["records"]
    ids = {rec["id"] for rec in after}
    assert body["saved_id"] in ids
    assert len(after) == len(before) + 1


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
