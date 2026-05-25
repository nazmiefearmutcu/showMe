"""Faz 2 — Route layer validation regression tests.

Covers:

* S5  — POST/PUT /api/bots reject unknown strategy_id / credential_id / exchange_id
        with 400 instead of silently persisting orphan bots.
* H-6 — PUT /api/bots/{id} with credential change while in live mode
        re-runs the trade-perm + confirm_account_label gate. Pre-fix it
        skipped the check whenever the bot was already live.
* M-1 — POST/PUT /api/bots reject ``mode="yolo"`` with 400 instead of
        silently coercing to "shadow".
* S9  — POST /api/strategies/{id}/preview rejects ``limit=-5`` and
        ``limit=99999`` with 422.
* S10 — POST /api/assistant/strategy-from-text type-guards the ``text``
        field so ``42``, ``None``, ``[]`` etc. yield 400 not 500.
* M-3 — POST/PUT /api/strategies refuses ``indicators=[...x1000]`` with 400.
* H-19 — /api/templates returns 500 with informative detail when the
        catalog YAML cannot be loaded.

We DO NOT modify any existing test file. Each test in this module
seeds its own FK fixtures so the FK validation introduced for S5
does not interfere.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from showme.server import build_app


# ─── Helpers ─────────────────────────────────────────────────────────────


_STRATEGY_BODY = {
    "name": "RSI mean revert (test fixture)",
    "indicators": [{"alias": "rsi14", "id": "rsi", "params": {"period": 14}}],
    "entry_rules": [{"kind": "crosses_below", "left": "rsi14", "right": "literal:30"}],
    "exit_rules": [{"kind": "crosses_above", "left": "rsi14", "right": "literal:70"}],
    "exit_logic": "any",
}


@pytest.fixture
def client(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.setenv("SHOWME_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")
    # 2026-05-24 rebuild: /api/templates/* is dev-only — this test suite
    # touches the template route in 3 cases, so force the gate on.
    monkeypatch.setenv("SHOWME_DEV", "1")
    # Reset factory state — tests below register their own credential.
    from showme.brokers import factory as factory_mod
    factory_mod._DYNAMIC.clear()
    factory_mod._LIVE.clear()
    for name in list(factory_mod._REGISTRY.keys()):
        if ":" in name:
            factory_mod._REGISTRY.pop(name, None)
    # Reset bot lifespan singleton.
    import showme.bots.lifespan as lifespan
    lifespan._RUNNER = None
    # Reset template catalog cache (other tests may have cached it).
    import showme.server_routes.templates as tmod
    tmod._CATALOG = None
    tmod._CATALOG_ERROR = None
    app = build_app(engine_root=None)
    return TestClient(app, headers={"X-ShowMe-Token": "test-token"})


def _seed_strategy(client) -> str:
    """Create a real strategy via the API and return its id."""
    r = client.post("/api/strategies", json=_STRATEGY_BODY)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _seed_credential(read_only: bool = False) -> str:
    """Add a real credential directly to the vault (skipping the
    /api/exchange/credentials route so we don't need a live broker
    auth test). Returns the credential id."""
    from showme.brokers import CredentialStore
    store = CredentialStore.fresh()
    perms: tuple[str, ...] = ("read",) if read_only else ("read", "trade")
    rec = store.add(
        exchange_id="binance",
        account_label="main",
        secrets={"apiKey": "k", "secret": "s"},
        permissions=perms,
    )
    return rec.id


# ─── S5 — FK validation on POST /api/bots ────────────────────────────────


def test_fk_validation_post_rejects_unknown_strategy(client):
    cid = _seed_credential()
    r = client.post("/api/bots", json={
        "strategy_id": "ghost",
        "credential_id": cid,
        "exchange_id": "binance",
        "symbol": "BTC/USDT",
    })
    assert r.status_code == 400, r.text
    assert "strategy_id" in r.json()["detail"]


def test_fk_validation_post_rejects_unknown_credential(client):
    sid = _seed_strategy(client)
    r = client.post("/api/bots", json={
        "strategy_id": sid,
        "credential_id": "ghost",
        "exchange_id": "binance",
        "symbol": "BTC/USDT",
    })
    assert r.status_code == 400, r.text
    assert "credential_id" in r.json()["detail"]


def test_fk_validation_post_rejects_unknown_exchange(client):
    sid = _seed_strategy(client)
    cid = _seed_credential()
    r = client.post("/api/bots", json={
        "strategy_id": sid,
        "credential_id": cid,
        "exchange_id": "totally-not-a-real-exchange-zzz",
        "symbol": "BTC/USDT",
    })
    assert r.status_code == 400, r.text
    assert "exchange_id" in r.json()["detail"]


def test_fk_validation_post_accepts_valid_combo(client):
    sid = _seed_strategy(client)
    cid = _seed_credential()
    r = client.post("/api/bots", json={
        "strategy_id": sid,
        "credential_id": cid,
        "exchange_id": "binance",
        "symbol": "BTC/USDT",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["strategy_id"] == sid
    assert body["credential_id"] == cid


@pytest.mark.parametrize("field", ["strategy_id", "credential_id", "exchange_id"])
def test_fk_validation_post_rejects_empty_string(client, field):
    sid = _seed_strategy(client)
    cid = _seed_credential()
    body = {
        "strategy_id": sid,
        "credential_id": cid,
        "exchange_id": "binance",
        "symbol": "BTC/USDT",
    }
    body[field] = ""
    r = client.post("/api/bots", json=body)
    assert r.status_code == 400, r.text


def test_fk_validation_post_rejects_missing_field(client):
    """If the client omits strategy_id entirely the route still 400s
    rather than letting pydantic raise a 500-flavoured error."""
    cid = _seed_credential()
    r = client.post("/api/bots", json={
        "credential_id": cid,
        "exchange_id": "binance",
        "symbol": "BTC/USDT",
    })
    assert r.status_code == 400


# ─── S5 — FK validation on PUT /api/bots/{id} ────────────────────────────


def _create_real_bot(client) -> tuple[str, str, str]:
    sid = _seed_strategy(client)
    cid = _seed_credential()
    r = client.post("/api/bots", json={
        "strategy_id": sid,
        "credential_id": cid,
        "exchange_id": "binance",
        "symbol": "BTC/USDT",
    })
    assert r.status_code == 200, r.text
    return r.json()["id"], sid, cid


def test_fk_validation_put_rejects_unknown_strategy(client):
    bid, _, cid = _create_real_bot(client)
    r = client.put(f"/api/bots/{bid}", json={
        "strategy_id": "ghost",
        "credential_id": cid,
        "exchange_id": "binance",
        "symbol": "BTC/USDT",
    })
    assert r.status_code == 400


def test_fk_validation_put_rejects_empty_strategy(client):
    bid, _, cid = _create_real_bot(client)
    r = client.put(f"/api/bots/{bid}", json={
        "strategy_id": "",
        "credential_id": cid,
        "exchange_id": "binance",
        "symbol": "BTC/USDT",
    })
    assert r.status_code == 400


# ─── H-6 — Live-mode credential swap re-checks trade permission ─────────


def test_live_mode_credential_swap_rerequires_trade_perm(client):
    """Pre-fix bug: an already-live bot could swap to a credential
    without 'trade' permission and the route happily 200'd because of
    the ``existing.mode != "live"`` short-circuit."""
    sid = _seed_strategy(client)
    cid_trade = _seed_credential()  # has read+trade
    # Create + escalate to live with the trade-perm credential.
    r = client.post("/api/bots", json={
        "strategy_id": sid,
        "credential_id": cid_trade,
        "exchange_id": "binance",
        "symbol": "BTC/USDT",
    })
    bid = r.json()["id"]
    # Transition to live (must pass through the legit gate).
    live = client.put(f"/api/bots/{bid}", json={
        "strategy_id": sid,
        "credential_id": cid_trade,
        "exchange_id": "binance",
        "symbol": "BTC/USDT",
        "mode": "live",
        "confirm_account_label": "main",
    })
    assert live.status_code == 200, live.text
    # Now plant a *read-only* credential and try to swap.
    cid_readonly = _seed_credential(read_only=True)
    bad = client.put(f"/api/bots/{bid}", json={
        "strategy_id": sid,
        "credential_id": cid_readonly,
        "exchange_id": "binance",
        "symbol": "BTC/USDT",
        "mode": "live",
        "confirm_account_label": "main",
    })
    assert bad.status_code == 400, bad.text
    assert "trade" in bad.json()["detail"]


def test_live_mode_credential_swap_still_requires_confirm_label(client):
    """Live → live swap with a fresh credential requires the caller to
    re-affirm the account label (matches the new credential's label)."""
    sid = _seed_strategy(client)
    cid_a = _seed_credential()
    r = client.post("/api/bots", json={
        "strategy_id": sid,
        "credential_id": cid_a,
        "exchange_id": "binance",
        "symbol": "BTC/USDT",
    })
    bid = r.json()["id"]
    live = client.put(f"/api/bots/{bid}", json={
        "strategy_id": sid,
        "credential_id": cid_a,
        "exchange_id": "binance",
        "symbol": "BTC/USDT",
        "mode": "live",
        "confirm_account_label": "main",
    })
    assert live.status_code == 200
    # Add a second credential with a different label.
    from showme.brokers import CredentialStore
    rec = CredentialStore.fresh().add(
        exchange_id="binance",
        account_label="second-account",
        secrets={"apiKey": "k", "secret": "s"},
        permissions=("read", "trade"),
    )
    cid_b = rec.id
    # Swap to it but DON'T re-affirm — the wrong label is "main".
    bad = client.put(f"/api/bots/{bid}", json={
        "strategy_id": sid,
        "credential_id": cid_b,
        "exchange_id": "binance",
        "symbol": "BTC/USDT",
        "mode": "live",
        "confirm_account_label": "main",
    })
    assert bad.status_code == 400
    assert "confirm_account_label" in bad.json()["detail"]
    # Correct label → 200.
    good = client.put(f"/api/bots/{bid}", json={
        "strategy_id": sid,
        "credential_id": cid_b,
        "exchange_id": "binance",
        "symbol": "BTC/USDT",
        "mode": "live",
        "confirm_account_label": "second-account",
    })
    assert good.status_code == 200, good.text


# ─── M-1 — mode allowlist ────────────────────────────────────────────────


def test_post_rejects_yolo_mode(client):
    sid = _seed_strategy(client)
    cid = _seed_credential()
    r = client.post("/api/bots", json={
        "strategy_id": sid,
        "credential_id": cid,
        "exchange_id": "binance",
        "symbol": "BTC/USDT",
        "mode": "yolo",
    })
    assert r.status_code == 400, r.text
    assert "mode" in r.json()["detail"].lower()


def test_put_rejects_unknown_mode(client):
    bid, sid, cid = _create_real_bot(client)
    r = client.put(f"/api/bots/{bid}", json={
        "strategy_id": sid,
        "credential_id": cid,
        "exchange_id": "binance",
        "symbol": "BTC/USDT",
        "mode": "yolo",
    })
    assert r.status_code == 400


# ─── S9 — preview limit bounds ───────────────────────────────────────────


def test_preview_rejects_negative_limit(client):
    sid = _seed_strategy(client)
    r = client.post(f"/api/strategies/{sid}/preview?limit=-5")
    # FastAPI Query(ge=1, ...) emits 422 by convention.
    assert r.status_code == 422, r.text


def test_preview_rejects_zero_limit(client):
    sid = _seed_strategy(client)
    r = client.post(f"/api/strategies/{sid}/preview?limit=0")
    assert r.status_code == 422


def test_preview_rejects_over_max_limit(client):
    sid = _seed_strategy(client)
    r = client.post(f"/api/strategies/{sid}/preview?limit=99999")
    assert r.status_code == 422


def test_preview_accepts_max_limit(client):
    sid = _seed_strategy(client)
    r = client.post(f"/api/strategies/{sid}/preview?limit=10000")
    assert r.status_code == 200
    assert r.json()["bars"] == 10000


def test_preview_default_limit_works(client):
    sid = _seed_strategy(client)
    r = client.post(f"/api/strategies/{sid}/preview")
    assert r.status_code == 200
    assert r.json()["bars"] == 200


# ─── S10 — assistant text type guard ─────────────────────────────────────


@pytest.mark.parametrize("bad_value", [42, 3.14, [], {}, True, False])
def test_assistant_text_rejects_non_string(client, bad_value):
    r = client.post("/api/assistant/strategy-from-text", json={"text": bad_value})
    assert r.status_code == 400, r.text
    assert "string" in r.json()["detail"].lower()


def test_assistant_text_rejects_null(client):
    r = client.post("/api/assistant/strategy-from-text", json={"text": None})
    assert r.status_code == 400


def test_assistant_text_rejects_empty(client):
    r = client.post("/api/assistant/strategy-from-text", json={"text": ""})
    assert r.status_code == 400


def test_assistant_text_rejects_whitespace_only(client):
    r = client.post("/api/assistant/strategy-from-text", json={"text": "   \t\n  "})
    assert r.status_code == 400


def test_assistant_text_accepts_valid_string(client):
    r = client.post(
        "/api/assistant/strategy-from-text",
        json={"text": "RSI 30 altında al, 70 üstünde sat"},
    )
    assert r.status_code == 200
    assert r.json()["spec"] is not None


# ─── M-3 — indicator array DoS guard ─────────────────────────────────────


def test_strategy_indicator_array_dos_blocked(client):
    big_indicators = [
        {"alias": f"x{i}", "id": "rsi", "params": {"period": 14}}
        for i in range(1000)
    ]
    bad = dict(_STRATEGY_BODY, indicators=big_indicators)
    r = client.post("/api/strategies", json=bad)
    assert r.status_code == 400, r.text
    assert "too many" in r.json()["detail"].lower()


def test_strategy_indicator_array_at_cap_accepted(client):
    # 64 is the configured cap; 64 unique aliases mapping to a real id.
    indicators = [
        {"alias": f"rsi{i:02d}", "id": "rsi", "params": {"period": 14}}
        for i in range(64)
    ]
    rules = [
        {"kind": "crosses_below", "left": "rsi00", "right": "literal:30"},
    ]
    spec = {
        "name": "Big spec",
        "indicators": indicators,
        "entry_rules": rules,
        "exit_rules": [
            {"kind": "crosses_above", "left": "rsi00", "right": "literal:70"},
        ],
        "exit_logic": "any",
    }
    r = client.post("/api/strategies", json=spec)
    assert r.status_code == 200, r.text


# ─── H-19 — templates catalog load failure surfaces as 500 ───────────────


def test_templates_list_surfaces_yaml_error(client, monkeypatch):
    """Force ``load_template_catalog`` to raise. Endpoint must answer
    500 with informative ``detail`` instead of returning an empty list."""
    import showme.server_routes.templates as tmod
    # Pre-clear cached state for this client (the fixture already does
    # this but tests in this file may have populated the cache by now).
    tmod._CATALOG = None
    tmod._CATALOG_ERROR = None

    def broken_loader(_path):
        raise RuntimeError("manufactured load failure")

    # Patch the loader symbol the route imports from inside _get_catalog.
    monkeypatch.setattr(
        "showme.templates.loader.load_template_catalog",
        broken_loader,
    )
    r = client.get("/api/templates")
    assert r.status_code == 500
    detail = r.json()["detail"]
    assert "template catalog failed to load" in detail
    assert "manufactured load failure" in detail


def test_templates_detail_surfaces_yaml_error(client, monkeypatch):
    import showme.server_routes.templates as tmod
    tmod._CATALOG = None
    tmod._CATALOG_ERROR = None

    def broken_loader(_path):
        raise RuntimeError("manufactured load failure")

    monkeypatch.setattr(
        "showme.templates.loader.load_template_catalog",
        broken_loader,
    )
    r = client.get("/api/templates/rsi-mean-revert")
    assert r.status_code == 500


def test_templates_list_happy_path_unchanged(client):
    """Sanity: when the catalog DOES load (default case), behavior is
    unchanged — still returns a non-empty list."""
    r = client.get("/api/templates")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) >= 12


# ─── Payload type sanity (defensive) ─────────────────────────────────────


def test_post_bot_rejects_non_dict_payload(client):
    """FastAPI usually rejects non-dict JSON at the parameter binding
    layer, but we have an inner guard too; either path must yield 4xx."""
    r = client.post("/api/bots", json="not-a-dict")
    assert 400 <= r.status_code < 500


def test_post_strategy_rejects_non_dict_payload(client):
    r = client.post("/api/strategies", json="not-a-dict")
    assert 400 <= r.status_code < 500
