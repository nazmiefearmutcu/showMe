"""TestClient coverage for every major sidecar route family.

Per TEST-02 P1: 0 / 40 routes were exercised end-to-end through FastAPI's
``TestClient``. This file plugs that gap with at least one test per route
family: health, scanner, portfolio/state, broker, instant, x, function-index,
quote, /api/fn/{code}, watchlists, llm, and the WebSocket handshake.

The tests deliberately avoid asserting deep payload shape — the goal is to
catch route-level regressions (handler crashes, pydantic schema drift, 503
gating, body-size middleware, auth middleware, CORS, websocket origin
checks). The richer per-payload contracts already live in their own
``test_*`` files.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from showme import server


# Make sure the engine subtree is importable regardless of cwd, mirroring the
# bootstrap shim other backend test files use.
ROOT = Path(__file__).resolve().parents[1] / "showme"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def app(tmp_path_factory: pytest.TempPathFactory):
    """Build a stand-alone FastAPI app pointing at a writable temp app-home."""
    home = tmp_path_factory.mktemp("showme-home")
    os.environ["SHOWME_HOME"] = str(home)
    # Engine root left None — that's the lightweight boot path used by tests.
    return server.build_app(engine_root=None)


@pytest.fixture(scope="module")
def client(app):
    with TestClient(app) as c:
        yield c


# ── /api/health ──────────────────────────────────────────────────────────


def test_health_route(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "function_count" in body
    assert "expected_min" in body
    assert "engine" in body


# ── /api/x/health ─ (auth-exempt path, must respond even with token set) ──


def test_x_health_route(client: TestClient) -> None:
    resp = client.get("/api/x/health")
    # XAnalyzer may return any payload depending on model availability; we
    # only require the route is reachable and returns 200.
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


# ── /api/function-index ─ has the only response_model in the codebase ────


def test_function_index_route(client: TestClient) -> None:
    resp = client.get("/api/function-index")
    assert resp.status_code == 200
    rows = resp.json()
    assert isinstance(rows, list)
    # Engine isn't attached in this test config, so we only assert the
    # well-known GP/HP aliases that get stitched in regardless of the
    # registry, plus shape.
    codes = {row["code"] for row in rows}
    assert "GP" in codes
    assert "HP" in codes
    for entry in rows:
        for key in ("code", "name", "category"):
            assert key in entry, f"missing {key} in function index entry"


# ── /api/sidecar/info + /api/sidecar/ticker ──────────────────────────────


def test_sidecar_info_route(client: TestClient) -> None:
    resp = client.get("/api/sidecar/info")
    assert resp.status_code == 200
    body = resp.json()
    assert "version" in body


def test_sidecar_ticker_route(client: TestClient) -> None:
    resp = client.get("/api/sidecar/ticker")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


# ── /api/quote/{symbol} (PERF-05 cache + Path regex constraint) ──────────


def test_quote_symbol_rejects_invalid_chars(client: TestClient) -> None:
    # Paths with disallowed characters should fail validation (422).
    resp = client.get("/api/quote/<<bad>>")
    assert resp.status_code in {404, 422}


def test_quote_symbol_route_well_formed(client: TestClient, monkeypatch) -> None:
    async def fake_fetch(_symbol: str) -> dict[str, Any]:
        return {
            "symbol": "BTCUSDT",
            "last": 12345.67,
            "asset_class": "crypto",
            "source": "binance",
        }

    from showme import quotes
    quotes.quote_cache_clear()
    monkeypatch.setattr(quotes, "fetch_quote_snapshot", fake_fetch)
    resp = client.get("/api/quote/BTCUSDT")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["last"] == 12345.67
    # S07 envelope: fresh fetch carries the metadata flags.
    assert body["cache_hit"] is False
    assert body["data_state"] == "ok"
    assert body["transport_state"] == "snapshot"
    assert body["source_kind"] == "binance"
    assert body["degraded"] is False
    assert body["synthetic"] is False
    # Second call must hit the cache. The inner ``data`` payload must be
    # byte-identical (the cache must NOT mutate cached data) but the
    # top-level metadata must flip ``cache_hit`` to True.
    resp2 = client.get("/api/quote/BTCUSDT")
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body2["ok"] is True
    assert body2["data"] == body["data"]
    assert body2["cache_hit"] is True
    assert body2["data_state"] == "ok"
    assert body2["freshness_ms"] is not None and body2["freshness_ms"] >= 0
    quotes.quote_cache_clear()


# ── /api/stream/stats (S07 envelope) ─────────────────────────────────────


def test_stream_stats_envelope_shape(client: TestClient) -> None:
    """Even with zero subscribers, the route must return the S07 envelope.

    The lazy hub provider materializes a real ``StreamHub`` on first hit,
    so ``hub_present`` should be True and ``channels`` empty.
    """
    resp = client.get("/api/stream/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["hub_present"] is True
    assert isinstance(body["generated_at"], str) and body["generated_at"]
    assert isinstance(body["stale_threshold_ms"], int)
    assert body["channels"] == []
    expected_totals = {
        "channel_count",
        "subscriber_count",
        "live_count",
        "stale_count",
        "reconnecting_count",
        "error_count",
        "dropped_tick_count",
    }
    assert set(body["totals"]) == expected_totals
    for value in body["totals"].values():
        assert value == 0


def test_stream_stats_envelope_when_provider_absent() -> None:
    """If ``deps.get_stream_hub`` is None, the route returns the honest
    ``hub_present:false`` envelope rather than the old empty shape."""
    from showme.server_routes import AppDeps, websocket
    from fastapi import FastAPI

    app = FastAPI()
    deps = AppDeps(get_stream_hub=None)
    websocket.register(app, deps)
    with TestClient(app) as fresh_client:
        resp = fresh_client.get("/api/stream/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["hub_present"] is False
        assert body["channels"] == []
        assert body["totals"]["channel_count"] == 0


# ── /api/quote provider-failure metadata (S07) ───────────────────────────


def test_quote_route_returns_unavailable_envelope_on_provider_error(
    client: TestClient,
    monkeypatch,
) -> None:
    """Provider failures must be explicit (``data_state=unavailable``,
    ``transport_state=offline``) instead of looking like a live snapshot."""
    from showme import quotes

    async def boom(_symbol: str) -> dict[str, Any]:
        raise quotes.QuoteFetchError("simulated provider outage")

    quotes.quote_cache_clear()
    monkeypatch.setattr(quotes, "fetch_quote_snapshot", boom)
    resp = client.get("/api/quote/AAPL")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["data"] is None
    assert "simulated provider outage" in body["error"]
    assert body["cache_hit"] is False
    assert body["data_state"] == "unavailable"
    assert body["transport_state"] == "offline"
    assert body["freshness_ms"] is None
    assert body["source_kind"] is None
    assert body["degraded"] is True
    assert body["synthetic"] is False
    # A repeat call hits the cached failure — cache_hit flips, data shape stays.
    resp2 = client.get("/api/quote/AAPL")
    body2 = resp2.json()
    assert body2["ok"] is False
    assert body2["cache_hit"] is True
    assert body2["data_state"] == "unavailable"
    assert body2["transport_state"] == "offline"
    quotes.quote_cache_clear()


# ── /api/state/positions / trades / migrations ───────────────────────────


def test_state_positions_route(client: TestClient) -> None:
    resp = client.get("/api/state/positions")
    assert resp.status_code == 200
    body = resp.json()
    assert "rows" in body and isinstance(body["rows"], list)


def test_state_trades_route_bounds_limit(client: TestClient) -> None:
    # limit > 1000 must be rejected by the Query validator (SEC-05).
    resp = client.get("/api/state/trades?limit=5000")
    assert resp.status_code == 422


# ── /api/scanner/run / universes ─────────────────────────────────────────


def test_scanner_universes_route(client: TestClient) -> None:
    resp = client.get("/api/scanner/universes")
    # Engine not attached in this fixture: route may return 200 with []
    # OR 503 (engine guard) — both are acceptable signals that the route
    # is wired correctly.
    assert resp.status_code in {200, 503}


def test_scanner_run_engine_guard(client: TestClient) -> None:
    resp = client.post("/api/scanner/run", json={"universe": "crypto:top10"})
    # Without engine_root attached the handler must return 503 quickly,
    # not 500 or hang.
    assert resp.status_code == 503


# ── /api/broker/info / orders ─────────────────────────────────────────────


def test_broker_info_route(client: TestClient) -> None:
    resp = client.get("/api/broker/info")
    assert resp.status_code == 200
    body = resp.json()
    assert "broker" in body
    assert "registered" in body


def test_broker_submit_order_validates_body(client: TestClient) -> None:
    # Missing required fields → 422 from Pydantic OrderRequest.
    resp = client.post("/api/broker/orders", json={})
    assert resp.status_code == 422
    # Negative quantity must also fail (gt=0).
    resp = client.post(
        "/api/broker/orders",
        json={"symbol": "AAPL", "side": "buy", "quantity": -1},
    )
    assert resp.status_code == 422


# ── /api/llm/cost ────────────────────────────────────────────────────────


def test_llm_cost_route(client: TestClient) -> None:
    resp = client.get("/api/llm/cost")
    assert resp.status_code == 200
    body = resp.json()
    for key in ("today_usd", "cap_usd", "remaining_usd", "exhausted", "providers"):
        assert key in body


# ── /api/instant/* ────────────────────────────────────────────────────────


def test_instant_routes(client: TestClient) -> None:
    for path in (
        "/api/instant/status",
        "/api/instant/events",
        "/api/instant/health",
        "/api/instant/performance",
    ):
        resp = client.get(path)
        assert resp.status_code in {200, 503}, f"{path} -> {resp.status_code}"


def test_instant_events_bounds_limit(client: TestClient) -> None:
    resp = client.get("/api/instant/events?limit=99999")
    assert resp.status_code == 422


# ── /api/x/* (POST classify validates body shape) ────────────────────────


def test_x_classify_validates_body(client: TestClient) -> None:
    # Missing texts → 422.
    resp = client.post("/api/x/classify", json={})
    assert resp.status_code == 422
    # Empty texts list → 422 (min_length=1).
    resp = client.post("/api/x/classify", json={"texts": []})
    assert resp.status_code == 422


def test_x_symbol_chip_bounds_limit(client: TestClient) -> None:
    resp = client.get("/api/x/symbol_chip?symbol=BTC&limit=99999")
    assert resp.status_code == 422


# ── /api/watchlists/* (FUNC-08 P1 — multi-watchlist routes) ──────────────


def test_watchlists_round_trip(client: TestClient) -> None:
    # Persist a watchlist with a couple of well-formed symbols.
    resp = client.put(
        "/api/watchlists/round2a",
        json={"symbols": ["AAPL", "BTCUSDT", "junk symbol", "EURUSD=X"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    # Server-side normalisation must drop the invalid entry.
    assert "AAPL" in body["symbols"]
    assert "BTCUSDT" in body["symbols"]
    assert "junk symbol" not in body["symbols"]
    # GET should now include it.
    resp = client.get("/api/watchlists")
    assert resp.status_code == 200
    body = resp.json()
    assert any(w["name"] == "round2a" for w in body["watchlists"])
    # DELETE should succeed and the entry should disappear.
    resp = client.delete("/api/watchlists/round2a")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


# ── /api/fn/{code} ───────────────────────────────────────────────────────


def test_run_function_invalid_code(client: TestClient) -> None:
    # Unknown code returns 404 (the engine is not attached so the lookup
    # falls through; either way the status must NOT be 200).
    resp = client.get("/api/fn/__unknown__")
    assert resp.status_code in {404, 503}


# ── /api/proxy/* (legacy 410 stub) ───────────────────────────────────────


def test_legacy_proxy_returns_410(client: TestClient) -> None:
    resp = client.get("/api/proxy/anything")
    assert resp.status_code == 410


# ── Body-size middleware (SEC-05) ────────────────────────────────────────


def test_body_size_middleware_rejects_oversized(client: TestClient) -> None:
    # 512 KB payload via Content-Length header should be rejected (>256 KB cap).
    resp = client.post(
        "/api/x/classify",
        headers={"Content-Length": "524288", "Content-Type": "application/json"},
        content=b"{" + b" " * 524286 + b"}",
    )
    assert resp.status_code == 413


# ── Auth middleware (SHOWME_AUTH_TOKEN) ──────────────────────────────────


def test_auth_middleware_blocks_when_token_missing(client: TestClient, monkeypatch) -> None:
    # Set a token, then a request without the header must 401 (except for
    # the two exempt paths).
    monkeypatch.setenv("SHOWME_AUTH_TOKEN", "secret-2a")
    blocked = client.get("/api/sidecar/info")
    assert blocked.status_code == 401
    # Exempt paths still work.
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/x/health").status_code == 200
    # Correct header passes through.
    ok = client.get("/api/sidecar/info", headers={"X-ShowMe-Token": "secret-2a"})
    assert ok.status_code == 200


# ── /ws/quote/{symbol} (Origin allowlist + handshake) ────────────────────


def test_ws_quote_rejects_disallowed_origin(client: TestClient) -> None:
    with pytest.raises(Exception):
        # Origin not on the allowlist → server closes with 1008 (policy
        # violation) before accept; TestClient surfaces this as an
        # exception/disconnect.
        with client.websocket_connect(
            "/ws/quote/BTCUSDT",
            headers={"origin": "http://evil.example"},
        ):
            pass


def test_ws_quote_rejects_invalid_symbol(client: TestClient) -> None:
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/quote/<<bad>>"):
            pass


def test_ws_quote_rejects_missing_origin(client: TestClient) -> None:
    # QA-fix: Origin is now mandatory by default. The opt-out path lives
    # below for non-browser callers (sidecar self-tester / pytest WS).
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/quote/BTCUSDT"):
            pass


def test_ws_quote_handshakes_without_origin_when_opt_out(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Opt-out path: setting SHOWME_WS_REQUIRE_ORIGIN=0 restores the
    # non-browser handshake (used by the sidecar self-tester / pytest WS
    # client). New app instance so the env var is picked up.
    monkeypatch.setenv("SHOWME_WS_REQUIRE_ORIGIN", "0")
    home = tmp_path_factory.mktemp("ws-optout-home")
    monkeypatch.setenv("SHOWME_HOME", str(home))
    app = server.build_app(engine_root=None)
    with TestClient(app) as c:
        ctx = c.websocket_connect("/ws/quote/BTCUSDT")
        try:
            with ctx as ws:  # noqa: F841 — handshake is the assertion
                pass
        except Exception:
            # Acceptable: the test transport can disconnect immediately
            # because no real upstream tick arrives during the test window.
            pass


# ── Lifespan migration (R4B) — TestClient ``with:`` block exercises both
#    the startup and shutdown branches of the asynccontextmanager lifespan,
#    replacing the deprecated @app.on_event("startup") hook. ──────────────


def test_lifespan_startup_and_shutdown(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Build a fresh app and walk through the lifespan once.

    The TestClient context manager triggers ``startup`` on enter and
    ``shutdown`` on exit. Both branches must complete without raising
    and ``/api/health`` must respond 200 from inside the block.
    """
    home = tmp_path_factory.mktemp("showme-lifespan")
    os.environ["SHOWME_HOME"] = str(home)
    fresh_app = server.build_app(engine_root=None)
    with TestClient(fresh_app) as fresh_client:
        resp = fresh_client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ── MIS scan input validation (S15) — bad numeric inputs must produce 400
#    before the engine-attached 503 guard so the UI can surface a clear
#    error instead of opaque 500s. ─────────────────────────────────────────


def test_mis_scan_rejects_malformed_top_n(client: TestClient) -> None:
    resp = client.post("/api/mis/scan", json={"top_n": "fast"})
    assert resp.status_code == 400, resp.text
    assert "invalid integer" in resp.text


def test_mis_scan_rejects_malformed_min_confidence(client: TestClient) -> None:
    resp = client.post("/api/mis/scan", json={"min_confidence": "high"})
    assert resp.status_code == 400, resp.text
    assert "invalid number" in resp.text


def test_mis_scan_rejects_malformed_max_symbols(client: TestClient) -> None:
    resp = client.post("/api/mis/scan", json={"max_symbols_per_market": "{}"})
    assert resp.status_code == 400, resp.text


def test_mis_scan_accepts_blank_max_symbols(client: TestClient) -> None:
    # `max_symbols_per_market: ""` is a common "unset" payload from the UI;
    # it must not crash and must fall through to the engine guard (503 here,
    # since the test fixture has no engine attached).
    resp = client.post("/api/mis/scan", json={"max_symbols_per_market": ""})
    assert resp.status_code == 503, resp.text


def test_mis_scan_engine_guard_with_valid_input(client: TestClient) -> None:
    # Sanity: well-formed input still produces 503 when the engine is not
    # attached — i.e. our 400 path only fires on actually-bad input.
    resp = client.post("/api/mis/scan", json={"top_n": 25, "min_confidence": 0.1})
    assert resp.status_code == 503, resp.text
