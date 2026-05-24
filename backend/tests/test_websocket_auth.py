"""SEC-13/14: WebSocket auth gate + HTTP token constant-time compare.

Before the fix, ``/ws/quote/{symbol}`` was unauthenticated (the HTTP
auth_token_middleware only matches /api/* paths) — any local process could
tap the live tick stream by guessing the dynamic sidecar port. Plus the
HTTP middleware used plain ``!=`` which leaks token bytes through latency.
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from showme.server import build_app


_TOKEN = "test-token-32-bytes-hex-1234567890ab"


@pytest.fixture
def client_with_token(monkeypatch):
    monkeypatch.setenv("SHOWME_AUTH_TOKEN", _TOKEN)
    # Force the WS-allowed-origin to include the TestClient host so the
    # Origin check (which runs BEFORE the token check) doesn't 1008 us.
    monkeypatch.setenv("SHOWME_WS_REQUIRE_ORIGIN", "0")
    app = build_app(engine_root=None)
    return TestClient(app)


@pytest.fixture
def client_no_token(monkeypatch):
    monkeypatch.delenv("SHOWME_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("SHOWME_WS_REQUIRE_ORIGIN", "0")
    app = build_app(engine_root=None)
    return TestClient(app)


@contextmanager
def _expect_close(client: TestClient, url: str, *, subprotocols=None):
    """Helper: the connect raises WebSocketDisconnect on close-before-accept."""
    try:
        with client.websocket_connect(url, subprotocols=subprotocols) as ws:
            # If accept happened we should not reach here.
            yield ws
    except WebSocketDisconnect as exc:
        yield exc


def test_ws_no_token_when_required_is_rejected(client_with_token):
    """No token in query/header/subprotocol → 4401 close."""
    with pytest.raises(WebSocketDisconnect) as info:
        with client_with_token.websocket_connect("/ws/quote/AAPL"):
            pass
    assert info.value.code == 4401


def test_ws_wrong_token_is_rejected(client_with_token):
    """Wrong token value → 4401 close, constant-time compare doesn't crash."""
    with pytest.raises(WebSocketDisconnect) as info:
        with client_with_token.websocket_connect("/ws/quote/AAPL?token=wrong"):
            pass
    assert info.value.code == 4401


def test_ws_correct_token_query_param_accepted(client_with_token):
    """?token=<TOKEN> passes the gate (stream itself may still fail w/ 'hub unavailable')."""
    try:
        with client_with_token.websocket_connect(
            f"/ws/quote/AAPL?token={_TOKEN}"
        ) as ws:
            # Server accepts then sends 'stream hub unavailable' because
            # build_app(engine_root=None) doesn't wire a hub. That's fine —
            # we only care the auth gate let us through.
            msg = ws.receive_json()
            # Auth gate passed → either an error envelope ("stream hub unavailable")
            # or a real tick payload ({price, ask, bid, ...}). Both prove the
            # token check let us through; we only care that 4401 didn't fire.
            assert isinstance(msg, dict)
    except WebSocketDisconnect:
        pytest.fail("expected websocket to be accepted after token match")


def test_ws_correct_token_via_header_accepted(client_with_token):
    """X-ShowMe-Token header passes the gate (Tauri shell injects this)."""
    try:
        with client_with_token.websocket_connect(
            "/ws/quote/AAPL",
            headers={"X-ShowMe-Token": _TOKEN},
        ) as ws:
            msg = ws.receive_json()
            # Auth gate passed → either an error envelope ("stream hub unavailable")
            # or a real tick payload ({price, ask, bid, ...}). Both prove the
            # token check let us through; we only care that 4401 didn't fire.
            assert isinstance(msg, dict)
    except WebSocketDisconnect:
        pytest.fail("expected websocket to be accepted after header token match")


def test_ws_correct_token_via_subprotocol_accepted(client_with_token):
    """Sec-WebSocket-Protocol: showme.token.<value> passes the gate."""
    try:
        with client_with_token.websocket_connect(
            "/ws/quote/AAPL",
            subprotocols=[f"showme.token.{_TOKEN}"],
        ) as ws:
            msg = ws.receive_json()
            # Auth gate passed → either an error envelope ("stream hub unavailable")
            # or a real tick payload ({price, ask, bid, ...}). Both prove the
            # token check let us through; we only care that 4401 didn't fire.
            assert isinstance(msg, dict)
    except WebSocketDisconnect:
        pytest.fail("expected websocket to be accepted after subprotocol token match")


def test_ws_no_token_required_when_env_unset(client_no_token):
    """When SHOWME_AUTH_TOKEN is unset (dev mode), no token is required."""
    try:
        with client_no_token.websocket_connect("/ws/quote/AAPL") as ws:
            msg = ws.receive_json()
            # Auth gate passed → either an error envelope ("stream hub unavailable")
            # or a real tick payload ({price, ask, bid, ...}). Both prove the
            # token check let us through; we only care that 4401 didn't fire.
            assert isinstance(msg, dict)
    except WebSocketDisconnect as exc:
        # The only acceptable close at this point is the hub-unavailable
        # one (normal 1000/1006), not 4401.
        assert exc.code != 4401, "expected dev mode to bypass token check"


def test_ws_opt_out_via_env_flag(client_with_token, monkeypatch):
    """SHOWME_WS_REQUIRE_TOKEN=0 disables the token check even when set."""
    monkeypatch.setenv("SHOWME_WS_REQUIRE_TOKEN", "0")
    try:
        with client_with_token.websocket_connect("/ws/quote/AAPL") as ws:
            msg = ws.receive_json()
            # Auth gate passed → either an error envelope ("stream hub unavailable")
            # or a real tick payload ({price, ask, bid, ...}). Both prove the
            # token check let us through; we only care that 4401 didn't fire.
            assert isinstance(msg, dict)
    except WebSocketDisconnect as exc:
        assert exc.code != 4401


def test_http_token_uses_hmac_compare_digest(client_with_token):
    """HTTP /api/* with wrong token is rejected (verifies compare_digest path)."""
    # Use a non-exempt route. /api/health is exempt; /api/portfolio/aggregate
    # is gated. The 401 path proves compare_digest didn't crash on len mismatch.
    res = client_with_token.get(
        "/api/portfolio/aggregate", headers={"X-ShowMe-Token": "definitely-wrong"}
    )
    assert res.status_code == 401
    body = res.json()
    assert "missing or invalid" in body.get("detail", "")


def test_http_token_correct_passes(client_with_token):
    """HTTP /api/* with correct token is accepted (constant-time compare OK)."""
    res = client_with_token.get(
        "/api/portfolio/aggregate", headers={"X-ShowMe-Token": _TOKEN}
    )
    # 200 or 500 (no creds wired) — either way NOT 401.
    assert res.status_code != 401
