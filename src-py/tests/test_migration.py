"""Round 22 — Faz B state importer."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from showme.migration import _iso_from_epoch, import_state  # noqa: E402


def _sample_state() -> dict:
    return {
        "paper_balance": 8020.566,
        "daily_pnl": 0.0,
        "bot_start_time": 1746000000.0,
        "positions": {
            "MASKUSDT": {
                "symbol": "MASKUSDT",
                "side": "LONG",
                "quantity": 15435.07,
                "entry_price": 0.5183,
                "current_price": 0.5,
                "unrealized_pnl": -100.0,
                "realized_pnl": 0.0,
                "leverage": 10,
                "stop_loss": 0.42,
                "take_profit": 0.65,
                "trailing_stop_price": 0.45,
                "open_time": 1746090000.0,
            },
            "AVAUSDT": {
                "symbol": "AVAUSDT",
                "side": "LONG",
                "quantity": 24742,
                "entry_price": 0.2544,
                "open_time": 1746000123.0,
            },
        },
        "trade_history": [
            {
                "trade_id": "T1",
                "symbol": "BTCUSDT",
                "side": "LONG",
                "quantity": 0.1,
                "entry_price": 60000,
                "exit_price": 61000,
                "realized_pnl": 100,
                "open_time": 1745000000,
                "close_time": 1745100000,
            },
        ],
    }


def test_import_state_writes_positions_and_trades(tmp_path):
    db = tmp_path / "portfolio.db"
    summary = import_state(_sample_state(), db)
    assert summary.positions_imported == 2
    assert summary.trades_imported == 1
    assert summary.warnings == []
    assert summary.mode == "read_only"

    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT symbol, side, mode FROM positions").fetchall()
    assert sorted(r[0] for r in rows) == ["AVAUSDT", "MASKUSDT"]
    assert {r[2] for r in rows} == {"read_only"}


def test_import_state_idempotent(tmp_path):
    db = tmp_path / "portfolio.db"
    s = _sample_state()
    import_state(s, db)
    import_state(s, db)  # second call upserts, doesn't double
    conn = sqlite3.connect(db)
    n_pos = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
    n_trade = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    n_mig = conn.execute("SELECT COUNT(*) FROM migrations").fetchone()[0]
    assert n_pos == 2
    assert n_trade == 1
    assert n_mig == 2  # one row per call


def test_import_state_writable_mode_marks_rows(tmp_path):
    db = tmp_path / "portfolio.db"
    summary = import_state(_sample_state(), db, writable=True)
    assert summary.mode == "writable"
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT mode FROM positions").fetchall()
    assert {r[0] for r in rows} == {"writable"}


def test_import_state_skips_malformed_positions(tmp_path):
    db = tmp_path / "portfolio.db"
    state = {
        "positions": {"BAD": "not-a-dict", "GOOD": {"symbol": "GOOD", "side": "LONG"}},
    }
    summary = import_state(state, db)
    assert summary.positions_imported == 1
    assert summary.positions_skipped == 1
    assert any("BAD" in w for w in summary.warnings)


def test_iso_from_epoch_handles_seconds_and_ms_and_none():
    assert _iso_from_epoch(None) is None
    out_s = _iso_from_epoch(1746000000)
    out_ms = _iso_from_epoch(1746000000000)
    assert out_s and out_s.startswith("2025") or out_s.startswith("2026")
    assert out_ms == out_s
    # Bare integers below 10**8 → assumed to be a duration → None
    assert _iso_from_epoch(123) is None


def test_import_state_handles_list_positions_too(tmp_path):
    db = tmp_path / "portfolio.db"
    state = {
        "positions": [
            {"symbol": "AAA", "side": "LONG", "open_time": 1746000000},
            {"symbol": "BBB", "side": "SHORT", "open_time": 1746000010},
        ],
    }
    summary = import_state(state, db)
    assert summary.positions_imported == 2


def test_import_state_idempotency_with_real_state_json():
    """If showMe/engine is local, import the live state.json and re-run idempotency."""
    state_path = (
        Path.home() / "Desktop/Projeler/proje/showMe/engine/runtime/state.json"
    )
    if not state_path.exists():
        pytest.skip("showMe/engine not local")
    import tempfile
    state = json.loads(state_path.read_text())
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "portfolio.db"
        s1 = import_state(state, db)
        s2 = import_state(state, db)
        assert s1.positions_imported == s2.positions_imported
        # Re-run shouldn't grow position count.
        conn = sqlite3.connect(db)
        n = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
        assert n == s1.positions_imported
