"""Route contract for the KAOS multibot delegate (POST/PUT validation,
status payload venue rows, templates instantiate engine keys)."""
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
    # /api/templates/* is dev-only (mounted only when SHOWME_DEV is truthy).
    monkeypatch.setenv("SHOWME_DEV", "1")
    from showme.brokers import factory as factory_mod
    factory_mod._DYNAMIC.clear()
    factory_mod._LIVE.clear()
    for name in list(factory_mod._REGISTRY.keys()):
        if ":" in name:
            factory_mod._REGISTRY.pop(name, None)
    import showme.server_routes.templates as tmod
    from showme.bots import lifespan
    lifespan._RUNNER = None
    tmod._CATALOG = None
    app = build_app(engine_root=None)
    return TestClient(app, headers={"X-ShowMe-Token": "test-token"})


def _seed_strategy(client) -> str:
    r = client.post("/api/strategies", json={
        "name": "kaos sizing host",
        "indicators": [],
        "entry_rules": [],
        "exit_rules": [],
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _seed_credential(exchange_id: str = "binance") -> str:
    from showme.brokers import CredentialStore
    rec = CredentialStore.fresh().add(
        exchange_id=exchange_id,
        account_label="main",
        secrets={"apiKey": "k", "secret": "s"},
        permissions=("read", "trade"),
    )
    return rec.id


def _kaos_body(client, **overrides) -> dict:
    body = {
        "strategy_id": _seed_strategy(client),
        "credential_id": _seed_credential(),
        "exchange_id": "binanceusdm",
        "symbol": "BTC/USDT",
        "engine": "kaos",
        "timeframe": "15m",
        "tick_interval_seconds": 60,
        "venues": [
            {"id": "crypto", "exchange_id": "binanceusdm",
             "market": "crypto-futures", "symbols": ["BTC/USDT:USDT"],
             "risk_profile": "crypto"},
            {"id": "nasdaq", "exchange_id": "alpaca",
             "market": "us-equities", "symbols": ["AAPL"],
             "risk_profile": "equity"},
        ],
    }
    body.update(overrides)
    return body


# ---- POST ------------------------------------------------------------------


def test_post_accepts_valid_kaos_bot(client):
    r = client.post("/api/bots", json=_kaos_body(client))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["engine"] == "kaos"
    assert [v["id"] for v in d["venues"]] == ["crypto", "nasdaq"]
    assert d["mode"] == "shadow"  # forced on create


def test_post_rejects_unknown_engine(client):
    body = _kaos_body(client, engine="gpt")
    r = client.post("/api/bots", json=body)
    assert r.status_code == 400
    assert "invalid engine" in r.json()["detail"]


def test_post_rejects_kaos_without_venues(client):
    body = _kaos_body(client, venues=[])
    r = client.post("/api/bots", json=body)
    assert r.status_code == 400
    assert "at least one venue" in r.json()["detail"]


def test_post_rejects_venue_exchange_not_in_catalog(client):
    body = _kaos_body(client)
    body["venues"][0]["exchange_id"] = "not-an-exchange"
    r = client.post("/api/bots", json=body)
    assert r.status_code == 400
    assert "not in catalog" in r.json()["detail"]


def test_post_rejects_bad_venue_market_and_symbols(client):
    body = _kaos_body(client)
    body["venues"][0]["market"] = "lse"
    assert client.post("/api/bots", json=body).status_code == 400
    body = _kaos_body(client)
    body["venues"][1]["symbols"] = []
    assert client.post("/api/bots", json=body).status_code == 400
    body = _kaos_body(client)
    body["venues"][1]["risk_profile"] = "crypto"  # mismatch with us-equities
    assert client.post("/api/bots", json=body).status_code == 400


def test_post_without_engine_defaults_to_spec(client):
    body = _kaos_body(client)
    body.pop("engine")
    body.pop("venues")
    r = client.post("/api/bots", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["engine"] == "spec"


# ---- PUT (equities live gate) -----------------------------------------------


def _create_bot(client) -> str:
    r = client.post("/api/bots", json=_kaos_body(client))
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _full_body(client, bot_id: str, **overrides) -> dict:
    """Full PUT body: the stored record minus server-owned fields."""
    d = client.get(f"/api/bots/{bot_id}").json()
    for k in ("id", "created_at", "updated_at", "signal_log",
              "last_processed_event", "closed_trades_log", "enabled",
              "engine", "venues"):
        d.pop(k, None)
    d.update(overrides)
    return d


def test_put_equities_live_requires_real_alpaca_credential(client):
    bot_id = _create_bot(client)
    # crypto credential + equities venue + live request → 400
    r = client.put(f"/api/bots/{bot_id}",
                   json=_full_body(client, bot_id, mode="live"))
    assert r.status_code == 400, r.text
    assert "Alpaca credential" in r.json()["detail"]


def test_put_shadow_default_unchanged(client):
    bot_id = _create_bot(client)
    r = client.put(f"/api/bots/{bot_id}",
                   json=_full_body(client, bot_id, mode="shadow"))
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "shadow"


def test_put_engine_validation_still_applies_on_update(client):
    bot_id = _create_bot(client)
    r = client.put(f"/api/bots/{bot_id}",
                   json=_full_body(client, bot_id, engine="yolo"))
    assert r.status_code == 400
    assert "invalid engine" in r.json()["detail"]


# ---- status payload ----------------------------------------------------------


def test_get_bot_status_includes_venue_rows(client):
    bot_id = _create_bot(client)
    d = client.get(f"/api/bots/{bot_id}").json()
    assert d["engine"] == "kaos"
    rows = d["venue_rows"]
    assert [r["venue_id"] for r in rows] == ["crypto", "nasdaq"]
    for row in rows:
        assert set(row) == {
            "venue_id", "market", "bars_age", "last_eval", "decisions",
            "lane_status",
        }
        assert row["lane_status"] == "idle"  # runner never ticked
        assert row["bars_age"] is None


def test_get_bot_spec_has_no_venue_rows(client):
    body = _kaos_body(client)
    body.pop("engine")
    body.pop("venues")
    bot_id = client.post("/api/bots", json=body).json()["id"]
    d = client.get(f"/api/bots/{bot_id}").json()
    assert "venue_rows" not in d


def test_list_bots_includes_engine(client):
    bot_id = _create_bot(client)
    recs = client.get("/api/bots").json()["records"]
    mine = next(r for r in recs if r["id"] == bot_id)
    assert mine["engine"] == "kaos"


# ---- templates instantiate carries engine + venues ---------------------------


def test_template_instantiate_returns_engine_and_venues(client):
    r = client.post("/api/templates/kaos-multibot/instantiate", json={})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["engine"] == "kaos"
    assert [v["id"] for v in d["venues"]] == ["crypto", "nasdaq"]
    assert d["strategy"]["name"] == "KAOS Multibot"
    # a spec template still answers the legacy shape
    r2 = client.post("/api/templates/rsi-mean-revert/instantiate", json={})
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["engine"] == "spec"
    assert d2["venues"] == []
