"""TLH#2-#5 regressions: wash-sale status, netted savings, Yahoo sector labels,
and the position-level output contract. The local book and yfinance are
patched through the helpers in test_tlh_real_portfolio; no network is used.
"""
from __future__ import annotations

import asyncio

import pytest

from showme.engine.functions.portfolio import tlh
from test_tlh_real_portfolio import _book, _deps, _pos


def _run(fn, **params):
    return asyncio.run(fn.execute(**params))


def _rows(res):
    return {c["symbol"]: c for c in res.data["candidates"]}


# ── TLH#2: wash-sale status is not claimed when it was not checked ───────


def test_seasoned_loss_is_not_claimed_wash_safe(monkeypatch):
    _book(monkeypatch, [_pos("AAPL", 10, 200.0, 400)])
    res = _run(tlh.TLHFunction(_deps({"AAPL": 180.0})))
    row = _rows(res)["AAPL"]
    assert row["wash_sale_status"] == "not_checked"
    assert row["wash_sale_safe"] is None
    assert res.data["wash_sale_checked"] is False
    assert res.data["wash_sale_rule_respected"] is None


def test_position_opened_inside_window_is_blocked_and_left_out_of_total(monkeypatch):
    _book(monkeypatch, [_pos("AAPL", 10, 200.0, 10)])
    res = _run(tlh.TLHFunction(_deps({"AAPL": 180.0})))
    row = _rows(res)["AAPL"]
    assert row["wash_sale_safe"] is False
    assert row["wash_sale_status"] == "blocked_open_date_in_window"
    assert "opened on" in row["wash_sale_reason"]
    assert res.data["total_estimated_tax_savings"] == 0
    assert res.data["summary"]["wash_blocked_count"] == 1


# ── TLH#3: savings are netted when gains are supplied, labelled gross otherwise


def test_gross_total_is_labelled_when_no_gains_supplied(monkeypatch):
    _book(monkeypatch, [_pos("AAPL", 10, 1000.0, 100)])  # loss 5000
    res = _run(tlh.TLHFunction(_deps({"AAPL": 500.0})), tax_bracket=0.24)
    assert res.data["savings_basis"] == "gross_upper_bound_no_gains_supplied"
    assert res.data["total_estimated_tax_savings"] == pytest.approx(5000 * 0.24)
    assert any("gross" in w for w in res.warnings)


def test_supplied_gains_net_losses_and_apply_the_ordinary_offset(monkeypatch):
    _book(monkeypatch, [_pos("AAPL", 10, 1000.0, 100)])  # loss 5000
    res = _run(
        tlh.TLHFunction(_deps({"AAPL": 500.0})),
        tax_bracket=0.24, realized_st_gain=0, realized_lt_gain=0,
    )
    assert res.data["savings_basis"] == "netted_against_supplied_realized_gains"
    # Only 3,000 of the 5,000 net loss offsets ordinary income this year.
    assert res.data["total_estimated_tax_savings"] == pytest.approx(3000 * 0.24)
    assert res.data["gross_estimated_tax_savings"] == pytest.approx(5000 * 0.24)
    # The per-position figure stays gross.
    assert _rows(res)["AAPL"]["estimated_tax_savings"] == pytest.approx(5000 * 0.24)


def test_non_numeric_realized_gain_is_an_input_error(monkeypatch):
    _book(monkeypatch, [_pos("AAPL", 10, 200.0, 400)])
    res = _run(tlh.TLHFunction(_deps({"AAPL": 150.0})), realized_st_gain="abc", realized_lt_gain=0)
    assert res.data["status"] == "input_error"
    assert res.data["next_actions"]


@pytest.mark.parametrize(
    "st, lt, expected",
    [
        (5000, 0, 1200.0),        # gains only: tax at the ST rate
        (3000, 0, 720.0),         # after a 2,000 ST loss offset
        (-5000, 0, -720.0),       # net loss: only 3,000 offsets income
        (0, 10000, 1500.0),       # LT gain at 15%
        (-2000, 10000, 1200.0),   # ST loss offsets LT gain first
        (5000, -2000, 720.0),     # LT loss offsets ST gain first
        (-1000, -500, -360.0),    # both losses, within the offset
    ],
)
def test_tax_on_net_gains_follows_the_netting_order(st, lt, expected):
    assert tlh._tax_on_net_gains(st, lt, 0.24, 0.15) == pytest.approx(expected)


# ── TLH#4: sector labels are the Yahoo vocabulary that yfinance returns ──


@pytest.mark.parametrize(
    "sector, etf",
    [
        ("Financial Services", "XLF"),
        ("Consumer Cyclical", "XLY"),
        ("Consumer Defensive", "XLP"),
        ("Basic Materials", "XLB"),
        ("Healthcare", "XLV"),
        ("Technology", "VGT"),
    ],
)
def test_yahoo_sector_label_gets_a_replacement(monkeypatch, sector, etf):
    _book(monkeypatch, [_pos("JPM", 10, 200.0, 100)])
    res = _run(tlh.TLHFunction(_deps({"JPM": 150.0}, {"JPM": sector})))
    assert _rows(res)["JPM"]["replacement_etf"] == etf


def test_unknown_sector_label_gets_no_replacement(monkeypatch):
    _book(monkeypatch, [_pos("JPM", 10, 200.0, 100)])
    res = _run(tlh.TLHFunction(_deps({"JPM": 150.0}, {"JPM": "Not A Sector"})))
    assert _rows(res)["JPM"]["replacement_etf"] is None


# ── TLH#5: manifest default, position-level labelling, must-have keys ────


def test_default_min_loss_threshold_is_the_manifest_value(monkeypatch):
    _book(monkeypatch, [_pos("AAPL", 10, 200.0, 100), _pos("MSFT", 10, 500.0, 100)])
    res = _run(tlh.TLHFunction(_deps({"AAPL": 195.0, "MSFT": 470.0})))  # AAPL loss 50, MSFT loss 300
    assert res.data["min_loss_threshold"] == 100.0
    assert set(_rows(res)) == {"MSFT"}


def test_position_level_contract_carries_the_must_have_keys(monkeypatch):
    _book(monkeypatch, [_pos("AAPL", 10, 200.0, 400)])
    res = _run(tlh.TLHFunction(_deps({"AAPL": 150.0})))
    for key in (
        "as_of", "credential_id", "candidates", "total_harvestable_loss",
        "wash_sale_rule_respected", "data_mode", "paper_mode", "ccy", "granularity",
    ):
        assert key in res.data, key
    assert res.data["granularity"] == "position"
    assert res.data["lot_level"] is False
    assert res.data["paper_mode"] is True
    assert res.data["total_harvestable_loss"] == pytest.approx(500.0)


def test_credential_and_currency_inputs_are_reported_not_silently_ignored(monkeypatch):
    _book(monkeypatch, [_pos("AAPL", 10, 200.0, 400)])
    res = _run(tlh.TLHFunction(_deps({"AAPL": 150.0})), credential_id="acct-1", ccy="EUR")
    assert any("credential_id" in w for w in res.warnings)
    assert any("EUR" in w for w in res.warnings)
    assert res.data["ccy"] == "native"
