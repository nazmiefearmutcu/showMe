"""WAVE 4 (py-server) fix-phase regression tests.

Covers the coordinator-triaged findings from hunt-02-py-server.md:
HNT-01 (agent fail status), HNT-02 (templates unconditional mount),
HNT-04 (/ws/quote disconnect leak), HNT-05 (hf classify off-loop),
HNT-06 (agent route validation + budget), HNT-07 (honest unavailable
echo), HNT-08 (SWR fast-fail double execution), HNT-09 (FeedHub
shutdown), HNT-10 (port reservation TOCTOU), HNT-11 (chunked 411),
HNT-12 (health warm_error masking), HNT-13 (scanner numeric 400s),
HNT-14 (force-delete ordering), HNT-15 (portfolio asset-class ladder),
E1 (llm_router client shutdown) and E2 (paper market-order hint).
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from showme.server import build_app


# ── HNT-01: agent exception path marks rows "fail" ───────────────────────


def test_agent_live_execution_failure_counts_as_fail(monkeypatch) -> None:
    from showme import server
    from showme.server_routes._models import FunctionIndexEntry

    async def failing_exec(_code: str, _params: dict[str, Any]) -> Any:
        raise RuntimeError("provider down")

    monkeypatch.setattr(server, "_execute_showme_function", failing_exec)
    monkeypatch.setattr(
        server,
        "_load_function_index",
        lambda: [FunctionIndexEntry(code="MLSIG", name="ML Signal", category="portfolio")],
    )

    out = asyncio.run(server._run_best_symbol_agent({
        "candidates": ["BTCUSDT"],
        "execute_functions": True,
        "include_functions": True,
    }))

    best = out["best"]
    assert best is not None
    # Pre-fix: the except block set status = "pass" so every failure
    # inflated pass_count and fail_count stayed 0 in live mode.
    assert best["fail"] == 1
    assert best["pass"] == 0
    assert best["functions"][0]["status"] == "fail"
    assert "provider down" in best["functions"][0]["reason"]


# ── HNT-02: /api/templates mounted without SHOWME_DEV ────────────────────


def test_templates_routes_mounted_without_showme_dev(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.delenv("SHOWME_DEV", raising=False)
    import showme.server_routes.templates as tmod

    tmod._CATALOG = None
    tmod._CATALOG_ERROR = None
    app = build_app(engine_root=None)
    client = TestClient(app)
    resp = client.get("/api/templates")
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list) and resp.json()


# ── HNT-04: /ws/quote releases the subscription on silent disconnect ─────


def test_ws_quote_releases_subscription_on_silent_disconnect(monkeypatch) -> None:
    from showme.server_routes import AppDeps, websocket

    monkeypatch.delenv("SHOWME_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("SHOWME_WS_REQUIRE_ORIGIN", "0")

    tracker: dict[str, bool] = {"released": False}

    class _FakeSubscription:
        def __init__(self, queue: asyncio.Queue) -> None:
            self._queue = queue

        async def __aenter__(self) -> asyncio.Queue:
            return self._queue

        async def __aexit__(self, *_exc: Any) -> None:
            tracker["released"] = True

    class _FakeHub:
        def __init__(self) -> None:
            # A channel that never produces a tick: the old handler
            # parked on queue.get() forever and never noticed the client
            # had gone.
            self.queue: asyncio.Queue = asyncio.Queue()

        async def subscribe(self, _symbol: str) -> _FakeSubscription:
            return _FakeSubscription(self.queue)

    hub = _FakeHub()
    app = FastAPI()
    websocket.register(app, AppDeps(get_stream_hub=lambda: hub))
    client = TestClient(app)

    with client.websocket_connect("/ws/quote/BTCUSDT") as ws:
        # Deliver the ASGI websocket.disconnect message WITHOUT exiting
        # the context manager (whose scope cancellation would mask the
        # bug): this is the exact "client closed the pane while the
        # channel was silent" scenario from the hunt report.
        ws.close(1000)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not tracker["released"]:
            time.sleep(0.02)

    assert tracker["released"], (
        "ws_quote handler leaked: hub subscription was not released after "
        "a silent-channel client disconnect"
    )


# ── HNT-05: hf classify runs off the event loop thread ───────────────────


def test_hf_classify_runs_in_worker_thread(monkeypatch) -> None:
    from showme.server_routes import AppDeps, integrations

    classify_thread: dict[str, int] = {}
    loop_thread: dict[str, int] = {}

    def fake_classify(text: str) -> dict[str, Any]:
        classify_thread["id"] = threading.get_ident()
        return {"label": "positive"}

    monkeypatch.setattr("showme.integrations.hf.classify", fake_classify)

    app = FastAPI()
    integrations.register(app, AppDeps())

    @app.get("/_loop-thread")
    async def _loop_thread() -> dict[str, Any]:
        loop_thread["id"] = threading.get_ident()
        return {}

    client = TestClient(app)
    probe = client.get("/_loop-thread")
    assert probe.status_code == 200
    resp = client.post("/api/integrations/hf/classify", json={"text": "markets rally"})
    assert resp.status_code == 200
    assert resp.json() == {"label": "positive"}
    # Pre-fix: classify (RoBERTa cold-load + torch inference) ran ON the
    # event-loop thread, freezing every concurrent request.
    assert classify_thread["id"] != loop_thread["id"]


# ── HNT-06: agent route numeric validation + route budget ────────────────


def _agent_app(monkeypatch) -> TestClient:
    from showme.server_routes import AppDeps, agent

    monkeypatch.setattr(
        "showme.server._run_best_symbol_agent_blocking",
        lambda req: {"best": None, "ranked": []},
    )
    app = FastAPI()
    agent.register(app, AppDeps(boot_state={"engine_attached": True}))
    return TestClient(app)


def test_agent_route_rejects_bad_max_candidates(monkeypatch) -> None:
    client = _agent_app(monkeypatch)
    resp = client.post("/api/agent/best-symbol", json={"max_candidates": "abc"})
    assert resp.status_code == 400, resp.text
    assert "max_candidates" in resp.text or "invalid integer" in resp.text


def test_agent_route_rejects_bad_per_function_timeout(monkeypatch) -> None:
    client = _agent_app(monkeypatch)
    resp = client.post("/api/agent/best-symbol", json={"per_function_timeout": [12]})
    assert resp.status_code == 400, resp.text


def test_agent_route_enforces_overall_budget(monkeypatch) -> None:
    import showme.server_routes.agent as agent_mod

    def slow_blocking(_req: dict[str, Any]) -> dict[str, Any]:
        time.sleep(1.0)
        return {"best": None, "ranked": []}

    monkeypatch.setattr(
        "showme.server._run_best_symbol_agent_blocking", slow_blocking
    )
    monkeypatch.setattr(agent_mod, "_AGENT_ROUTE_BUDGET_S", 0.05)

    from showme.server_routes import AppDeps, agent

    app = FastAPI()
    agent.register(app, AppDeps(boot_state={"engine_attached": True}))
    client = TestClient(app)
    resp = client.post("/api/agent/best-symbol", json={})
    assert resp.status_code == 504, resp.text
    assert "budget" in resp.json()["detail"]
    # NB: the route RETURNS at the budget (the 504 is raised by
    # wait_for); the to_thread worker itself cannot be interrupted and
    # finishes in the background — the documented asyncio limitation the
    # hunt report acknowledges. (The wall-clock of client.post also
    # includes the TestClient portal's loop.shutdown(wait=True) joining
    # that executor thread, so it is not asserted here.)


# ── HNT-07: unavailable_function_data does not invent a symbol ───────────


def test_unavailable_function_data_no_invented_symbol() -> None:
    from showme import server

    data = server.unavailable_function_data(
        "TOP", {"query": "market news"}, reason="rss unreachable"
    )
    assert data["symbol"] is None
    assert "symbol" not in data["requested"]
    # A free-text topic must not masquerade as a symbol either.
    data_topic = server.unavailable_function_data(
        "NI", {"topic": "market news"}, reason="down"
    )
    assert data_topic["symbol"] is None
    assert data_topic["requested"].get("topic") == "market news"

    # A real symbol request still echoes it, canonically.
    data_sym = server.unavailable_function_data(
        "GP", {"symbol": "aapl", "asset_class": "EQUITY"}, reason="down"
    )
    assert data_sym["symbol"] == "AAPL"
    assert data_sym["requested"]["asset_class"] == "EQUITY"


# ── HNT-08: SWR fast-fail path must not re-execute the function ──────────


def test_swr_fast_fail_does_not_double_execute(monkeypatch) -> None:
    from showme import server
    from showme.server_routes import AppDeps, function_index

    monkeypatch.setattr(server, "home_swr_enabled", lambda: True)
    monkeypatch.setattr(
        server, "_route_function_params", lambda code, params: dict(params)
    )
    calls = {"n": 0}

    async def failing_exec(_code: str, _params: dict[str, Any]) -> Any:
        calls["n"] += 1
        raise RuntimeError("deterministic provider failure")

    monkeypatch.setattr(server, "_execute_showme_function", failing_exec)

    app = FastAPI()
    function_index.register(app, AppDeps(boot_state={"engine_attached": True}))
    client = TestClient(app)

    resp = client.post("/api/fn/TOP", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["metadata"]["fallback"] is True
    assert "deterministic provider failure" in str(
        body["metadata"]["provider_errors"]
    )
    # Pre-fix: the first exception was swallowed and the function was
    # re-executed with the full budget (double provider charge).
    assert calls["n"] == 1, f"expected exactly one execution, got {calls['n']}"


# ── HNT-09: FeedHub.aclose tears sessions down ───────────────────────────


def test_feed_hub_aclose_cancels_sessions_and_stops_feeds() -> None:
    from showme.flowmap import events
    from showme.flowmap.session import ClientTx, FeedHub

    class _FakeFeed:
        def __init__(self) -> None:
            self.stopped = False
            self.synced = False

        def stop(self) -> None:
            self.stopped = True

        async def events(self):
            while True:
                await asyncio.sleep(0.05)
                yield events.FeedStateEvent("live")

    async def _run() -> None:
        feed = _FakeFeed()
        hub = FeedHub(feed_factory=lambda _symbol: feed)
        sub = events.Subscribe(market="crypto", symbol="BTCUSDT", mode="live")
        session = await hub.subscribe(sub, ClientTx())
        assert hub.live_feed_count == 1
        run_task = session.run_task
        assert run_task is not None

        await hub.aclose()
        assert hub.live_feed_count == 0
        assert feed.stopped
        assert run_task.done()
        # Idempotent: a second shutdown must not raise.
        await hub.aclose()

    asyncio.run(_run())


# ── HNT-09 + E1: _shutdown_cleanup closes flowmap hub + llm clients ─────


def test_shutdown_cleanup_closes_flowmap_hub_and_llm_clients(monkeypatch) -> None:
    from showme import server

    calls: list[str] = []

    class _FakeFlowHub:
        async def aclose(self) -> None:
            calls.append("flowmap")

    async def fake_aclose_clients() -> None:
        calls.append("llm")

    monkeypatch.setattr(
        "showme.engine.agents.llm_router.aclose_clients", fake_aclose_clients
    )
    app = FastAPI()
    app.state.flowmap_hub = _FakeFlowHub()

    asyncio.run(server._shutdown_cleanup(lambda: None, app))
    assert "flowmap" in calls
    assert "llm" in calls

    # Backward-compatible signature (no app) must not raise.
    asyncio.run(server._shutdown_cleanup(lambda: None))


# ── HNT-10: _pick_port keeps the reserved socket bound ───────────────────


def test_pick_port_returns_bound_reserved_socket() -> None:
    from showme import server

    port, sock = server._pick_port(0)
    try:
        assert sock is not None
        # The reservation is still held: the socket is bound to the very
        # port we report on stdout (no close-then-rebind TOCTOU window).
        name = sock.getsockname()
        assert name[0] == "127.0.0.1"
        assert name[1] == port
    finally:
        if sock is not None:
            sock.close()

    explicit_port, explicit_sock = server._pick_port(8080)
    assert explicit_port == 8080
    assert explicit_sock is None


# ── HNT-11: chunked request bodies are rejected with 411 ─────────────────


def test_chunked_post_rejected_with_411(monkeypatch) -> None:
    monkeypatch.delenv("SHOWME_AUTH_TOKEN", raising=False)
    app = build_app(engine_root=None)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/quote/BTCUSDT",
        "raw_path": b"/api/quote/BTCUSDT",
        "query_string": b"",
        "root_path": "",
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
        "headers": [(b"transfer-encoding", b"chunked")],
        "app": app,
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"x" * 10, "more_body": False}

    messages: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    assert start["status"] == 411, f"expected 411, got {start['status']}"


# ── HNT-12: /api/health masks *_warm_error detail ────────────────────────


def test_health_masks_warm_error_detail(monkeypatch) -> None:
    from showme.server_routes import AppDeps, health

    # Keep the probe cheap: no function-index walk.
    monkeypatch.setattr("showme.server._load_function_index", lambda: [])
    boot_state = {
        "engine_attached": False,
        "function_factory_warm_error": "FileNotFoundError: /Users/x/.cache/model.bin",
    }
    app = FastAPI()
    health.register(app, AppDeps(boot_state=boot_state))
    client = TestClient(app)

    body = client.get("/api/health").json()
    assert body["ok"] is True
    # Presence is preserved as a bool; the exception string must NOT leak
    # through the auth-exempt endpoint.
    assert body["engine"]["function_factory_warm_error"] is True
    assert "/Users/x" not in json.dumps(body)


# ── HNT-13: scanner numeric fields validate to 400 ───────────────────────


def _scanner_app(monkeypatch, run_scan) -> TestClient:
    from types import SimpleNamespace

    from showme import server
    from showme.server_routes import AppDeps, scanner

    class _FakeFactory:
        deps = None

    fake_factory_mod = SimpleNamespace(get_factory=lambda: _FakeFactory())
    monkeypatch.setattr(
        server,
        "_safe_import",
        lambda name: fake_factory_mod
        if name == "showme.engine.services.function_factory"
        else None,
    )
    monkeypatch.setattr("showme.scanner.run_scan", run_scan)
    app = FastAPI()
    scanner.register(app, AppDeps(boot_state={"engine_attached": True}))
    return TestClient(app)


def test_scanner_rejects_bad_top_n(monkeypatch) -> None:
    async def unreachable_run_scan(*_a: Any, **_kw: Any) -> Any:  # pragma: no cover
        raise AssertionError("run_scan must not be reached on invalid input")

    client = _scanner_app(monkeypatch, unreachable_run_scan)
    resp = client.post("/api/scanner/run", json={"top_n": "fast"})
    assert resp.status_code == 400, resp.text
    assert "invalid integer" in resp.json()["detail"]


def test_scanner_rejects_bad_fine_top_k(monkeypatch) -> None:
    async def unreachable_run_scan(*_a: Any, **_kw: Any) -> Any:  # pragma: no cover
        raise AssertionError("run_scan must not be reached on invalid input")

    client = _scanner_app(monkeypatch, unreachable_run_scan)
    resp = client.post("/api/scanner/run", json={"fine_top_k": [1]})
    assert resp.status_code == 400, resp.text


def test_scanner_accepts_valid_numbers(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    class _FakeResult:
        def to_dict(self) -> dict[str, Any]:
            return {"ok": True}

    async def fake_run_scan(req: Any, _deps: Any) -> Any:
        seen["top_n"] = req.top_n
        seen["fine_top_k"] = req.fine_top_k
        return _FakeResult()

    client = _scanner_app(monkeypatch, fake_run_scan)
    resp = client.post("/api/scanner/run", json={"top_n": 5, "fine_top_k": 3})
    assert resp.status_code == 200, resp.text
    assert seen == {"top_n": 5, "fine_top_k": 3}


# ── HNT-14: force-delete runs cascade only after the delete commits ──────


_CASCADE_YAML = """
- id: binance
  display_name: Binance
  aliases: []
  asset_classes: [spot]
  regions: [global]
  adapter: ccxt
  ccxt_id: binance
  requires: [api_key, api_secret]
  optional: []
  capabilities: {fetch_balance: true, fetch_positions: true, fetch_open_orders: true, create_order: true, cancel_order: true}
"""


@pytest.fixture
def cascade_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.setenv("SHOWME_AUTH_TOKEN", "test-token")
    yml = tmp_path / "ex.yml"
    yml.write_text(_CASCADE_YAML)
    from showme.brokers import factory as factory_mod
    from showme.brokers.catalog.loader import load_catalog

    monkeypatch.setattr(factory_mod, "_CATALOG", load_catalog(yml))
    factory_mod._DYNAMIC.clear()
    factory_mod._LIVE.clear()
    for name in list(factory_mod._REGISTRY.keys()):
        if ":" in name:
            factory_mod._REGISTRY.pop(name, None)
    import showme.bots.lifespan as lifespan

    lifespan._RUNNER = None
    app = build_app(engine_root=None)
    return TestClient(app, headers={"X-ShowMe-Token": "test-token"})


def _seed_ghost_bot(tmp_home: Path, *, credential_id: str, strategy_id: str) -> str:
    """Write a bot record directly to the store, referencing ids that do
    NOT exist in their stores (FK validation on the bots route would
    reject this — that's the point: the refs are stale by delete time)."""
    bots_dir = tmp_home / "bots"
    bots_dir.mkdir(parents=True, exist_ok=True)
    bot_id = "bot-ghost"
    (bots_dir / f"{bot_id}.json").write_text(
        json.dumps({
            "id": bot_id,
            "strategy_id": strategy_id,
            "credential_id": credential_id,
            "exchange_id": "binance",
            "symbol": "BTC/USDT",
            "timeframe": "1h",
            "mode": "shadow",
            "enabled": True,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }),
        encoding="utf-8",
    )
    return bot_id


def _bot_enabled(client: TestClient, bot_id: str) -> bool:
    resp = client.get(f"/api/bots/{bot_id}")
    assert resp.status_code == 200, resp.text
    return bool(resp.json()["enabled"])


def test_exchange_force_delete_404_runs_no_cascade(
    cascade_client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import showme.server_routes.exchange as exchange_mod

    cascade_calls: list[str] = []

    async def spying_cascade(bot_ids: list[str]) -> list[dict[str, str]]:
        cascade_calls.extend(bot_ids)
        return [{"bot_id": bid, "status": "disabled"} for bid in bot_ids]

    monkeypatch.setattr(exchange_mod, "_cascade_disable_bots", spying_cascade)

    bot_id = _seed_ghost_bot(
        tmp_path, credential_id="ghost-credential", strategy_id="any-strategy"
    )
    # Bot references the credential, but the credential does not exist:
    # store.delete must 404 and — pre-fix — the cascade had already
    # disabled the bot as a side effect of a "nothing happened" answer.
    resp = cascade_client.delete("/api/exchange/credentials/ghost-credential?force=true")
    assert resp.status_code == 404, resp.text
    assert cascade_calls == []
    assert _bot_enabled(cascade_client, bot_id) is True


def test_strategies_force_delete_404_runs_no_cascade(
    cascade_client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import showme.server_routes.strategies as strategies_mod

    cascade_calls: list[str] = []

    async def spying_cascade(bot_ids: list[str]) -> list[dict[str, str]]:
        cascade_calls.extend(bot_ids)
        return [{"bot_id": bid, "status": "disabled"} for bid in bot_ids]

    monkeypatch.setattr(strategies_mod, "_cascade_disable_bots", spying_cascade)

    bot_id = _seed_ghost_bot(
        tmp_path, credential_id="any-credential", strategy_id="ghost-strategy"
    )
    resp = cascade_client.delete("/api/strategies/ghost-strategy?force=true")
    assert resp.status_code == 404, resp.text
    assert cascade_calls == []
    assert _bot_enabled(cascade_client, bot_id) is True


def test_strategies_force_delete_cascade_after_commit(
    cascade_client: TestClient, tmp_path: Path
) -> None:
    """Happy path: an EXISTING strategy with referencing bots still gets
    the cascade-disable (now strictly after the delete commits)."""
    create = cascade_client.post("/api/strategies", json={
        "name": "cascade order probe",
        "indicators": [{"alias": "rsi14", "id": "rsi", "params": {"period": 14}}],
        "entry_rules": [{"kind": "crosses_below", "left": "rsi14", "right": "literal:30"}],
        "exit_rules": [{"kind": "crosses_above", "left": "rsi14", "right": "literal:70"}],
        "exit_logic": "any",
    })
    assert create.status_code == 200, create.text
    sid = create.json()["id"]
    bot_id = _seed_ghost_bot(
        tmp_path, credential_id="any-credential", strategy_id=sid
    )

    resp = cascade_client.delete(f"/api/strategies/{sid}?force=true")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["bots_affected"] == 1
    assert _bot_enabled(cascade_client, bot_id) is False
    # Strategy is gone.
    gone = cascade_client.get(f"/api/strategies/{sid}")
    assert gone.status_code == 404


# ── HNT-15: portfolio manual-position asset-class inference ──────────────


def test_resolve_asset_class_full_ladder() -> None:
    from showme.engine.core.instrument import AssetClass
    from showme.server_routes.portfolio import _resolve_asset_class

    assert _resolve_asset_class("", "BTCUSDT") == AssetClass.CRYPTO
    assert _resolve_asset_class("", "EURUSD=X") == AssetClass.FX
    assert _resolve_asset_class("", "EURUSD") == AssetClass.FX
    assert _resolve_asset_class("", "GC=F") == AssetClass.COMMODITY
    assert _resolve_asset_class("", "^GSPC") == AssetClass.INDEX
    assert _resolve_asset_class("", "US10Y") == AssetClass.BOND
    assert _resolve_asset_class("", "AAPL") == AssetClass.EQUITY
    # Explicit request still wins; unknown request still 400s (None).
    assert _resolve_asset_class("CRYPTO", "AAPL") == AssetClass.CRYPTO
    assert _resolve_asset_class("ALIEN", "AAPL") is None


# ── E2: paper market order gets a live `last:` hint ──────────────────────


@pytest.fixture
def paper_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.setenv("SHOWME_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")
    monkeypatch.setenv("SHOWME_BROKER", "paper")
    from showme.brokers import factory as factory_mod

    factory_mod._DYNAMIC.clear()
    factory_mod._LIVE.clear()
    for name in list(factory_mod._REGISTRY.keys()):
        if ":" in name:
            factory_mod._REGISTRY.pop(name, None)
    app = build_app(engine_root=None)
    return TestClient(app, headers={"X-ShowMe-Token": "test-token"})


def test_paper_market_order_gets_quote_hint(
    paper_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_quote(_symbol: str) -> dict[str, Any]:
        return {"symbol": "AAPL", "last": 123.5, "source": "fake"}

    monkeypatch.setattr("showme.quotes.fetch_quote_snapshot", fake_quote)
    resp = paper_client.post("/api/broker/orders", json={
        "symbol": "AAPL",
        "side": "buy",
        "quantity": 2,
        "order_type": "market",
        "confirmation_token": "paper",
    })
    assert resp.status_code == 200, resp.text
    order = resp.json()["order"]
    assert str(order["status"]).upper() == "FILLED"
    assert order["avg_fill_price"] == pytest.approx(123.5)


def test_paper_market_order_fails_honestly_without_quote(
    paper_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing_quote(_symbol: str) -> dict[str, Any]:
        raise RuntimeError("no provider")

    monkeypatch.setattr("showme.quotes.fetch_quote_snapshot", failing_quote)
    resp = paper_client.post("/api/broker/orders", json={
        "symbol": "AAPL",
        "side": "buy",
        "quantity": 2,
        "order_type": "market",
        "confirmation_token": "paper",
    })
    # No quote -> no fabricated price: the paper broker's own reject.
    assert resp.status_code == 400, resp.text
    assert "last:" in resp.json()["detail"]


def test_paper_market_order_hint_not_overridden_by_notes(
    paper_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def never_called(_symbol: str) -> dict[str, Any]:  # pragma: no cover
        raise AssertionError("quote must not be fetched when notes carry a hint")

    monkeypatch.setattr("showme.quotes.fetch_quote_snapshot", never_called)
    resp = paper_client.post("/api/broker/orders", json={
        "symbol": "AAPL",
        "side": "buy",
        "quantity": 2,
        "order_type": "market",
        "confirmation_token": "paper",
        "notes": "manual ticket last:200",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["order"]["avg_fill_price"] == pytest.approx(200.0)
