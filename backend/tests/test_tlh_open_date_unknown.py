"""TLH#2/#3 regressions: a position whose open date was never recorded must
not be blocked on a date the book made up, and it must stay in the netted
total. The local book and yfinance are patched through the helpers in
test_tlh_real_portfolio; no network is used.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio import tlh
from showme.engine.portfolio.state import PortfolioPosition
from test_tlh_real_portfolio import _book, _deps


def _run(fn, **params):
    return asyncio.run(fn.execute(**params))


def _added_without_open_date(sym, qty, cost):
    """Built the way the portfolio add route builds a position: no opened_at."""
    return PortfolioPosition(
        instrument=Instrument(symbol=sym, asset_class=AssetClass.EQUITY),
        quantity=qty,
        avg_cost=cost,
    )


# ── TLH#2: no recorded open date means not checked, never a blocked finding ──


def test_position_added_without_open_date_is_not_blocked(monkeypatch):
    _book(monkeypatch, [_added_without_open_date("AAPL", 10, 200.0)])
    res = _run(tlh.TLHFunction(_deps({"AAPL": 150.0})))
    [row] = res.data["candidates"]
    assert row["opened_at"] is None
    assert row["held_days"] is None
    assert row["wash_sale_status"] == "not_checked"
    assert row["wash_sale_safe"] is None
    assert "open date" in row["wash_sale_reason"].lower()
    assert res.data["summary"]["wash_blocked_count"] == 0


def test_unknown_open_date_holding_is_counted_at_the_short_term_rate(monkeypatch):
    _book(monkeypatch, [_added_without_open_date("AAPL", 10, 200.0)])
    res = _run(tlh.TLHFunction(_deps({"AAPL": 150.0})), tax_bracket=0.24)
    [row] = res.data["candidates"]
    assert row["holding_period_known"] is False
    assert row["long_term"] is None
    assert row["tax_rate_applied"] == pytest.approx(0.24)
    # Loss of 500 at 24%: the real holding is in the total, not dropped.
    assert res.data["total_estimated_tax_savings"] == pytest.approx(500 * 0.24)
    assert res.data["total_harvestable_loss"] == pytest.approx(500)


def test_recorded_open_date_inside_window_still_blocks(monkeypatch):
    pos = PortfolioPosition(
        instrument=Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY),
        quantity=10,
        avg_cost=200.0,
        opened_at=datetime.now(timezone.utc) - timedelta(days=10),
        opened_at_known=True,
    )
    _book(monkeypatch, [pos])
    res = _run(tlh.TLHFunction(_deps({"AAPL": 150.0})))
    [row] = res.data["candidates"]
    assert row["wash_sale_status"] == "blocked_open_date_in_window"
    assert row["wash_sale_safe"] is False
    assert row["holding_period_known"] is True
    assert res.data["total_estimated_tax_savings"] == 0


# ── TLH#3: the netted total keeps an unknown-date holding ─────────────────


def test_netted_total_keeps_an_unknown_date_holding(monkeypatch):
    _book(monkeypatch, [_added_without_open_date("AAPL", 10, 1000.0)])  # loss 5000 at 500
    res = _run(
        tlh.TLHFunction(_deps({"AAPL": 500.0})),
        tax_bracket=0.24, realized_st_gain=0, realized_lt_gain=0,
    )
    assert res.data["savings_basis"] == "netted_against_supplied_realized_gains"
    # Only 3,000 of the 5,000 net loss offsets ordinary income this year.
    assert res.data["total_estimated_tax_savings"] == pytest.approx(3000 * 0.24)
    assert res.data["summary"]["wash_blocked_count"] == 0


# ── open-date provenance flag: default False, persisted, legacy rows False ──


def test_open_date_flag_defaults_false_and_round_trips():
    instrument = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    pos = PortfolioPosition(instrument=instrument, quantity=1, avg_cost=1.0)
    assert pos.opened_at_known is False
    assert pos.to_dict()["opened_at_known"] is False

    known = PortfolioPosition(
        instrument=instrument, quantity=1, avg_cost=1.0,
        opened_at=datetime(2026, 1, 2, tzinfo=timezone.utc), opened_at_known=True,
    )
    assert PortfolioPosition.from_dict(known.to_dict()).opened_at_known is True


def test_legacy_row_with_an_opened_at_but_no_flag_is_unknown():
    row = {
        "instrument": Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY).to_dict(),
        "quantity": 1,
        "avg_cost": 1.0,
        "opened_at": "2026-01-02T00:00:00+00:00",
    }
    assert PortfolioPosition.from_dict(row).opened_at_known is False
