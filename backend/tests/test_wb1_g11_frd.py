"""FRD (FX forward rates, covered interest parity) — honesty and input tests.

Covers:
  * FRD#1 — the policy-rate legs come from keyless FRED series when live, and
    a constant fallback is labelled and warned, never silent.
  * FRD#2 — manifest input names (base, quote, tenor, r_dom, r_for,
    spot_override) drive the handler instead of being ignored.
  * FRD#4 — day count and forward-point units are stated in the response.

Network is patched: ``fx.fetch_fred_csv_series`` is replaced with a fake, and
every test passes a manual spot or ``live=False`` so no spot provider is hit.
"""
from __future__ import annotations

import asyncio

import pandas as pd
import pytest

from showme.engine.functions.fx import _funcs as fx
from showme.engine.functions.fx._funcs import FRDFunction


def _run(coro):
    return asyncio.run(coro)


def _series(value_pct: float, date: str = "2026-11-05") -> pd.DataFrame:
    return pd.DataFrame({"value": [value_pct]}, index=pd.DatetimeIndex([pd.Timestamp(date)]))


@pytest.fixture
def fred(monkeypatch):
    """Fake keyless FRED: DFF=3.88 (USD), ECBDFR=2.50 (EUR), others absent."""
    calls: list[str] = []
    book = {"DFF": 3.88, "ECBDFR": 2.50}

    async def _fake_fred(series_id, *, client=None, timeout=8.0, lookback_days=None):  # noqa: ARG001
        calls.append(series_id)
        if series_id in book:
            return _series(book[series_id])
        return None

    monkeypatch.setattr(fx, "fetch_fred_csv_series", _fake_fred)
    return calls


@pytest.fixture
def fred_down(monkeypatch):
    """Every FRED series unavailable."""
    calls: list[str] = []

    async def _none(series_id, *, client=None, timeout=8.0, lookback_days=None):  # noqa: ARG001
        calls.append(series_id)
        return None

    monkeypatch.setattr(fx, "fetch_fred_csv_series", _none)
    return calls


# ── FRD#1: live policy rates, labelled fallback ───────────────────────────


def test_frd_policy_rates_come_from_live_fred_series(fred) -> None:
    res = _run(FRDFunction().execute(pair="EURUSD", spot=1.10, tenors="3M"))
    d = res.data
    # EUR base -> ECB deposit rate 2.50 (percent) -> 0.025 decimal.
    assert d["r_base"] == pytest.approx(0.025)
    # USD quote -> fed funds effective 3.88 (percent) -> 0.0388 decimal.
    assert d["r_quote"] == pytest.approx(0.0388)
    assert d["rate_sources"] == {"base": "fred:ECBDFR", "quote": "fred:DFF"}
    assert d["rate_as_of"] == {"base": "2026-11-05", "quote": "2026-11-05"}
    assert "fred:DFF" in res.sources and "fred:ECBDFR" in res.sources
    assert not any("policy rate" in w for w in res.warnings)


def test_frd_no_live_rate_is_unavailable_not_a_stale_constant(fred_down) -> None:
    """DATA POLICY: with no live series and no caller input, no forward is computed.

    The 2024-06 constants (USD 4.5%, EUR 3.5%) must never be used as current rates.
    """
    res = _run(FRDFunction().execute(pair="EURUSD", spot=1.10, tenors="3M"))
    d = res.data
    assert d["status"] == "provider_unavailable"
    assert d["rows"] == []
    assert d["curve"] == []
    assert "F" not in d and "r_base" not in d and "r_quote" not in d
    assert isinstance(d.get("reason"), str) and d["reason"]
    actions = d.get("next_actions")
    assert isinstance(actions, list) and actions
    assert all(isinstance(a, str) and a for a in actions)
    assert any("r_base" in a and "r_quote" in a for a in actions)
    assert "reference_policy_rate_constant" not in res.sources
    assert any("EUR policy rate" in w and "unavailable" in w for w in res.warnings)
    assert any("USD policy rate" in w and "unavailable" in w for w in res.warnings)


def test_frd_one_live_leg_and_one_missing_leg_is_unavailable(monkeypatch) -> None:
    """A single missing leg blocks the forward; the live leg is not enough."""

    async def _only_dff(series_id, *, client=None, timeout=8.0, lookback_days=None):  # noqa: ARG001
        return _series(3.88) if series_id == "DFF" else None

    monkeypatch.setattr(fx, "fetch_fred_csv_series", _only_dff)
    res = _run(FRDFunction().execute(pair="EURUSD", spot=1.10, tenors="3M"))
    assert res.data["status"] == "provider_unavailable"
    assert res.data["rows"] == []
    assert res.data["rate_sources"]["quote"] == "fred:DFF"
    assert res.data["rate_sources"]["base"] == "unavailable"


def test_frd_explicit_rates_win_and_skip_the_live_lookup(fred) -> None:
    res = _run(FRDFunction().execute(pair="EURUSD", spot=1.10, tenors="3M", r_base=0.02, r_quote=0.05))
    d = res.data
    assert d["r_base"] == pytest.approx(0.02)
    assert d["r_quote"] == pytest.approx(0.05)
    assert d["rate_sources"] == {"base": "caller_input", "quote": "caller_input"}
    assert fred == []


def test_frd_live_false_skips_policy_lookup_and_is_unavailable(fred) -> None:
    res = _run(FRDFunction().execute(pair="EURUSD", spot=1.10, tenors="3M", live=False))
    assert fred == []
    assert res.data["status"] == "provider_unavailable"
    assert res.data["rate_sources"]["base"] == "unavailable"
    assert any("EUR policy rate" in w for w in res.warnings)


def test_frd_unknown_currency_is_unavailable_not_invented(fred_down) -> None:
    """A currency with no policy source and no reference rate must not get a made-up 4%."""
    res = _run(FRDFunction().execute(base="XYZ", quote="USD", spot=1.10, tenors="3M"))
    assert res.data["status"] == "provider_unavailable"
    assert res.data["rows"] == []
    assert any("XYZ" in w for w in res.warnings)
    # DATA POLICY: an honest state carries a reason and next_actions.
    assert isinstance(res.data.get("reason"), str) and res.data["reason"]
    actions = res.data.get("next_actions")
    assert isinstance(actions, list) and actions
    assert all(isinstance(a, str) and a for a in actions)


# ── FRD#2: manifest input names are honoured ──────────────────────────────


def test_frd_manifest_inputs_drive_pair_rates_tenor_and_spot(fred) -> None:
    res = _run(
        FRDFunction().execute(
            base="GBP",
            quote="USD",
            spot_override=1.25,
            r_dom=0.02,
            r_for=0.05,
            tenor="6M",
            live=False,
        )
    )
    d = res.data
    assert d["pair"] == "GBPUSD"
    assert d["base"] == "GBP" and d["quote"] == "USD"
    assert d["S"] == pytest.approx(1.25)
    assert d["r_base"] == pytest.approx(0.02)  # r_dom -> base
    assert d["r_quote"] == pytest.approx(0.05)  # r_for -> quote
    assert [row["tenor"] for row in d["rows"]] == ["6M"]


def test_frd_pair_param_still_wins_over_base_quote(fred) -> None:
    res = _run(FRDFunction().execute(pair="USDJPY", base="EUR", quote="GBP", spot=150.0, live=False, tenors="1M"))
    assert res.data["pair"] == "USDJPY"


# ── FRD#4: day count and forward-point units are stated ───────────────────


def test_frd_states_day_count_and_pip_units_for_jpy(fred_down) -> None:
    res = _run(
        FRDFunction().execute(
            base="USD", quote="JPY", spot=150.0, tenors="3M", r_base=0.04, r_quote=0.005
        )
    )
    d = res.data
    assert d["day_count"] == "ACT/360"
    assert "price" in d["forward_points_unit"]
    row = d["rows"][0]
    # JPY quote: one pip is 0.01, so pips = (F - S) * 100.
    assert row["forward_points_pips"] == pytest.approx((row["forward"] - row["spot"]) * 100, abs=0.01)


def test_frd_pips_use_ten_thousand_for_non_jpy_quote(fred_down) -> None:
    res = _run(
        FRDFunction().execute(base="EUR", quote="USD", spot=1.10, tenors="3M", r_base=0.035, r_quote=0.045)
    )
    row = res.data["rows"][0]
    assert row["forward_points_pips"] == pytest.approx((row["forward"] - row["spot"]) * 10000, abs=0.01)
