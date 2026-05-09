"""Round 25 — read-side state API over portfolio.db."""
from __future__ import annotations

from pathlib import Path

import pytest

from showme.migration import import_state
from showme.state_api import list_migrations, list_positions, list_trades


@pytest.fixture()
def seeded_db(tmp_path: Path) -> Path:
    db = tmp_path / "portfolio.db"
    state = {
        "positions": {
            "AAPL": {
                "symbol": "AAPL",
                "side": "LONG",
                "quantity": 10,
                "entry_price": 180,
                "current_price": 195,
                "unrealized_pnl": 150,
                "open_time": 1_700_000_000,
            },
            "BTCUSDT": {
                "symbol": "BTCUSDT",
                "side": "LONG",
                "quantity": 0.25,
                "entry_price": 50_000,
                "current_price": 60_000,
                "unrealized_pnl": 2_500,
                "open_time": 1_700_500_000,
            },
        },
        "trade_history": [
            {
                "trade_id": "t1",
                "symbol": "MSFT",
                "side": "LONG",
                "quantity": 5,
                "entry_price": 300,
                "exit_price": 320,
                "realized_pnl": 100,
                "opened_at": 1_699_000_000,
                "closed_at": 1_699_100_000,
            },
            {
                "trade_id": "t2",
                "symbol": "MSFT",
                "side": "SHORT",
                "quantity": 3,
                "entry_price": 320,
                "exit_price": 310,
                "realized_pnl": 30,
                "opened_at": 1_699_200_000,
                "closed_at": 1_699_300_000,
            },
        ],
        "daily_pnl": 175.5,
        "paper_balance": 100_000,
    }
    import_state(state, db)
    return db


def test_list_positions_returns_rows_sorted_by_unrealized_pnl(seeded_db: Path) -> None:
    out = list_positions(seeded_db)
    assert out.total == 2
    syms = [r["symbol"] for r in out.rows]
    # BTCUSDT carries +2_500, AAPL +150 → BTCUSDT first.
    assert syms == ["BTCUSDT", "AAPL"]
    # raw blob hydrated from JSON column
    assert out.rows[0]["raw"]["entry_price"] == 50_000


def test_list_trades_orders_by_closed_at_desc_and_caps_limit(seeded_db: Path) -> None:
    out = list_trades(seeded_db, limit=1)
    assert out.total == 2  # total counts everything in the table
    assert len(out.rows) == 1
    assert out.rows[0]["trade_id"] == "t2"  # most recent close


def test_list_trades_filters_by_symbol(seeded_db: Path) -> None:
    out = list_trades(seeded_db, symbol="msft", limit=10)
    assert {r["symbol"] for r in out.rows} == {"MSFT"}


def test_list_migrations_returns_audit_with_decoded_summary(seeded_db: Path) -> None:
    out = list_migrations(seeded_db)
    assert out.rows
    summary = out.rows[0]["summary"]
    assert summary["positions_imported"] == 2
    assert summary["trades_imported"] == 2


def test_endpoints_are_safe_when_db_missing(tmp_path: Path) -> None:
    missing = tmp_path / "no.db"
    assert list_positions(missing).total == 0
    assert list_trades(missing).total == 0
    assert list_migrations(missing).total == 0
