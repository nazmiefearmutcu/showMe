"""LOTS ledger honesty pins (wc1-g28): acquisition date, lot_ids, long-term threshold.

Offline: the tax-lot ledger is a temporary SQLite file; no network is used.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest  # noqa: E402

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.core.instrument import AssetClass, Instrument  # noqa: E402
from showme.engine.functions.portfolio.lots import LOTSFunction  # noqa: E402
from showme.engine.services import tax_lots  # noqa: E402

SYM = Instrument(symbol="WCTEST", asset_class=AssetClass.EQUITY)


@pytest.fixture(autouse=True)
def _ledger(monkeypatch, tmp_path):
    monkeypatch.setattr(tax_lots, "_db_file", lambda: tmp_path / "tax_lots.sqlite")


def _run(**kwargs):
    return asyncio.run(LOTSFunction(FunctionDeps()).execute(**kwargs))


def _epoch(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp())


# LOTS#3: the acquisition date must be settable; holding period and term depend on it.
def test_open_stamps_the_lot_with_the_supplied_acquisition_date() -> None:
    res = _run(instrument=SYM, action="open", quantity=10, price=100, acquired_at="2024-01-15")
    assert res.data.get("status") in (None, "ok")
    lots = tax_lots.list_open_lots(symbol="WCTEST")
    assert len(lots) == 1
    assert lots[0]["opened_at"] == _epoch(2024, 1, 15)
    assert res.data["acquired_at_source"] == "supplied"


def test_long_term_split_follows_the_supplied_acquisition_date() -> None:
    _run(instrument=SYM, action="open", quantity=10, price=100, acquired_at="2024-01-15")
    res = _run(instrument=SYM, action="sell", quantity=4, price=120, method="FIFO")
    consumed = res.data["consumed_lots"][0]
    assert consumed["term"] == "long"
    assert consumed["holding_days"] >= 365


def test_open_without_acquisition_date_is_flagged_as_entry_time() -> None:
    res = _run(instrument=SYM, action="open", quantity=10, price=100)
    assert res.data["acquired_at_source"] == "entry_time"
    assert res.data["warnings"]


def test_open_rejects_a_future_acquisition_date_and_writes_nothing() -> None:
    res = _run(instrument=SYM, action="open", quantity=10, price=100, acquired_at="2999-01-01")
    assert res.data["status"] == "input_error"
    assert "acquired_at" in res.data["missing"]
    assert tax_lots.list_open_lots() == []


def test_open_rejects_an_unparseable_acquisition_date_and_writes_nothing() -> None:
    res = _run(instrument=SYM, action="open", quantity=10, price=100, acquired_at="last spring")
    assert res.data["status"] == "input_error"
    assert "acquired_at" in res.data["missing"]
    assert tax_lots.list_open_lots() == []


# LOTS#4: lot_ids must select the lots to sell, not be silently ignored under FIFO.
def test_sell_with_lot_ids_consumes_the_named_lot_not_the_fifo_lot() -> None:
    old = _run(instrument=SYM, action="open", quantity=10, price=100, acquired_at="2024-01-15")
    new = _run(instrument=SYM, action="open", quantity=10, price=110, acquired_at="2025-06-01")
    old_id, new_id = old.data["lot_id"], new.data["lot_id"]
    res = _run(instrument=SYM, action="sell", quantity=3, price=120, method="FIFO",
               lot_ids=[new_id])
    consumed = [row["lot_id"] for row in res.data["consumed_lots"]]
    assert consumed == [new_id]
    assert old_id not in consumed
    assert res.data["method"] == "SPECIFIC"
    assert res.data["qty_filled"] == pytest.approx(3.0)


def test_sell_lot_ids_accepts_a_comma_separated_string() -> None:
    old = _run(instrument=SYM, action="open", quantity=10, price=100, acquired_at="2024-01-15")
    new = _run(instrument=SYM, action="open", quantity=10, price=110, acquired_at="2025-06-01")
    res = _run(instrument=SYM, action="sell", quantity=2, price=120, lot_ids=f"{new.data['lot_id']}")
    assert [row["lot_id"] for row in res.data["consumed_lots"]] == [new.data["lot_id"]]
    assert old.data["lot_id"] not in [row["lot_id"] for row in res.data["consumed_lots"]]


# LOTS#6: the long-term cutoff is an input (default 365 days), not a fixed constant.
def test_sell_long_term_threshold_is_an_input() -> None:
    from datetime import timedelta

    held_since = (datetime.now(timezone.utc) - timedelta(days=60)).date().isoformat()
    _run(instrument=SYM, action="open", quantity=10, price=100, acquired_at=held_since)
    short = _run(instrument=SYM, action="sell", quantity=1, price=120, method="FIFO")
    assert short.data["consumed_lots"][0]["term"] == "short"
    long_ = _run(instrument=SYM, action="sell", quantity=1, price=120, method="FIFO",
                 long_term_threshold_days=30)
    assert long_.data["consumed_lots"][0]["term"] == "long"


def test_sell_rejects_a_non_positive_long_term_threshold_and_keeps_the_lot() -> None:
    _run(instrument=SYM, action="open", quantity=10, price=100, acquired_at="2024-01-15")
    for bad in (0, -5, "soon"):
        res = _run(instrument=SYM, action="sell", quantity=1, price=120, method="FIFO",
                   long_term_threshold_days=bad)
        assert res.data["status"] == "input_error", bad
        assert "long_term_threshold_days" in res.data["missing"]
    lots = tax_lots.list_open_lots(symbol="WCTEST")
    assert lots[0]["closed_qty"] == pytest.approx(0.0)
