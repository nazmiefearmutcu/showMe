"""BugHunt hunt-03 (py-engine-core) — WAVE 2 fix regression tests.

Pins the fixes from the 2026-09-23 bug hunt report
``hunt-03-py-engine-core.md`` (HNT-01 … HNT-22) for the engine core:
webauthn server-side verification, state-store locking, WS cache merge
semantics, off-loop gap-fill/whisper/alert work, paper fee accounting,
runtime-path unification, stuck-scan recovery and friends.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sqlite3
import sys
import threading
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from showme.engine.agents import llm_router as router_mod  # noqa: E402
from showme.engine.data import ws_manager as wsm  # noqa: E402
from showme.engine.data.market_cache import MarketCache  # noqa: E402
from showme.engine.data.market_data import MarketDataProvider  # noqa: E402
from showme.engine.persistence.state_store import StateStore  # noqa: E402
from showme.engine.portfolio.state import PortfolioState  # noqa: E402
from showme.engine.services import exec_monitor  # noqa: E402
from showme.engine.services import sentiment as sentiment_mod  # noqa: E402
from showme.engine.services import tax_lots  # noqa: E402
from showme.engine.services import webauthn_service  # noqa: E402
from showme.engine.services.bot_service import BotService  # noqa: E402
from showme.engine.services.world_events import window_meta  # noqa: E402
from showme.engine.trading.execution_engine import ExecutionEngine  # noqa: E402
from showme.engine.trading.position_manager import PositionManager  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """Every store in this suite resolves through app_paths → SHOWME_HOME."""
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    yield tmp_path


# ═══════════════════ HNT-01 / HNT-20: webauthn ═══════════════════

_AUTH_CHALLENGE = b"secret-auth-challenge"
_VALID_SIGNATURE = b"valid-signature"


class _FakeFido2Server:
    """Mirrors the fido2>=1.0 server API surface used by the service."""

    def __init__(self, rp=None):
        self.rp = rp

    def authenticate_begin(self, descs):
        state = {
            "challenge": _AUTH_CHALLENGE,
            "user_verification": "preferred",
        }
        return ({"publicKey": {"challenge": "opaque"}}, state)

    def authenticate_complete(self, state, credentials, credential_id, response):
        if state.get("challenge") != _AUTH_CHALLENGE:
            raise ValueError("challenge mismatch")
        known = {c.credential_id for c in credentials}
        if credential_id not in known:
            raise ValueError("unknown credential")
        if response.signature != _VALID_SIGNATURE:
            raise ValueError("signature verification failed")
        return True

    def register_complete(self, state, response):
        raise ValueError("bad attestation object")


@pytest.fixture
def fake_fido2(monkeypatch):
    fido2 = types.ModuleType("fido2")
    server_mod = types.ModuleType("fido2.server")
    webauthn_mod = types.ModuleType("fido2.webauthn")
    server_mod.Fido2Server = _FakeFido2Server
    webauthn_mod.PublicKeyCredentialRpEntity = lambda name, id: SimpleNamespace(
        name=name, id=id
    )
    webauthn_mod.PublicKeyCredentialDescriptor = lambda id: SimpleNamespace(id=id)

    def _aar(client_data=None, authenticator_data=None, signature=None):
        return SimpleNamespace(
            client_data=client_data,
            authenticator_data=authenticator_data,
            signature=signature,
        )

    webauthn_mod.AuthenticatorAssertionResponse = _aar
    webauthn_mod.CollectedClientData = lambda data: SimpleNamespace(raw=data)
    webauthn_mod.AuthenticatorData = lambda data: SimpleNamespace(raw=data)
    fido2.server = server_mod
    fido2.webauthn = webauthn_mod
    monkeypatch.setitem(sys.modules, "fido2", fido2)
    monkeypatch.setitem(sys.modules, "fido2.server", server_mod)
    monkeypatch.setitem(sys.modules, "fido2.webauthn", webauthn_mod)


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _seed_credential(user_id: str, cred_id: bytes = b"cred-1",
                     sign_count: int = 5) -> None:
    con = webauthn_service._db()
    con.execute(
        "INSERT OR REPLACE INTO credentials"
        "(user_id, credential_id, public_key, sign_count, created_at) VALUES (?,?,?,?,?)",
        [user_id, cred_id, b"pk-1", sign_count, int(time.time())],
    )
    con.commit()
    con.close()


def _sign_count(user_id: str) -> int:
    con = webauthn_service._db()
    row = con.execute(
        "SELECT sign_count FROM credentials WHERE user_id = ?", [user_id]
    ).fetchone()
    con.close()
    return int(row[0]) if row else 0


def _sign_counts(user_id: str) -> dict[str, int]:
    con = webauthn_service._db()
    rows = con.execute(
        "SELECT credential_id, sign_count FROM credentials WHERE user_id = ?", [user_id]
    ).fetchall()
    con.close()
    return {r[0].hex(): int(r[1]) for r in rows}


def _pending_auth_rows(user_id: str) -> int:
    con = webauthn_service._db()
    n = con.execute(
        "SELECT COUNT(*) FROM pending WHERE user_id = ? AND kind = 'auth'", [user_id]
    ).fetchone()[0]
    con.close()
    return int(n)


def _valid_assertion(cred_id: bytes = b"cred-1") -> dict:
    return {
        "id": _b64u(cred_id),
        "rawId": _b64u(cred_id),
        "type": "public-key",
        "response": {
            "clientDataJSON": _b64u(b'{"type":"webauthn.get"}'),
            "authenticatorData": _b64u(b"auth-data"),
            "signature": _b64u(_VALID_SIGNATURE),
            "userHandle": None,
        },
    }


def test_begin_authentication_persists_server_state(fake_fido2):
    """HNT-01: the authenticate_begin state (challenge + flags) must be
    persisted so complete_authentication can run real verification."""
    _seed_credential("alice")
    res = webauthn_service.begin_authentication("alice")
    assert "options" in res
    con = webauthn_service._db()
    row = con.execute(
        "SELECT challenge, state_json FROM pending WHERE user_id = 'alice'"
    ).fetchone()
    con.close()
    assert row is not None
    assert row[0] == _AUTH_CHALLENGE
    state = json.loads(row[1])
    # bytes challenge survives the b64 round-trip tag
    assert base64.b64decode(state["challenge"]["__b64__"]) == _AUTH_CHALLENGE
    assert state["user_verification"] == "preferred"


def test_forged_ok_flag_alone_is_rejected(fake_fido2):
    """HNT-01 CRITICAL: a client posting {"ok": true} without a valid
    assertion must NOT authenticate."""
    _seed_credential("mallory", sign_count=5)
    webauthn_service.begin_authentication("mallory")

    res = webauthn_service.complete_authentication("mallory", {"ok": True})

    assert "authenticated" not in res
    assert "error" in res
    # no side effects: challenge kept for a legitimate retry, counter intact
    assert _sign_count("mallory") == 5
    assert _pending_auth_rows("mallory") == 1


def test_wrong_signature_is_rejected(fake_fido2):
    _seed_credential("mallory", sign_count=5)
    webauthn_service.begin_authentication("mallory")

    forged = _valid_assertion()
    forged["response"]["signature"] = _b64u(b"evil-forged-signature")
    res = webauthn_service.complete_authentication("mallory", forged)

    assert "error" in res
    assert _sign_count("mallory") == 5
    assert _pending_auth_rows("mallory") == 1


def test_valid_assertion_authenticates_and_bumps_counter(fake_fido2):
    _seed_credential("alice", sign_count=5)
    webauthn_service.begin_authentication("alice")

    res = webauthn_service.complete_authentication("alice", _valid_assertion())

    assert res.get("authenticated") is True
    assert res["user_id"] == "alice"
    assert _sign_count("alice") == 6
    assert _pending_auth_rows("alice") == 0


def test_authentication_bumps_only_the_authenticating_credential(fake_fido2):
    """FR-03: the sign_count UPDATE must be scoped to the credential that
    authenticated — the old statement bumped EVERY credential the user
    owns on every login."""
    _seed_credential("dana", cred_id=b"cred-1", sign_count=5)
    _seed_credential("dana", cred_id=b"cred-2", sign_count=9)
    webauthn_service.begin_authentication("dana")

    res = webauthn_service.complete_authentication("dana", _valid_assertion(b"cred-2"))

    assert res.get("authenticated") is True
    counts = _sign_counts("dana")
    assert counts[b"cred-1".hex()] == 5
    assert counts[b"cred-2".hex()] == 10


def test_authentication_stores_assertion_counter(fake_fido2):
    """FR-03: when the assertion carries an authenticator counter, that
    real value is persisted (the baseline fido2's clone detector compares
    against) instead of a blind +1."""
    _seed_credential("erin", cred_id=b"cred-1", sign_count=3)
    webauthn_service.begin_authentication("erin")
    # Make the fake AuthenticatorData carry a counter like real fido2's.
    sys.modules["fido2.webauthn"].AuthenticatorData = (
        lambda data: SimpleNamespace(raw=data, counter=12)
    )

    res = webauthn_service.complete_authentication("erin", _valid_assertion())

    assert res.get("authenticated") is True
    assert _sign_counts("erin")[b"cred-1".hex()] == 12


def test_complete_authentication_without_pending_is_error(fake_fido2):
    _seed_credential("alice")
    res = webauthn_service.complete_authentication("alice", _valid_assertion())
    assert "error" in res


def test_complete_registration_closes_connection_on_verification_error(fake_fido2, monkeypatch):
    """HNT-20: register_complete raising must not leak the sqlite conn."""
    con = webauthn_service._db()
    con.execute(
        "INSERT INTO pending(user_id, challenge, kind, created_at) VALUES (?,?,?,?)",
        ["bob", b"reg-challenge", "register", int(time.time())],
    )
    con.commit()
    con.close()

    closed = {"n": 0}
    real_db = webauthn_service._db

    class _CountingConn:
        def __init__(self, inner):
            self._inner = inner

        def execute(self, *a, **k):
            return self._inner.execute(*a, **k)

        def commit(self):
            return self._inner.commit()

        def close(self):
            closed["n"] += 1
            return self._inner.close()

    monkeypatch.setattr(webauthn_service, "_db", lambda: _CountingConn(real_db()))
    res = webauthn_service.complete_registration("bob", {"response": {}})

    assert "error" in res
    assert closed["n"] == 1, "connection must be closed when verification raises"


# ═══════════════════ HNT-02: exec_monitor connection leak ═══════════════════


def test_list_parents_uses_a_single_connection():
    opens = {"n": 0}
    real_connect = exec_monitor._connect

    def counting_connect():
        opens["n"] += 1
        return real_connect()

    orig = exec_monitor._connect
    exec_monitor._connect = counting_connect
    try:
        exec_monitor.open_parent("P-1", symbol="BTCUSDT", side="BUY", target_qty=10)
        exec_monitor.record_slice("P-1", slice_idx=0, qty=5, avg_px=100.0)
        exec_monitor.record_slice("P-1", slice_idx=1, qty=5, avg_px=101.0)
        rows = exec_monitor.list_parents(limit=10)
    finally:
        exec_monitor._connect = orig

    assert len(rows) == 1
    assert rows[0]["metrics"]["n_slices"] == 2
    # open(1) + 2 slices + list(1) — the old code opened one EXTRA
    # connection per parent row and never closed it.
    assert opens["n"] == 4


# ═══════════════════ HNT-03: state_store locking ═══════════════════


def test_state_store_concurrent_updates_never_tear_the_file():
    store = StateStore("runtime/state.json")
    store.load()

    def worker(i: int) -> None:
        for j in range(25):
            store.update(**{f"key_{i}_{j}": j})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    data = json.loads(Path("runtime/state.json").read_text())
    written = [k for k in data if k.startswith("key_")]
    assert len(written) == 100, "a torn or racy save lost updates"
    # no per-thread tmp residue left behind
    leftovers = [p.name for p in Path("runtime").glob("state.json.tmp*")]
    assert leftovers == []


def test_state_store_tmp_file_is_thread_specific():
    store = StateStore("runtime/state.json")
    seen: dict[int, str] = {}

    def worker() -> None:
        seen[threading.get_ident()] = "alive"
        store.update(marker=threading.get_ident())

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert store.get("marker") in seen  # the other thread's update landed


# ═══════════════════ HNT-04: market_cache candle merge ═══════════════════


def _candle(ot: int, close: float = 1.0) -> dict:
    return {"open_time": ot, "open": 1.0, "high": 1.0, "low": 1.0,
            "close": close, "volume": 1.0}


def _open_times(cache: MarketCache, symbol: str = "S", tf: str = "1m") -> list[int]:
    df = cache.get_ohlcv(symbol, tf)
    return [int(pd.Timestamp(t).value // 1_000_000) for t in df["open_time"]]


def test_update_candle_merges_gap_fill_overlap_without_duplicates():
    cache = MarketCache()
    for ot in [1, 2, 3, 4, 5]:
        cache.update_candle("S", "1m", _candle(ot))

    # live tick on the forming candle → in-place replace
    cache.update_candle("S", "1m", _candle(5, close=9.0))

    # REST gap-fill batch overlapping the tail: [3, 4, 5, 6, 7]
    for ot in [3, 4, 5, 6, 7]:
        cache.update_candle("S", "1m", _candle(ot, close=7.0))

    assert _open_times(cache) == [1, 2, 3, 4, 5, 6, 7]
    df = cache.get_ohlcv("S", "1m")
    assert list(df["close"]) == [1.0, 1.0, 7.0, 7.0, 7.0, 7.0, 7.0]


def test_update_candle_inserts_missing_interior_timestamp_in_order():
    cache = MarketCache()
    for ot in [1, 2, 5]:
        cache.update_candle("S", "1m", _candle(ot))
    cache.update_candle("S", "1m", _candle(3))
    assert _open_times(cache) == [1, 2, 3, 5]


def test_update_candle_drops_rows_older_than_the_window():
    cache = MarketCache()
    for ot in [10, 11, 12]:
        cache.update_candle("S", "1m", _candle(ot))
    cache.update_candle("S", "1m", _candle(9))
    assert _open_times(cache) == [10, 11, 12]


def test_update_candle_inserts_gap_row_into_full_maxlen_buffer():
    """FR-02: ``deque.insert`` on a buffer already at ``maxlen`` raises
    IndexError — a mid-window gap row used to kill the rest of the
    gap-fill batch exactly in the steady state HNT-04 targets. The
    window slides: the oldest candle drops, order stays sorted."""
    cache = MarketCache(max_candles=3)
    for ot in [10, 12, 13]:
        cache.update_candle("S", "1m", _candle(ot))
    cache.update_candle("S", "1m", _candle(11))
    assert _open_times(cache) == [11, 12, 13]


# ═══════════════════ HNT-05 + HNT-11: ws_manager ═══════════════════


class _GapStore:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.thread: int | None = None

    def write_candle(self, row: dict) -> None:
        self.thread = threading.get_ident()
        self.rows.append(row)


class _GapRest:
    def __init__(self, now_ms: int) -> None:
        self.now_ms = now_ms
        self.thread: int | None = None

    def get_klines(self, symbol=None, interval=None, limit=None):
        self.thread = threading.get_ident()
        base = self.now_ms - 10 * 60_000
        return [
            [base + i * 60_000, "1", "2", "0.5", "1.5", "10",
             base + i * 60_000, "20", 3, "5", "7", "0"]
            for i in range(10)
        ]


async def test_gap_fill_runs_rest_and_store_off_the_loop():
    now_ms = int(time.time() * 1000)
    store = _GapStore()
    rest = _GapRest(now_ms)
    cache = MarketCache()
    mgr = wsm.WSManager(symbols=["BTCUSDT"], timeframes=["1m"],
                        cache=cache, store=store, rest_client=rest)  # type: ignore[arg-type]
    mgr.last_kline_ms[("BTCUSDT", "1m")] = now_ms - 10 * 60_000

    await mgr._gap_fill_on_reconnect(["btcusdt@kline_1m"])

    loop_thread = threading.get_ident()
    assert rest.thread is not None and rest.thread != loop_thread
    assert store.thread is not None and store.thread != loop_thread
    assert mgr.health["gap_fills"] == 1
    assert len(store.rows) == 10
    # merged cache stays chronological (HNT-04 integration)
    assert _open_times(cache, "BTCUSDT", "1m") == sorted(
        r["open_time"] for r in store.rows
    )


async def test_ws_connected_health_tracks_current_shards(monkeypatch):
    """HNT-11: health['connected'] must be "shards connected right now",
    not a cumulative connect counter."""

    class _FakeSocket:
        async def __aiter__(self):
            while True:
                await asyncio.sleep(3600)
                yield "{}"

    class _FakeConnect:
        def __init__(self, url, **kw):
            pass

        async def __aenter__(self):
            return _FakeSocket()

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(wsm, "websockets", SimpleNamespace(connect=_FakeConnect))
    mgr = wsm.WSManager(symbols=["BTCUSDT"], timeframes=["1m"],
                        cache=MarketCache(), store=None, rest_client=None)

    task = asyncio.create_task(mgr._run_shard(mgr.shards[0], 0))
    await asyncio.sleep(0.1)
    during = mgr.get_health()["connected"]
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert during == 1
    # the old cumulative counter stayed >0 forever after a disconnect
    assert mgr.get_health()["connected"] == 0


# ═══════════════════ HNT-06: whisper off-loop ═══════════════════


async def test_transcribe_tier1_runs_whisper_off_the_loop(tmp_path, monkeypatch):
    from showme.engine.services import transcription

    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFF" + bytes(range(64)))  # unique → cache miss

    main_thread = threading.get_ident()
    seen: dict[str, int] = {}

    def fake_transcribe(path, language=None):
        seen["thread"] = threading.get_ident()
        return {"text": "hello world", "language": "en", "segments": []}

    fake_whisper = SimpleNamespace(
        load_model=lambda name: SimpleNamespace(transcribe=fake_transcribe)
    )
    monkeypatch.setitem(sys.modules, "whisper", fake_whisper)

    res = await transcription.transcribe(audio, use_singleton=False)

    assert res["text"] == "hello world"
    assert res["model"] == "whisper:base"
    assert seen["thread"] != main_thread, (
        "whisper load+transcribe must run in a worker thread, not on the loop"
    )


# ═══════════════════ HNT-07: paper fee accounting ═══════════════════


def _paper_engine(start_balance: float = 10_000.0, fee_pct: float = 0.001):
    from showme.engine.trading.order_models import TradeAction

    config = {"mode": "paper", "risk": {"stop_loss_pct": 0.02, "take_profit_pct": 0.04},
              "paper": {"starting_balance": start_balance, "fee_pct": fee_pct}}
    pm = PositionManager(config)
    return ExecutionEngine(config, None, pm), pm, TradeAction  # type: ignore[arg-type]


def test_paper_round_trip_charges_entry_fee_once():
    """HNT-07: a full spot round trip changes the balance by
    gross_pnl − entry_fee − exit_fee (the old close fee re-charged the
    entry leg, draining one extra entry-fee per round trip)."""
    engine, pm, TradeAction = _paper_engine(fee_pct=0.001)

    engine._execute_paper(TradeAction.OPEN_LONG, "BTCUSDT", 1.0, 100.0, "o", leverage=1)
    close = engine._execute_paper(
        TradeAction.CLOSE_LONG, "BTCUSDT", 1.0, 110.0, "c", leverage=1
    )
    assert close["executed"] is True

    record = pm.trade_history[-1]
    gross = (110.0 - 100.0) * 1.0
    entry_fee = 100.0 * 1.0 * 0.001
    exit_fee = 110.0 * 1.0 * 0.001
    assert record.fee == pytest.approx(exit_fee)
    assert record.pnl == pytest.approx(gross - exit_fee)
    assert engine.paper_balance == pytest.approx(10_000.0 + gross - entry_fee - exit_fee)


# ═══════════════════ HNT-08: portfolio runtime path ═══════════════════


def test_portfolio_state_resolves_runtime_via_app_paths(_isolated_home: Path):
    from showme.engine.portfolio.state import _runtime_path

    resolved = _runtime_path("runtime/portfolio.json")
    assert resolved == _isolated_home / "runtime" / "portfolio.json"
    # absolute paths pass through untouched
    absolute = _isolated_home / "elsewhere" / "book.json"
    assert _runtime_path(absolute) == absolute

    ps = PortfolioState("runtime/portfolio.json")
    ps.save()
    assert (_isolated_home / "runtime" / "portfolio.json").exists()
    # no cwd-relative parallel tree
    assert not Path("runtime").exists() or Path("runtime").resolve() == (
        _isolated_home / "runtime"
    ).resolve()


# ═══════════════════ HNT-09: stuck scan recovery ═══════════════════


class _BotSkeleton:
    """Shared BotService skeleton built via __new__ (offline, no threads)."""

    def __init__(self, tmp_path: Path):  # noqa: D107
        self.svc = BotService.__new__(BotService)
        self.svc._auto_scan_interval = 600
        self.svc.market_cache = None
        self.svc.market_store = None
        self.svc.config = {
            "_config_path": str(tmp_path / "nope.yaml"),
            "dashboard_status_path": str(tmp_path / "ds.json"),
        }
        self.svc._last_auto_scan_time = 0.0
        self.svc._scanning_active = False
        self.svc._scan_threads = []
        self.svc._scan_started_monotonic = None
        self.svc._scan_lock = threading.Lock()


def test_scan_is_stale_detects_old_progress_started_at():
    sk = _BotSkeleton(Path.cwd())
    svc = sk.svc
    runtime_dir = Path(svc.config["dashboard_status_path"]).parent
    runtime_dir.mkdir(parents=True, exist_ok=True)
    old = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    (runtime_dir / "auto_scan_progress.json").write_text(
        json.dumps({"scanning": True, "started_at": old})
    )
    svc._scanning_active = True
    assert svc._scan_is_stale() is True

    fresh = datetime.now(timezone.utc).isoformat()
    (runtime_dir / "auto_scan_progress.json").write_text(
        json.dumps({"scanning": True, "started_at": fresh})
    )
    svc._scan_started_monotonic = time.time()
    assert svc._scan_is_stale() is False


def test_auto_scan_force_resets_stale_scanning_state(monkeypatch):
    sk = _BotSkeleton(Path.cwd())
    svc = sk.svc
    # a scan "in progress" whose start marker is 3h old + a live thread
    svc._scanning_active = True
    svc._scan_started_monotonic = time.time() - 3 * 3600
    blocker = threading.Thread(target=lambda: time.sleep(30), daemon=True)
    blocker.start()
    svc._scan_threads = [blocker]
    svc._is_manual_scan_active = lambda: False  # type: ignore[assignment]

    launched: dict[str, Any] = {}

    class _FakeThread:
        def __init__(self, target=None, daemon=None, name=None):
            launched[name] = target

        def start(self):
            pass

    monkeypatch.setattr(threading, "Thread", _FakeThread)
    try:
        svc._auto_scan_market()
    finally:
        blocker.join(timeout=0.1)

    # the stale batch was force-reset and a NEW coordinator was launched —
    # the old code returned early forever while the thread hung.
    assert "scan-coordinator" in launched
    assert svc._scanning_active is True  # re-marked by the fresh batch
    assert svc._scan_started_monotonic is None or svc._scan_started_monotonic > 0


def test_progress_writer_caps_scan_lifetime_shared_constant():
    """The writer deadline uses the same _SCAN_STALE_AFTER_SECONDS the
    stale-reset checks (kept in sync by construction)."""
    assert BotService._SCAN_STALE_AFTER_SECONDS == 2 * 3600


# ═══════════════════ HNT-10: LOT_SIZE step flooring ═══════════════════


def test_adjust_quantity_exact_step_multiple_is_not_floored_low():
    engine, _pm, _ta = _paper_engine()
    info = {"filters": [{"filterType": "LOT_SIZE", "minQty": "0.0001",
                         "stepSize": "0.1"}]}
    # 0.3 / 0.1 == 2.999… in binary float — pure int() floored this to 0.2.
    assert engine._adjust_quantity(0.3, info) == pytest.approx(0.3)
    assert engine._adjust_quantity(1.0, info) == pytest.approx(1.0)
    # non-multiples still floor to the step below
    assert engine._adjust_quantity(0.34, info) == pytest.approx(0.3)


# ═══════════════════ HNT-12: graceful shutdown ═══════════════════


def test_shutdown_stops_ws_manager_and_closes_market_store():
    svc = BotService.__new__(BotService)
    stopped = {"ws": False, "store": False, "state": False}

    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()

    class _WS:
        async def stop(self):
            stopped["ws"] = True

    class _Store:
        def close(self):
            stopped["store"] = True

    class _StateStore:
        def save(self):
            stopped["state"] = True

    class _Exporter:
        def export_stopped(self, *a, **k):
            pass

    svc.ws_manager = _WS()
    svc._ws_loop = loop
    svc.market_store = _Store()
    svc.state_store = _StateStore()
    svc.status_exporter = _Exporter()
    svc.config = {}

    try:
        svc._shutdown()
    finally:
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=5)
        loop.close()

    assert stopped == {"ws": True, "store": True, "state": True}


# ═══════════════════ HNT-13: tax_lots UTC + WAL ═══════════════════


def test_realized_summary_year_boundary_is_utc():
    con = tax_lots._db()
    # 2026-12-31 23:00 UTC — belongs to 2026 only under UTC boundaries.
    ts = int(datetime(2026, 12, 31, 23, 0, tzinfo=timezone.utc).timestamp())
    con.execute(
        "INSERT INTO realized(ts, symbol, sold_lot, qty, sale_price, "
        "cost_basis, realized_pnl, holding_days, term) VALUES (?,?,?,?,?,?,?,?,?)",
        [ts, "BTCUSDT", "lot-1", 1.0, 100.0, 90.0, 10.0, 5, "short"],
    )
    con.commit()
    con.close()

    summary = tax_lots.realized_summary(year=2026)
    assert summary["short"]["n"] == 1
    assert summary["total_pnl"] == pytest.approx(10.0)

    # open_sqlite → WAL journal mode on the ledger file
    check = sqlite3.connect(str(tax_lots._db_file()))
    mode = check.execute("PRAGMA journal_mode").fetchone()[0]
    check.close()
    assert str(mode).lower() == "wal"


# ═══════════════════ HNT-14: risk monitor bg tasks ═══════════════════


async def test_risk_fire_keeps_strong_task_reference():
    from showme.engine.services.risk_monitor import RiskMonitor

    done: list[str] = []

    async def notifier(evt):
        await asyncio.sleep(0.02)
        done.append(evt["subkind"])

    rm = RiskMonitor(notifiers=[notifier])
    rm._fire("drawdown", "portfolio.drawdown <= -10%", {"v": -11})
    await asyncio.sleep(0.15)

    assert done == ["drawdown"], "fire-and-forget task was GC'd before finishing"
    assert not rm._bg, "done callback must discard finished tasks"


# ═══════════════════ HNT-15: alert engine off-loop + timeouts ═══════════════════


async def test_alert_fire_runs_sync_notifier_off_the_loop():
    from showme.engine.services.alert_engine import AlertEngine

    engine = AlertEngine()
    loop_thread = threading.get_ident()
    seen: dict[str, Any] = {}

    def sync_notifier(event):
        seen["thread"] = threading.get_ident()
        seen["event"] = event
        return "sent"

    engine.notifiers.append(sync_notifier)
    await engine._fire(
        {"id": "a1", "condition": "c", "actions": []}, {"v": 1},
        datetime.now(timezone.utc),
    )

    assert seen["thread"] != loop_thread, "sync notifier ran on the event loop"
    assert seen["event"]["alert_id"] == "a1"


async def test_resolve_quote_bounds_each_source_with_wait_for():
    from showme.engine.services.alert_engine import AlertEngine

    engine = AlertEngine()

    class _Hang:
        timeout_seconds = 0.05

        async def fetch(self, req):
            await asyncio.Event().wait()  # never resolves
            return None

    class _Fast:
        async def fetch(self, req):
            return SimpleNamespace(last=42.0)

    engine.deps = SimpleNamespace(
        yfinance=_Hang(), finnhub=None, alphavantage=None, exchangerate_host=_Fast()
    )
    inst = SimpleNamespace(asset_class=SimpleNamespace(value="EQUITY"))

    t0 = time.monotonic()
    q = await engine._resolve_quote(inst)

    assert q is not None and q.last == 42.0
    assert time.monotonic() - t0 < 5, "a hung adapter froze the quote resolution"


# ═══════════════════ HNT-16: llm router client cache ═══════════════════


class _FakeAsyncAnthropic:
    instances: list["_FakeAsyncAnthropic"] = []

    def __init__(self, api_key=None):
        self.api_key = api_key
        self.closed = False
        self.messages = SimpleNamespace(create=self._create)
        _FakeAsyncAnthropic.instances.append(self)

    async def _create(self, **kw):
        return SimpleNamespace(
            content=[SimpleNamespace(text="hi")],
            usage=SimpleNamespace(input_tokens=3, output_tokens=2),
        )

    async def close(self):
        self.closed = True


async def test_llm_router_reuses_singleton_client(monkeypatch):
    fake_mod = SimpleNamespace(AsyncAnthropic=_FakeAsyncAnthropic)
    monkeypatch.setitem(sys.modules, "anthropic", fake_mod)
    _FakeAsyncAnthropic.instances.clear()

    saved = router_mod._ANTHROPIC_CLIENT
    router_mod._ANTHROPIC_CLIENT = None
    try:
        r = router_mod.LLMRouter()
        r.anthropic_key = "key-1"
        req = router_mod.LLMRequest(role="t", user="u")
        text, _i, _o = await r._call_anthropic("claude-haiku", req)
        assert text == "hi"
        await r._call_anthropic("claude-haiku", req)
        # same key → the ONE cached client is reused, not rebuilt per call
        assert len(_FakeAsyncAnthropic.instances) == 1

        # key rotation rebuilds (and retires the old client's sockets)
        r.anthropic_key = "key-2"
        await r._call_anthropic("claude-haiku", req)
        assert len(_FakeAsyncAnthropic.instances) == 2
        await asyncio.sleep(0)  # let the retire task run

        # lifespan close helper closes and clears the cache
        await router_mod.aclose_clients()
        assert all(c.closed for c in _FakeAsyncAnthropic.instances)
        assert router_mod._ANTHROPIC_CLIENT is None
    finally:
        router_mod._ANTHROPIC_CLIENT = saved


# ═══════════════════ HNT-17: sentiment keyword TTL ═══════════════════


def test_keyword_fallback_ttl_retries_upper_tiers(monkeypatch):
    # make transformers and nltk unimportable → every tier fails → keyword
    monkeypatch.setitem(sys.modules, "transformers", None)
    monkeypatch.setitem(sys.modules, "nltk", None)

    saved = (
        sentiment_mod._MODEL,
        sentiment_mod._MODEL_KIND,
        sentiment_mod._VADER,
        sentiment_mod._KEYWORD_SINCE,
    )
    try:
        sentiment_mod._MODEL = None
        sentiment_mod._MODEL_KIND = None
        sentiment_mod._VADER = None
        sentiment_mod._KEYWORD_SINCE = None

        model, kind = sentiment_mod._load_model()
        assert kind == "keyword"
        first_since = sentiment_mod._KEYWORD_SINCE
        assert first_since is not None

        # inside the TTL → stays latched, no tier re-attempt
        model, kind = sentiment_mod._load_model()
        assert kind == "keyword"
        assert sentiment_mod._KEYWORD_SINCE == first_since

        # TTL expired → the latch is dropped and the tiers are retried
        sentiment_mod._KEYWORD_SINCE = time.monotonic() - (
            sentiment_mod._KEYWORD_TTL_SECONDS + 1
        )
        model, kind = sentiment_mod._load_model()
        assert kind == "keyword"  # still offline, but it RETRIED
        assert sentiment_mod._KEYWORD_SINCE > first_since
    finally:
        (
            sentiment_mod._MODEL,
            sentiment_mod._MODEL_KIND,
            sentiment_mod._VADER,
            sentiment_mod._KEYWORD_SINCE,
        ) = saved


# ═══════════════════ HNT-19: world_events window_meta ═══════════════════


def test_window_meta_newest_past_skips_undated_rows():
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    rows = [
        {  # dated, newest past row
            "when_utc": "2026-05-31T10:00:00+00:00",
            "undated": False,
            "seconds_to_event": -93600,
            "impact": "medium",
        },
        {  # undated wire copy leads split_window's past list
            "when_utc": None,
            "undated": True,
            "seconds_to_event": 0,
            "impact": "low",
        },
    ]
    meta = window_meta(rows, now=now, days_ahead=1.0, days_back=7.0)
    assert meta["past_count"] == 2
    # the old past[0] lookup returned the undated row's None
    assert meta["newest_past_utc"] == "2026-05-31T10:00:00+00:00"


# ═══════════════════ HNT-21: market_data acceptance floor ═══════════════════


class _StaticCache:
    def __init__(self, df):
        self.df = df

    def get_ohlcv(self, symbol, timeframe, n=500):
        return self.df

    def get_funding(self, symbol):
        return None


class _CountingRest:
    def __init__(self):
        self.kline_calls = 0

    def get_klines(self, symbol, interval, limit):
        self.kline_calls += 1
        return []

    def get_ticker_price(self, symbol):
        return 123.0


def _fresh_frame(rows: int) -> pd.DataFrame:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    times = [now_ms - (rows - 1 - i) * 3_600_000 for i in range(rows)]
    return pd.DataFrame({"open_time": pd.to_datetime(times, unit="ms"),
                         "close": [1.0] * rows})


def test_small_candle_limit_still_uses_ws_cache():
    """candle_limit=30 → 25 fresh cached rows must be accepted (the old
    fixed 50-row floor forced every cycle back to REST)."""
    cfg = {"timeframe": "1h", "candle_limit": 30,
           "data_pipeline": {"use_ws_cache": True}}
    rest = _CountingRest()
    mdp = MarketDataProvider(rest, cfg, cache=_StaticCache(_fresh_frame(25)), store=None)
    out = mdp.get_ohlcv("BTCUSDT")
    assert out is not None and len(out) == 25
    assert rest.kline_calls == 0, "cache frame below the old fixed floor went to REST"


def test_large_candle_limit_still_rejects_thin_cache():
    cfg = {"timeframe": "1h", "candle_limit": 200,
           "data_pipeline": {"use_ws_cache": True}}
    rest = _CountingRest()
    mdp = MarketDataProvider(rest, cfg, cache=_StaticCache(_fresh_frame(25)), store=None)
    mdp.get_ohlcv("BTCUSDT")
    assert rest.kline_calls == 1, "thin cache must still fall through to REST"


# ═══════════════════ HNT-18 / HNT-22: bot_service ═══════════════════


class _Side:
    def __init__(self, value):
        self.value = value


class _Pos:
    def __init__(self, side="LONG", qty=2.0, entry=100.0, lev=1):
        self.side = _Side(side)
        self.quantity = qty
        self.entry_price = entry
        self.leverage = lev


class _PM:
    def __init__(self, positions=None):
        self.positions = positions or {}
        self.total_realized_pnl = 0.0
        self.trade_history = []
        self.config = {}
        self.risk_config = {}

    def get_position(self, sym):
        return self.positions.get(sym)

    def get_positions_dict(self):
        return {k: {"x": 1} for k in self.positions}


class _EE:
    def __init__(self):
        self.paper_balance = 4242.0
        self.mode = "paper"
        self.paper_config = {}
        self.paper_fee_pct = 0.001
        self.config = {}


class _ReloadClient:
    def __init__(self):
        self.mode = "paper"
        self.market_type = "spot"
        self.init_calls = 0

    def initialize(self):
        self.init_calls += 1


def test_apply_config_drops_signal_service_caches(monkeypatch):
    from showme.engine.services import bot_service as bs

    for name in ("SignalService", "ConsensusEngine", "LeverageManager",
                 "DecisionEngine", "MarketDataProvider"):
        monkeypatch.setattr(
            bs, name, type("F" + name, (), {"__init__": lambda self, *a, **k: None})
        )
    svc = BotService.__new__(BotService)
    svc._auto_scan_interval = 600
    svc.market_cache = None
    svc.market_store = None
    svc.config = {"mode": "paper", "market_type": "spot", "timeframe": "1h",
                  "polling_interval_seconds": 60, "risk": {},
                  "paper": {"fee_pct": 0.0005}}
    svc.binance_client = _ReloadClient()
    svc.position_manager = _PM()
    svc.execution_engine = _EE()

    # caches built from the OLD config
    svc._signal_service_cache = {"1h": object()}
    stale_consensus = object()
    svc._consensus_engine_cache = stale_consensus

    svc._apply_config(dict(svc.config))

    assert svc._signal_service_cache == {}
    assert svc._consensus_engine_cache is not stale_consensus


def test_fetch_all_position_prices_prefers_fresh_bulk_price():
    svc = BotService.__new__(BotService)
    svc.position_manager = _PM({"AAA": _Pos()})

    class _Client:
        def __init__(self, prices):
            self.prices = prices

        def get_all_prices(self):
            return self.prices

    class _SymbolCtrl:
        def get_current_symbol(self):
            return "AAA"

    svc.binance_client = _Client({"AAA": 105.0, "BBB": 50.0})
    svc.symbol_controller = _SymbolCtrl()
    svc._last_price = 100.0  # cycle-start price

    out = svc._fetch_all_position_prices()
    assert out["AAA"] == 105.0, "stale cycle price overwrote the fresh bulk price"

    # fallback: bulk fetch missing the active symbol keeps the cycle price
    svc.binance_client = _Client({"BBB": 50.0})
    out = svc._fetch_all_position_prices()
    assert out["AAA"] == 100.0
