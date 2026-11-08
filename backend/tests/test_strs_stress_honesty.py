"""STRS honesty regressions (p1a-g05).

* STRS#1 — a scaled shock must never push a position below zero market value.
* STRS#3 — bond funds take the BOND bucket only for treasury/aggregate funds, never
  the credit or inflation funds; in the GFC and COVID windows a bond fund takes its
  own measured window return (history fetched through the yfinance adapter) and is
  left unshocked, with a warning, when that return is unavailable. No TLT constant
  is hard-coded.
* STRS#4 — the manifest must not claim historical replay that the code does not run
  (see test_strs_manifest_honesty.py).

All tests go through STRSFunction.execute() with PortfolioState replaced by an
in-memory fake and the yfinance history replaced by an in-memory fake, so no
network or runtime/portfolio.json is read.
"""

from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio import strs as strs_mod
from showme.engine.services import stress_scenarios as stress


class _Position:
    def __init__(self, symbol: str, asset_class: AssetClass, quantity: float, avg_cost: float):
        self.instrument = Instrument(symbol=symbol, asset_class=asset_class)
        self.quantity = quantity
        self.avg_cost = avg_cost


def _use_positions(monkeypatch, positions):
    class _Portfolio:
        def __init__(self):
            self.positions = positions

        def import_legacy_crypto(self):
            return None

    monkeypatch.setattr(strs_mod, "PortfolioState", _Portfolio)


def _run(coro):
    return asyncio.run(coro)


class _FakeHistory:
    """In-memory yfinance OHLCV fake: two closes per window, price return ``r``.

    ``returns`` maps symbol -> {window key: return}. A missing entry raises, which
    the STRS path must turn into an explicit unavailable state.
    """

    def __init__(self, returns: dict[str, dict[str, float]] | None = None):
        self.returns = returns or {}
        self.requests: list = []

    async def fetch(self, request):
        self.requests.append(request)
        sym = request.instrument.symbol
        key = "GFC_2008" if request.start.year == 2008 else "COVID_2020"
        r = self.returns.get(sym, {}).get(key)
        if r is None:
            raise RuntimeError(f"no history for {sym} {key}")
        start, end = stress.MEASURED_WINDOWS[key]
        return pd.DataFrame(
            {"close": [100.0, 100.0 * (1.0 + r)]},
            index=pd.DatetimeIndex([pd.Timestamp(start), pd.Timestamp(end)]),
        )


def _deps(history: _FakeHistory | None):
    return SimpleNamespace(yfinance=history)


def _row(res, symbol):
    return next(r for r in res.data["positions"] if r["symbol"] == symbol)


# ── STRS#1: no negative market value under scaling ──────────────────────


def test_strs1_scaled_shock_never_drives_market_value_negative(monkeypatch):
    _use_positions(monkeypatch, [_Position("AAPL", AssetClass.EQUITY, 100.0, 100.0)])
    res = _run(strs_mod.STRSFunction().execute(action="scenario", scenario="GFC_2008", scale=2))
    rows = res.data["positions"]
    assert rows[0]["market_value_post"] >= 0.0, rows[0]
    assert res.data["total_market_value_post"] >= 0.0
    assert any("AAPL" in w for w in res.warnings), res.warnings


def test_strs1_compare_path_floors_and_reports(monkeypatch):
    _use_positions(monkeypatch, [_Position("BTC-USD", AssetClass.CRYPTO, 1.0, 10_000.0)])
    res = _run(strs_mod.STRSFunction().execute(action="compare", scale=2))
    assert res.data["comparisons"]
    assert all(r["total_pnl"] >= -10_000.0 - 1e-9 for r in res.data["comparisons"])
    assert res.warnings, "floored shocks must be reported in warnings"


# ── STRS#3: bond-fund bucket membership ─────────────────────────────────


@pytest.mark.parametrize("symbol", ["HYG", "JNK", "LQD", "TIP"])
def test_strs3_credit_and_inflation_funds_are_not_in_the_bond_bucket(symbol):
    assert symbol not in stress.BOND_ETF_SYMBOLS


@pytest.mark.parametrize("symbol", ["TLT", "IEF", "SHY", "GOVT", "VGSH"])
def test_strs3_treasury_funds_are_in_the_bond_bucket(symbol):
    assert stress.resolve_shock_bucket(symbol, "ETF") == "BOND"


def test_strs3_credit_etf_keeps_equity_style_etf_bucket(monkeypatch):
    _use_positions(monkeypatch, [_Position("HYG", AssetClass.ETF, 100.0, 100.0)])
    res = _run(strs_mod.STRSFunction().execute(action="scenario", scenario="GFC_2008"))
    assert _row(res, "HYG")["shock"] == pytest.approx(-0.50)
    assert _row(res, "HYG")["shock_source"] == "hand_set"


def test_strs3_equity_etf_still_takes_etf_bucket(monkeypatch):
    _use_positions(monkeypatch, [_Position("SPY", AssetClass.ETF, 100.0, 100.0)])
    res = _run(strs_mod.STRSFunction().execute(action="scenario", scenario="GFC_2008"))
    assert _row(res, "SPY")["shock"] == pytest.approx(-0.50)


def test_strs3_treasury_outside_measured_windows_uses_hand_set_bond_row(monkeypatch):
    _use_positions(monkeypatch, [_Position("IEF", AssetClass.ETF, 100.0, 100.0)])
    res = _run(strs_mod.STRSFunction().execute(action="scenario", scenario="RATE_SHOCK_300BP"))
    # RATE_SHOCK_300BP has no measured window: BOND -0.20 applies, the ETF bucket must not.
    assert _row(res, "IEF")["shock"] == pytest.approx(-0.20)
    assert _row(res, "IEF")["shock_source"] == "hand_set"


def test_strs3_no_hardcoded_treasury_window_constants():
    for key in stress.MEASURED_WINDOWS:
        sc = stress.SCENARIOS[key]
        assert "TLT" not in sc.symbol_shocks, key
        assert not (set(sc.symbol_shocks) & stress.BOND_ETF_SYMBOLS), key


# ── STRS#3: measured window returns ─────────────────────────────────────


def test_measured_window_return_is_first_to_last_close_in_window():
    closes = [
        (date(2008, 9, 15), 100.0),
        (date(2008, 10, 1), 90.0),
        (date(2009, 3, 9), 105.74),
        (date(2009, 3, 20), 1.0),  # outside the window: ignored
    ]
    got = stress.measured_window_return(closes, *stress.MEASURED_WINDOWS["GFC_2008"])
    assert got == pytest.approx(0.0574, abs=1e-9)


def test_measured_window_return_rejects_thin_or_gapped_coverage():
    start, end = stress.MEASURED_WINDOWS["GFC_2008"]
    # Only one close: no return.
    assert stress.measured_window_return([(date(2008, 10, 1), 100.0)], start, end) is None
    # First close 10 days after the window opens: a gap, not the window.
    gapped = [(date(2008, 9, 25), 100.0), (date(2009, 3, 9), 105.0)]
    assert stress.measured_window_return(gapped, start, end) is None


def test_measured_window_return_ignores_non_finite_closes():
    start, end = stress.MEASURED_WINDOWS["COVID_2020"]
    closes = [(date(2020, 2, 19), 100.0), (date(2020, 3, 2), float("nan")), (date(2020, 3, 23), 85.93)]
    assert stress.measured_window_return(closes, start, end) == pytest.approx(-0.1407, abs=1e-4)


def test_strs3_treasury_takes_measured_gfc_return(monkeypatch):
    _use_positions(monkeypatch, [_Position("TLT", AssetClass.ETF, 100.0, 100.0)])
    hist = _FakeHistory({"TLT": {"GFC_2008": 0.0574, "COVID_2020": 0.1407}})
    res = _run(strs_mod.STRSFunction(_deps(hist)).execute(action="scenario", scenario="GFC_2008"))
    row = _row(res, "TLT")
    assert row["shock"] == pytest.approx(0.0574, abs=1e-6)
    assert row["market_value_post"] > row["market_value_pre"]
    assert row["shock_source"] == "measured_window"
    assert "yfinance_history" in res.sources
    # The window requested is the named one, not a hard-coded constant.
    assert hist.requests[0].start.date() == date(2008, 9, 15)


def test_strs3_treasury_takes_measured_covid_return(monkeypatch):
    _use_positions(monkeypatch, [_Position("TLT", AssetClass.ETF, 100.0, 100.0)])
    hist = _FakeHistory({"TLT": {"GFC_2008": 0.0574, "COVID_2020": 0.1407}})
    res = _run(strs_mod.STRSFunction(_deps(hist)).execute(action="scenario", scenario="COVID_2020"))
    assert _row(res, "TLT")["shock"] == pytest.approx(0.1407, abs=1e-6)


def test_strs3_treasury_unavailable_is_not_estimated(monkeypatch):
    _use_positions(monkeypatch, [_Position("TLT", AssetClass.ETF, 100.0, 100.0)])
    res = _run(strs_mod.STRSFunction(_deps(_FakeHistory({}))).execute(action="scenario", scenario="GFC_2008"))
    row = _row(res, "TLT")
    assert row["shock"] is None
    assert row["shock_source"] == "unavailable"
    assert row["market_value_post"] == row["market_value_pre"]
    assert any("TLT" in w and "unavailable" in w for w in res.warnings), res.warnings
    assert res.data["unpriced_positions"] == 1


def test_strs3_treasury_unavailable_without_any_provider(monkeypatch):
    _use_positions(monkeypatch, [_Position("IEF", AssetClass.ETF, 100.0, 100.0)])
    res = _run(strs_mod.STRSFunction().execute(action="scenario", scenario="COVID_2020"))
    assert _row(res, "IEF")["shock_source"] == "unavailable"


def test_strs3_compare_uses_measured_windows_for_treasuries(monkeypatch):
    _use_positions(monkeypatch, [_Position("TLT", AssetClass.ETF, 1.0, 100.0)])
    hist = _FakeHistory({"TLT": {"GFC_2008": 0.0574, "COVID_2020": 0.1407}})
    res = _run(strs_mod.STRSFunction(_deps(hist)).execute(action="compare"))
    by_key = {c["key"]: c for c in res.data["comparisons"]}
    assert by_key["GFC_2008"]["total_pnl"] == pytest.approx(5.74, abs=1e-6)
    assert by_key["COVID_2020"]["total_pnl"] == pytest.approx(14.07, abs=1e-6)


def test_strs3_measured_window_never_applies_to_equities(monkeypatch):
    _use_positions(monkeypatch, [
        _Position("SPY", AssetClass.ETF, 1.0, 100.0),
        _Position("TLT", AssetClass.ETF, 1.0, 100.0),
    ])
    hist = _FakeHistory({"TLT": {"GFC_2008": 0.0574}, "SPY": {"GFC_2008": 0.9}})
    res = _run(strs_mod.STRSFunction(_deps(hist)).execute(action="scenario", scenario="GFC_2008"))
    assert _row(res, "SPY")["shock"] == pytest.approx(-0.50)
    assert _row(res, "SPY")["shock_source"] == "hand_set"


def test_apply_scenario_measured_none_marks_treasury_unavailable():
    positions = [{"symbol": "TLT", "asset_class": "ETF", "market_value": 100.0}]
    out = stress.apply_scenario(
        positions, stress.SCENARIOS["GFC_2008"], measured={"TLT": None},
    )
    row = out["positions"][0]
    assert row["shock_source"] == "unavailable"
    assert out["total_pnl"] == 0.0
    assert out["warnings"]


# ── STRS#4: unknown keys are reported, not silently dropped ─────────────


def test_strs4_compare_reports_unknown_scenario_keys(monkeypatch):
    _use_positions(monkeypatch, [_Position("AAPL", AssetClass.EQUITY, 1.0, 100.0)])
    res = _run(strs_mod.STRSFunction().execute(
        action="compare", scenarios=["LEHMAN_2008", "gfc_2008"],
    ))
    assert [c["key"] for c in res.data["comparisons"]] == ["gfc_2008"]
    assert any("LEHMAN_2008" in w for w in res.warnings), res.warnings


def test_strs4_compare_accepts_a_comma_separated_scenario_string(monkeypatch):
    _use_positions(monkeypatch, [_Position("AAPL", AssetClass.EQUITY, 1.0, 100.0)])
    res = _run(strs_mod.STRSFunction().execute(
        action="compare", scenarios="GFC_2008, COVID_2020",
    ))
    assert sorted(c["key"] for c in res.data["comparisons"]) == ["COVID_2020", "GFC_2008"]


def test_strs4_unknown_single_scenario_is_an_explicit_input_error(monkeypatch):
    _use_positions(monkeypatch, [_Position("AAPL", AssetClass.EQUITY, 1.0, 100.0)])
    res = _run(strs_mod.STRSFunction().execute(action="scenario", scenario="BLACK_MONDAY_1987"))
    assert res.data["status"] == "input_error", res.data
    assert "GFC_2008" in res.data["scenarios"]
    assert res.data["next_actions"]
    assert any("BLACK_MONDAY_1987" in w for w in res.warnings), res.warnings


def test_strs4_scenario_magnitudes_input_is_the_scale_factor(monkeypatch):
    _use_positions(monkeypatch, [_Position("HYG", AssetClass.ETF, 100.0, 100.0)])
    res = _run(strs_mod.STRSFunction().execute(
        action="scenario", scenario="GFC_2008", scenario_magnitudes=1.5,
    ))
    assert res.data["scale"] == pytest.approx(1.5)
    assert _row(res, "HYG")["shock"] == pytest.approx(-0.75)
