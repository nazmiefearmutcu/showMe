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
    update = dict(_SPEC)
    update["name"] = "RSI-v2"
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


# ── Agent 2 cascade regression tests (BOT_AUDIT_REPORT.md C-INT-2) ──────


def _seed_credential() -> str:
    """Seed a credential directly so we can build bots referencing it."""
    from showme.brokers import CredentialStore
    store = CredentialStore.fresh()
    rec = store.add(
        exchange_id="binance",
        account_label="main",
        secrets={"apiKey": "k", "secret": "s"},
        permissions=("read", "trade"),
    )
    return rec.id


def _seed_bot(client, strategy_id: str, credential_id: str) -> str:
    """POST a bot referencing the given strategy."""
    r = client.post("/api/bots", json={
        "strategy_id": strategy_id,
        "credential_id": credential_id,
        "exchange_id": "binance",
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "tick_interval_seconds": 900,
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_negative_sizing_rejected_on_create(client):
    """C-API-1 — POST /api/strategies with sizing_value=-50 must 400.

    Catches the negative-sizing repro from BOT_AUDIT_REPORT.md§C-API-1
    that would otherwise reach the live runner.
    """
    bad = dict(_SPEC)
    bad["position"] = {"sizing_kind": "fixed_quote", "sizing_value": -50}
    r = client.post("/api/strategies", json=bad)
    assert r.status_code == 400, r.text
    assert "sizing_value" in r.json()["detail"]


def test_negative_sizing_rejected_on_update(client):
    """C-API-1 — PUT /api/strategies/{id} negative sizing also rejected."""
    r = client.post("/api/strategies", json=_SPEC)
    sid = r.json()["id"]
    bad = dict(_SPEC)
    bad["position"] = {"sizing_kind": "fixed_quote", "sizing_value": -1}
    p = client.put(f"/api/strategies/{sid}", json=bad)
    assert p.status_code == 400, p.text


def test_risk_pct_over_100_rejected(client):
    """C-API-1 — risk_pct sizing must be in (0, 100]."""
    bad = dict(_SPEC)
    bad["position"] = {"sizing_kind": "risk_pct", "sizing_value": 250}
    r = client.post("/api/strategies", json=bad)
    assert r.status_code == 400, r.text


def test_dependents_endpoint_lists_referencing_bots(client, monkeypatch):
    """GET /api/strategies/{id}/dependents returns the bots that reference it."""
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")
    # The strategies-route fixture already resets SHOWME_HOME per-test.
    r = client.post("/api/strategies", json=_SPEC)
    sid = r.json()["id"]
    cid = _seed_credential()
    b1 = _seed_bot(client, sid, cid)
    b2 = _seed_bot(client, sid, cid)

    dep = client.get(f"/api/strategies/{sid}/dependents")
    assert dep.status_code == 200
    body = dep.json()
    assert body["strategy_id"] == sid
    assert body["bot_count"] == 2
    assert set(body["bot_ids"]) == {b1, b2}


def test_dependents_endpoint_invalid_id_returns_400(client):
    r = client.get("/api/strategies/..%2Fetc%2Fpasswd/dependents")
    assert r.status_code in (400, 404)  # FastAPI may pre-decode and 404


def test_delete_returns_409_when_bots_reference(client, monkeypatch):
    """C-INT-2 — DELETE /api/strategies/{id} without force=true must
    refuse with 409 when bots still reference the strategy."""
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")
    r = client.post("/api/strategies", json=_SPEC)
    sid = r.json()["id"]
    cid = _seed_credential()
    bid = _seed_bot(client, sid, cid)

    d = client.delete(f"/api/strategies/{sid}")
    assert d.status_code == 409, d.text
    body = d.json()
    assert body["detail"]["error"] == "strategy_has_bots"
    assert body["detail"]["bot_count"] == 1
    assert bid in body["detail"]["bot_ids"]
    # Strategy MUST still exist on disk.
    g = client.get(f"/api/strategies/{sid}")
    assert g.status_code == 200


def test_delete_force_cascade_disables_bots(client, monkeypatch):
    """C-INT-2 — DELETE ?force=true cascade-disables referencing bots,
    then removes the strategy."""
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")
    r = client.post("/api/strategies", json=_SPEC)
    sid = r.json()["id"]
    cid = _seed_credential()
    bid = _seed_bot(client, sid, cid)

    d = client.delete(f"/api/strategies/{sid}?force=true")
    assert d.status_code == 200, d.text
    body = d.json()
    assert body["ok"] is True
    assert body["bots_affected"] == 1
    assert any(c.get("bot_id") == bid for c in body["cascade"])
    # Strategy file removed.
    g = client.get(f"/api/strategies/{sid}")
    assert g.status_code == 404
    # Bot still exists (only disabled).
    bg = client.get(f"/api/bots/{bid}")
    assert bg.status_code == 200
    assert bg.json()["enabled"] is False


def test_delete_no_dependents_passes_without_force(client):
    """Sanity: no bots → DELETE succeeds without force=true."""
    r = client.post("/api/strategies", json=_SPEC)
    sid = r.json()["id"]
    d = client.delete(f"/api/strategies/{sid}")
    assert d.status_code == 200
    assert d.json()["ok"] is True
    assert d.json()["bots_affected"] == 0
