"""Faz 2 / S7 — Path-traversal regression tests for bot/strategy ids.

The audit found that ``store._path(bot_id)`` happily resolved
``../../etc/passwd`` because the id segment was never validated. These
tests pin:

1. Direct ``store._path(bad_id)`` raises ``ValueError("invalid id")``
   for traversal payloads, control characters, and over-long strings.
2. UUID-style ids (``uuid4().hex`` is 32 hex chars) are accepted.
3. Route layer translates that ``ValueError`` into 400 — no 5xx, no
   404 (the request never reaches the on-disk check), no 200.
4. URL-encoded ``..%2F`` payloads delivered via the HTTP path are
   normalized by Starlette/FastAPI and either rejected by the router
   (404 path miss) or by the store validator (400). Either way no
   file outside ``$SHOWME_HOME/(bots|strategies)/`` is touched.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from showme.bots.store import BotStore
from showme.strategies.store import StrategyStore
from showme.server import build_app


# ─── Unit-level: the validator ───────────────────────────────────────────


@pytest.mark.parametrize(
    "bad_id",
    [
        "../escape",
        "../../etc/passwd",
        "..%2Fetc%2Fpasswd",  # encoded form arriving as a literal segment
        "/abs/path",
        "with space",
        "with/slash",
        "with\\backslash",
        "with\x00null",
        "with;semicolon",
        "",
        "x" * 65,  # over the 64-char ceiling
        "tab\there",
        "newline\nhere",
    ],
)
def test_bot_store_rejects_invalid_ids(tmp_path: Path, bad_id: str):
    store = BotStore(tmp_path / "bots")
    with pytest.raises(ValueError, match="invalid id"):
        store._path(bad_id)


@pytest.mark.parametrize(
    "bad_id",
    [
        "../escape",
        "../../etc/passwd",
        "/abs/path",
        "with space",
        "with/slash",
        "",
        "x" * 65,
    ],
)
def test_strategy_store_rejects_invalid_ids(tmp_path: Path, bad_id: str):
    store = StrategyStore(tmp_path / "strategies")
    with pytest.raises(ValueError, match="invalid id"):
        store._path(bad_id)


@pytest.mark.parametrize(
    "good_id",
    [
        "abc123",
        "deadbeefcafedead",
        "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",  # uuid4 with dashes
        "deadbeefcafedeadbeef0000deadbeef",  # uuid4().hex (32-char)
        "x" * 64,  # exactly the ceiling
        "A_B-c",
        "0",
    ],
)
def test_bot_store_accepts_valid_ids(tmp_path: Path, good_id: str):
    store = BotStore(tmp_path / "bots")
    # Should NOT raise.
    p = store._path(good_id)
    assert str(p).endswith(f"{good_id}.json")


@pytest.mark.parametrize(
    "good_id",
    [
        "abc123",
        "deadbeefcafedeadbeef0000deadbeef",
        "x" * 64,
        "A_B-c",
    ],
)
def test_strategy_store_accepts_valid_ids(tmp_path: Path, good_id: str):
    store = StrategyStore(tmp_path / "strategies")
    p = store._path(good_id)
    assert str(p).endswith(f"{good_id}.json")


def test_bot_validator_blocks_filesystem_escape(tmp_path: Path):
    """End-to-end: even if a caller manages to land an invalid id past
    pydantic, ``store.delete`` will not touch any file outside the
    store directory."""
    store = BotStore(tmp_path / "bots")
    # Pre-create a victim file outside the store dir.
    victim = tmp_path / "victim.json"
    victim.write_text('{"compromised": false}')
    with pytest.raises(ValueError):
        store.delete("../victim")
    assert victim.exists(), "Path traversal allowed delete outside store dir"
    assert victim.read_text() == '{"compromised": false}'


# ─── HTTP layer: the routes translate ValueError → 400 ────────────────────


@pytest.fixture
def client(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.setenv("SHOWME_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")
    import showme.bots.lifespan as lifespan
    lifespan._RUNNER = None
    app = build_app(engine_root=None)
    return TestClient(app, headers={"X-ShowMe-Token": "test-token"})


def test_get_bot_traversal_returns_400(client):
    # FastAPI path-segment containing literal ``..`` — Starlette won't
    # collapse this to a relative path; it gets passed in raw.
    r = client.get("/api/bots/..escape")
    # Either the router rejected (4xx) or our store layer caught it.
    # We require 4xx and explicitly NOT 5xx and NOT 200.
    assert r.status_code == 400, r.text


def test_get_bot_encoded_traversal_returns_4xx(client):
    # ``..%2Fetc%2Fpasswd`` — encoded segment. Starlette decodes this
    # to ``../etc/passwd`` which crosses path segments, so the router
    # itself returns a route-miss 404. We only require that the request
    # is rejected with a 4xx and never returns a 200 or 5xx that
    # surfaced the traversed file.
    r = client.get("/api/bots/..%2Fetc%2Fpasswd")
    assert 400 <= r.status_code < 500, r.text


def test_delete_bot_traversal_returns_400(client):
    r = client.delete("/api/bots/..escape")
    assert r.status_code == 400


def test_delete_bot_encoded_traversal_returns_4xx_safely(client, tmp_path: Path):
    """The repro from the audit: DELETE /api/bots/..%2Fetc%2Fpasswd
    must NOT delete anything outside the bots/ directory."""
    # Plant a victim file in the SHOWME_HOME root (sibling to bots/).
    victim = tmp_path / "victim.txt"
    victim.write_text("sensitive")
    r = client.delete("/api/bots/..%2Fvictim.txt")
    assert 400 <= r.status_code < 500
    # Most importantly: the victim file still exists.
    assert victim.exists()
    assert victim.read_text() == "sensitive"


def test_signals_endpoint_traversal_400(client):
    r = client.get("/api/bots/..escape/signals")
    assert r.status_code == 400


def test_get_strategy_traversal_400(client):
    r = client.get("/api/strategies/..escape")
    assert r.status_code == 400


def test_delete_strategy_traversal_400(client):
    r = client.delete("/api/strategies/..escape")
    assert r.status_code == 400


def test_preview_strategy_traversal_400(client):
    r = client.post("/api/strategies/..escape/preview")
    assert r.status_code == 400
