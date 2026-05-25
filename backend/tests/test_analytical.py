"""Tests for the showMe analytical core.

These tests MUST never touch the real ``~/Library/Application Support/showMe/``
directory — every test pins the DuckDB file to ``tmp_path`` via the
``analytical_db`` fixture, which monkeypatches both the pool's path
resolver (so a fresh pool would land in tmp) and the existing module-level
``POOL`` singleton (so the in-process pool already attached during import
also points at tmp).
"""
from __future__ import annotations

import datetime as dt
import time
from pathlib import Path

import polars as pl
import pyarrow as pa
import pytest

from showme.analytical import (
    audit as audit_mod,
    cache as cache_mod,
    duck as duck_mod,
    frames as frames_mod,
    snapshots as snapshots_mod,
)
from showme.analytical.duck import DuckPool


@pytest.fixture
def analytical_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the analytical DuckDB file to ``tmp_path/analytical.duckdb``.

    Any test that uses the cache, snapshot, audit, or pool helpers must take
    this fixture so the on-disk file lands in a per-test tmp dir, never in
    the user's real Application Support directory.
    """
    db_path = tmp_path / "analytical.duckdb"

    # 1) ``duck._data_dir`` is what *new* pools call — pin it to tmp.
    monkeypatch.setattr(duck_mod, "_data_dir", lambda: tmp_path)

    # 2) The module-level ``POOL`` was constructed at import time; swap it
    #    for a fresh pool so cache/snapshot/audit helpers (which call
    #    ``duck.connection()`` → ``POOL.connection()``) hit tmp too.
    fresh = DuckPool()
    monkeypatch.setattr(duck_mod, "POOL", fresh)

    yield db_path

    # Teardown: close any open handle so tmp_path can be removed cleanly.
    fresh.close()


# ---------------------------------------------------------------------------
# DuckPool / schema bootstrap
# ---------------------------------------------------------------------------


def test_pool_creates_schemas(analytical_db: Path) -> None:
    con = duck_mod.connection()
    # All four schemas must exist after first connection.
    schemas = {
        row[0]
        for row in con.execute(
            "SELECT schema_name FROM information_schema.schemata"
        ).fetchall()
    }
    assert {"cache", "snapshot", "audit", "research"}.issubset(schemas)

    # And the three concrete tables.
    tables = {
        (row[0], row[1])
        for row in con.execute(
            "SELECT table_schema, table_name FROM information_schema.tables"
        ).fetchall()
    }
    assert ("cache", "provider_responses") in tables
    assert ("snapshot", "pane_outputs") in tables
    assert ("audit", "events") in tables

    # File must materialize on disk under tmp_path.
    assert analytical_db.exists()


# ---------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------


def test_cache_roundtrip(analytical_db: Path) -> None:
    key = cache_mod.cache_key("yfinance", "history", ticker="AAPL", interval="1d")
    assert isinstance(key, str) and len(key) == 40  # sha1 hex

    payload_obj = {"rows": [{"close": 250.0}, {"close": 251.5}]}
    blob = cache_mod.dumps(payload_obj)

    cache_mod.write_cache(
        provider="yfinance",
        op="history",
        input_hash=key,
        payload=blob,
        mode="LIVE",
        ttl_seconds=3600,
        latency_ms=137,
    )

    got = cache_mod.read_cache("yfinance", "history", key)
    assert got is not None
    payload_back, mode, latency = got
    assert mode == "LIVE"
    assert latency == 137
    assert cache_mod.loads(payload_back) == payload_obj

    # Second write with same key must overwrite (no PK violation).
    cache_mod.write_cache(
        provider="yfinance",
        op="history",
        input_hash=key,
        payload=cache_mod.dumps({"rows": []}),
        mode="OFFLINE",
        ttl_seconds=60,
        latency_ms=4,
    )
    got2 = cache_mod.read_cache("yfinance", "history", key)
    assert got2 is not None
    assert cache_mod.loads(got2[0]) == {"rows": []}
    assert got2[1] == "OFFLINE"


def test_cache_expiry(analytical_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key = cache_mod.cache_key("polygon", "quote", symbol="MSFT")
    # Force the row's created/expires_at into the past so we don't have
    # to actually sleep through a TTL window.
    base = dt.datetime(2026, 1, 1, 12, 0, 0)
    monkeypatch.setattr(cache_mod, "_utcnow", lambda: base)
    cache_mod.write_cache(
        provider="polygon",
        op="quote",
        input_hash=key,
        payload=cache_mod.dumps({"price": 425.1}),
        mode="LIVE",
        ttl_seconds=5,  # expires at base + 5s
        latency_ms=22,
    )

    # Still fresh at base + 1s.
    monkeypatch.setattr(cache_mod, "_utcnow", lambda: base + dt.timedelta(seconds=1))
    assert cache_mod.read_cache("polygon", "quote", key) is not None

    # Stale at base + 30s — read returns None, eviction sweep removes 1 row.
    monkeypatch.setattr(cache_mod, "_utcnow", lambda: base + dt.timedelta(seconds=30))
    assert cache_mod.read_cache("polygon", "quote", key) is None
    assert cache_mod.evict_expired() == 1
    # And a second sweep is a no-op.
    assert cache_mod.evict_expired() == 0

    # ``ttl_seconds=None`` rows never expire.
    monkeypatch.setattr(cache_mod, "_utcnow", lambda: base)
    forever_key = cache_mod.cache_key("polygon", "quote", symbol="NVDA")
    cache_mod.write_cache(
        provider="polygon",
        op="quote",
        input_hash=forever_key,
        payload=cache_mod.dumps({"price": 1000.0}),
        mode="LIVE",
        ttl_seconds=None,
        latency_ms=10,
    )
    monkeypatch.setattr(
        cache_mod, "_utcnow", lambda: base + dt.timedelta(days=365)
    )
    assert cache_mod.read_cache("polygon", "quote", forever_key) is not None


# ---------------------------------------------------------------------------
# snapshots
# ---------------------------------------------------------------------------


def test_snapshot_roundtrip(analytical_db: Path) -> None:
    snap_id = snapshots_mod.save_snapshot(
        function_code="GP",
        inputs={"symbol": "AAPL", "interval": "1d"},
        payload={"close": [250.0, 251.5], "ts": ["2026-01-01", "2026-01-02"]},
        label="post-earnings",
    )
    assert isinstance(snap_id, str) and len(snap_id) == 32  # uuid4.hex

    fetched = snapshots_mod.get_snapshot(snap_id)
    assert fetched is not None
    assert fetched["function_code"] == "GP"
    assert fetched["inputs"] == {"symbol": "AAPL", "interval": "1d"}
    assert fetched["payload"]["close"] == [250.0, 251.5]
    assert fetched["label"] == "post-earnings"
    assert fetched["created_at"] is not None  # ISO string

    # Save another one for a different function, then test filtered list.
    snapshots_mod.save_snapshot("HP", {"symbol": "MSFT"}, {"x": 1})

    all_snaps = snapshots_mod.list_snapshots(limit=10)
    assert len(all_snaps) == 2

    gp_only = snapshots_mod.list_snapshots(function_code="GP", limit=10)
    assert len(gp_only) == 1
    assert gp_only[0]["function_code"] == "GP"

    # Missing id returns None, doesn't raise.
    assert snapshots_mod.get_snapshot("does-not-exist") is None


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------


def test_audit_event_lifecycle(analytical_db: Path) -> None:
    e1 = audit_mod.record_event(
        actor="user:nazmi",
        kind="bot.enable",
        target="bot:1",
        payload={"mode": "shadow"},
    )
    # Force a slight wall-clock gap so timestamp ordering is deterministic
    # even on filesystems that round to milliseconds.
    time.sleep(0.005)
    e2 = audit_mod.record_event(
        actor="user:nazmi",
        kind="strategy.save",
        target="strategy:rsi-bounce",
        payload={"version": 2},
    )
    time.sleep(0.005)
    e3 = audit_mod.record_event(
        actor="system",
        kind="bot.enable",
        target="bot:2",
        payload={"mode": "live"},
    )
    assert len({e1, e2, e3}) == 3  # all unique

    all_events = audit_mod.list_events(limit=10)
    assert len(all_events) == 3
    # Most-recent-first ordering by timestamp.
    assert all_events[0]["event_id"] == e3

    enables = audit_mod.list_events(kind="bot.enable", limit=10)
    assert {row["event_id"] for row in enables} == {e1, e3}
    assert enables[0]["payload"]["mode"] == "live"  # e3 first, descending


# ---------------------------------------------------------------------------
# frames — pure helpers, no DB needed
# ---------------------------------------------------------------------------


def test_frames_resample_1h_to_4h() -> None:
    # 8 hourly bars across one day.
    start = dt.datetime(2026, 1, 1, 0, 0)
    times = [start + dt.timedelta(hours=i) for i in range(8)]
    df = pl.DataFrame(
        {
            "time": times,
            "open": [float(i) for i in range(8)],
            "high": [float(i) + 0.5 for i in range(8)],
            "low": [float(i) - 0.5 for i in range(8)],
            "close": [float(i) + 0.25 for i in range(8)],
            "volume": [100 * (i + 1) for i in range(8)],
        }
    )
    out = frames_mod.resample_ohlcv(df, interval="4h", time_col="time")

    # 8 hours / 4h = 2 buckets.
    assert out.height == 2

    # Bucket 0 (00:00..03:59) — open=0, close=3.25, high=3.5, low=-0.5, vol=100+200+300+400=1000.
    row0 = out.row(0, named=True)
    assert row0["time"] == start
    assert row0["open"] == 0.0
    assert row0["close"] == 3.25
    assert row0["high"] == 3.5
    assert row0["low"] == -0.5
    assert row0["volume"] == 1000

    # Bucket 1 (04:00..07:59) — open=4, close=7.25, high=7.5, low=3.5, vol=500+600+700+800=2600.
    row1 = out.row(1, named=True)
    assert row1["time"] == start + dt.timedelta(hours=4)
    assert row1["open"] == 4.0
    assert row1["close"] == 7.25
    assert row1["high"] == 7.5
    assert row1["low"] == 3.5
    assert row1["volume"] == 2600


def test_frames_correlation_matrix_shape() -> None:
    # 5 timesteps across 3 symbols. AAPL & MSFT walk together; NVDA inverts AAPL.
    times = [dt.datetime(2026, 1, 1) + dt.timedelta(days=i) for i in range(5)]
    rows = []
    for i, t in enumerate(times):
        rows.append({"time": t, "symbol": "AAPL", "close": float(i)})
        rows.append({"time": t, "symbol": "MSFT", "close": float(i) * 2.0})
        rows.append({"time": t, "symbol": "NVDA", "close": float(4 - i)})
    df = pl.DataFrame(rows)

    out = frames_mod.correlation_matrix(
        df, value_col="close", key_col="symbol", time_col="time"
    )
    # Long form: 3 keys → 3×3 = 9 rows, ordered (key_a, key_b).
    assert out.height == 9
    assert set(out.columns) == {"key_a", "key_b", "correlation"}

    # Diagonal must be 1.0.
    diag = out.filter(pl.col("key_a") == pl.col("key_b"))
    assert diag.height == 3
    for v in diag["correlation"].to_list():
        assert v is not None
        assert abs(v - 1.0) < 1e-9

    # AAPL ↔ MSFT perfectly correlated (linear scale).
    pair = out.filter(
        (pl.col("key_a") == "AAPL") & (pl.col("key_b") == "MSFT")
    ).get_column("correlation").item()
    assert pair is not None
    assert abs(pair - 1.0) < 1e-9

    # AAPL ↔ NVDA perfectly anti-correlated.
    inv = out.filter(
        (pl.col("key_a") == "AAPL") & (pl.col("key_b") == "NVDA")
    ).get_column("correlation").item()
    assert inv is not None
    assert abs(inv + 1.0) < 1e-9


def test_frames_rolling_mean() -> None:
    df = pl.DataFrame({"close": [1.0, 2.0, 3.0, 4.0, 5.0]})
    out = frames_mod.rolling_mean(df, col="close", window=3)
    assert "close_rolling_mean" in out.columns
    values = out["close_rolling_mean"].to_list()
    # First two rows must be null (insufficient history), then 2, 3, 4.
    assert values[0] is None
    assert values[1] is None
    assert values[2] == pytest.approx(2.0)
    assert values[3] == pytest.approx(3.0)
    assert values[4] == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# Bonus: ensure the to_polars_from_arrow shim works as a smoke test for
# pyarrow integration (the spec listed it as a public helper).
# ---------------------------------------------------------------------------


def test_frames_to_polars_from_arrow_shim() -> None:
    table = pa.table({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    out = frames_mod.to_polars_from_arrow(table)
    assert isinstance(out, pl.DataFrame)
    assert out.columns == ["a", "b"]
    assert out["a"].to_list() == [1, 2, 3]
    assert out["b"].to_list() == ["x", "y", "z"]
