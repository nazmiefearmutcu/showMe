"""XCON-6: FX rate inputs are decimal annual rates; a percent entry is refused.

A caller who types 3.5 (meaning 3.5 %) into an FX rate field used to get a
silently wrong forward. Every FX function that takes a rate input must now
return an explicit ``input_error`` for a value above 1.0 instead.
Network is patched: no spot or FRED call is made.
"""
from __future__ import annotations

import asyncio

import pytest

from showme.engine.functions.fx import _funcs as fx
from showme.engine.functions.fx.fxh import FXHFunction
from showme.engine.services.fx_hedge import decimal_rate_error


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    async def _none(series_id, **kw):  # noqa: ARG001
        return None

    monkeypatch.setattr(fx, "fetch_fred_csv_series", _none)


def test_decimal_rate_error_refuses_percent_entries_and_accepts_decimals() -> None:
    assert decimal_rate_error("r_base", 0.035) is None
    assert decimal_rate_error("r_base", None) is None
    assert decimal_rate_error("r_base", "") is None
    assert decimal_rate_error("r_base", -0.01) is None
    assert decimal_rate_error("r_base", 3.5) is not None
    assert "decimal" in decimal_rate_error("r_base", 3.5)
    assert decimal_rate_error("r_base", float("nan")) is not None


def test_frd_percent_rate_is_input_error_not_a_forward() -> None:
    res = _run(fx.FRDFunction().execute(base="EUR", quote="USD", tenors="3M", spot=1.10, live=False,
                                        r_base=3.5, r_quote=0.045))
    assert res.data["status"] == "input_error", res.data
    assert "decimal" in res.data["reason"]
    assert res.data.get("F") is None
    assert res.data.get("rows") == []


def test_fxfc_percent_rate_is_input_error_not_a_forward() -> None:
    res = _run(fx.FXFCFunction().execute(pair="EURUSD", spot=1.10, live=False, vol_annualized=0.08,
                                         r_base=0.035, r_quote=4.5))
    assert res.data["status"] == "input_error", res.data
    assert "decimal" in res.data["reason"]
    assert all(row.get("forecast") is None for row in res.data.get("curve", []))


def test_fxip_percent_rate_is_input_error_not_a_forward() -> None:
    res = _run(fx.FXIPFunction().execute(pair="EURUSD", spot=1.10, live=False, r_base=0.035, r_quote=4.5))
    assert res.data["status"] == "input_error", res.data
    assert "decimal" in res.data["reason"]
    assert res.data.get("one_month_forward") is None


def test_fxh_percent_base_rate_is_input_error_not_a_hedge_book() -> None:
    res = _run(FXHFunction().execute(pair="EURUSD", spot_rate=1.10, base_rate=3.5, home_rate=0.045,
                                     tenor="3M"))
    assert res.data["status"] == "input_error", res.data
    assert "decimal" in res.data["reason"]


# ── XCON-4: one day-count convention across FXH, FRD and FXFC ─────────────


def test_fxh_forward_uses_act_360_like_frd_and_fxfc() -> None:
    """A 360-day tenor at S=1, r_quote=10 %, r_base=0 is exactly 1.10 on ACT/360.

    On the old ACT/365 basis (days/365) the same inputs give 1.0986, so FXH
    undercounted the accrual against the USD/EUR money-market quote basis.
    """
    from showme.engine.services.fx_hedge import forward_rate

    assert forward_rate(spot=1.0, home_rate=0.10, base_rate=0.0, days=360) == pytest.approx(1.10, abs=1e-12)


def test_fxh_and_frd_agree_on_the_same_named_tenor() -> None:
    """XCON-4-RQ: the same pair and tenor must price the same forward in FXH and FRD.

    FRD maps 3M to 0.25 of a 365-day year (91.25 days). FXH used a flat 90 days
    for 3M, so the two panes disagreed by about 0.37 pip for EURUSD.
    """
    frd = _run(fx.FRDFunction().execute(base="EUR", quote="USD", tenor="3M", spot=1.10, live=False,
                                        r_base=0.035, r_quote=0.045))
    fxh = _run(FXHFunction().execute(pair="EURUSD", spot_rate=1.10, base_rate=0.035, home_rate=0.045,
                                     tenor="3M"))
    assert frd.data["forward_rate"] == pytest.approx(fxh.data["rows"][0]["forward_rate"], abs=1e-6)


def test_fxh_and_frd_agree_for_the_same_number_of_days() -> None:
    from showme.engine.services.fx_hedge import forward_rate

    days = 91
    fxh = forward_rate(spot=1.10, home_rate=0.035, base_rate=0.045, days=days)
    frd = fx._forward(1.10, 0.045, 0.035, days / 365.0, "ACT/360")
    assert fxh == pytest.approx(frd, abs=1e-12)


# ── XCON-5-RQ: every FRD card slot has a producer in the handler output ───


def test_frd_card_slots_all_have_producers_in_output() -> None:
    from showme.manifest.seeds.frd_seed import frd as frd_manifest

    slot_keys = [slot.key for slot in frd_manifest.card_schema.slots]
    res = _run(fx.FRDFunction().execute(base="EUR", quote="USD", tenor="3M", spot=1.10, live=False,
                                        r_base=0.035, r_quote=0.045))
    missing = [key for key in slot_keys if key not in res.data]
    assert missing == [], f"card slots without a producer: {missing}"


def test_frd_implied_carry_is_annualized_percent_and_matches_forward() -> None:
    res = _run(fx.FRDFunction().execute(base="EUR", quote="USD", tenor="3M", spot=1.10, live=False,
                                        r_base=0.035, r_quote=0.045))
    row = res.data["rows"][0]
    t = 0.25
    unrounded_fwd = fx._forward(1.10, 0.035, 0.045, t, "ACT/360")
    expected = (unrounded_fwd / 1.10 - 1.0) / (t * 365.0 / 360.0) * 100.0
    assert row["implied_carry"] == pytest.approx(expected, rel=1e-6)
    assert res.data["implied_carry"] == pytest.approx(expected, rel=1e-6)
    assert res.data["forward_points"] == pytest.approx(res.data["forward_rate"] - 1.10, abs=1e-6)


# ── FXIP#2-RQ: the rate-vintage warning names only the reference currency ──


def test_fxip_mixed_rate_basis_warns_only_about_the_reference_currency() -> None:
    """Base EUR is a 2024-06 reference constant; quote USD is caller input.

    The warning must name EUR and must not describe the user-supplied USD rate
    as a reference constant.
    """
    res = _run(fx.FXIPFunction().execute(pair="EURUSD", spot=1.085, live=False, r_quote=0.045))
    assert res.data["rate_basis"] == {"base": "reference_policy_rate_2024-06", "quote": "user_input"}
    vintage = [w for w in res.warnings if "2024-06" in w]
    assert len(vintage) == 1, res.warnings
    assert "EUR" in vintage[0]
    assert "USD" not in vintage[0]


# ── XCON-5-RQ: FRD never prices EURUSD in place of a missing or invalid pair ──


def test_frd_invalid_base_code_is_input_error_not_eurusd() -> None:
    """Base 'GB' is not an ISO code. FRD used to price EURUSD silently instead."""
    res = _run(fx.FRDFunction().execute(base="GB", quote="JPY", tenor="1M", spot=190.0, live=False,
                                        r_base=0.04, r_quote=0.005))
    assert res.data["status"] == "input_error", res.data
    assert res.data["rows"] == []
    assert res.data.get("pair") is None
    assert all(row.get("pair") != "EURUSD" for row in res.data.get("rows", []))


def test_frd_with_no_pair_or_currencies_needs_input_not_eurusd() -> None:
    res = _run(fx.FRDFunction().execute(spot=1.10, tenors="3M", live=False, r_base=0.035, r_quote=0.045))
    assert res.data["status"] == "needs_input", res.data
    assert res.data["rows"] == []
    assert res.data.get("pair") is None


def test_frd_malformed_pair_is_input_error_not_eurusd() -> None:
    res = _run(fx.FRDFunction().execute(pair="XYZ", spot=1.10, tenors="3M", live=False,
                                        r_base=0.035, r_quote=0.045))
    assert res.data["status"] == "input_error", res.data
    assert res.data["rows"] == []
