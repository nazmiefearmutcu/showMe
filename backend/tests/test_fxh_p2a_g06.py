"""P2A-G06 regressions for FXH (FX hedge calculator).

Findings covered: FXH#1 (exposure_side ignored), FXH#2 (manifest output
contract incl. hedge_cost), FXH#3 (spot_shock_pct / tenor ignored),
FXH#5 (silent base_rate=0.04 fallback), FXH#6 (portfolio mode reason).

All tests run offline: no yfinance dependency, spot is supplied manually.
"""
from __future__ import annotations

import asyncio

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.fx.fxh import (
    DEFAULT_BASE_RATE,
    DEFAULT_HOME_RATE,
    FXHFunction,
)
from showme.engine.services.fx_hedge import forward_rate


def _run(coro):
    return asyncio.run(coro)


def _fn() -> FXHFunction:
    return FXHFunction(deps=FunctionDeps(yfinance=None))


# ── FXH#5: explicit exposure without base_rate must not use 0.04 ─────────


def test_fxh5_explicit_exposure_missing_base_rate_uses_documented_default() -> None:
    """Was: e.get('base_rate', 0.04) silently used 4%, which is neither the
    documented DEFAULT_BASE_RATE (3.5%) nor reported in assumed_defaults."""
    result = _run(_fn().execute(
        action="forward",
        exposures=[{"currency": "EUR", "notional": 100_000, "spot_rate": 1.08}],
    ))
    fwd = result.data["forwards"][0]["forward"]
    expected = forward_rate(
        spot=1.08, home_rate=DEFAULT_HOME_RATE, base_rate=DEFAULT_BASE_RATE, days=90,
    )
    assert fwd == pytest.approx(expected, rel=1e-12)
    assert "base_rate" in result.data["assumed_defaults"]
    assert "home_rate" in result.data["assumed_defaults"]
    assert result.data["assumed_values"]["base_rate"] == pytest.approx(DEFAULT_BASE_RATE)


def test_fxh5_explicit_base_rate_none_does_not_crash_and_is_flagged() -> None:
    """A caller passing base_rate=None in the default book path must get the
    documented default and an echoed assumption, not a TypeError."""
    result = _run(_fn().execute(action="calc", pair="EURUSD", spot_rate=1.08, base_rate=None))
    assert "base_rate" in result.data["assumed_defaults"]
    assert result.data["rows"][0]["forward_rate"] == pytest.approx(
        forward_rate(spot=1.08, home_rate=DEFAULT_HOME_RATE,
                     base_rate=DEFAULT_BASE_RATE, days=90),
        rel=1e-12,
    )


# ── FXH#6: portfolio mode with no foreign positions ─────────────────────


class _FakePortfolio:
    """Stand-in for PortfolioState: only the members FXH reads."""

    def __init__(self, positions):
        self.positions = positions

    def import_legacy_crypto(self):
        return 0


def _patch_portfolio(monkeypatch, positions) -> None:
    import showme.engine.portfolio.state as state_mod

    monkeypatch.setattr(state_mod, "PortfolioState", lambda *a, **k: _FakePortfolio(positions))


def test_fxh6_portfolio_all_home_currency_reports_empty_book_not_spot(monkeypatch) -> None:
    """Was: an all-USD book (home=USD for EURUSD) produced an empty exposure
    list and the spot-provider message 'No exposure has a usable spot rate',
    with the envelope still reporting ok. It must say there is nothing to hedge."""
    from showme.engine.core.instrument import AssetClass, Instrument
    from showme.engine.portfolio.state import PortfolioPosition

    usd_pos = PortfolioPosition(
        instrument=Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY),
        quantity=10, avg_cost=150.0, currency="USD",
    )
    _patch_portfolio(monkeypatch, [usd_pos])
    result = _run(_fn().execute(action="calc", pair="EURUSD", use_portfolio=True))

    assert result.data["status"] == "empty"
    assert result.data["rows"] == []
    reason = result.data["reason"].lower()
    assert "non-home" in reason or "no foreign" in reason
    assert "spot" not in reason


def test_fxh6_portfolio_foreign_position_notional_is_native_currency(monkeypatch) -> None:
    """Pins the sizing convention: PortfolioPosition.avg_cost is stated in the
    position's own currency, so quantity*avg_cost is already foreign units."""
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.core.instrument import AssetClass, Instrument
    from showme.engine.portfolio.state import PortfolioPosition

    class _Quote:
        last = 1.08

    class _YF:
        async def fetch(self, req):
            return _Quote()

    eur_pos = PortfolioPosition(
        instrument=Instrument(symbol="SAP.DE", asset_class=AssetClass.EQUITY),
        quantity=10, avg_cost=150.0, currency="EUR",
    )
    _patch_portfolio(monkeypatch, [eur_pos])
    result = _run(FXHFunction(deps=FunctionDeps(yfinance=_YF())).execute(
        action="calc", pair="EURUSD", use_portfolio=True,
    ))
    assert result.data["rows"][0]["currency"] == "EUR"
    assert result.data["rows"][0]["notional_foreign"] == pytest.approx(1500.0)


# ── FXH#3: manifest spot_shock_pct (percent) and tenor are honoured ─────


def test_fxh3_spot_shock_pct_is_read_as_percent() -> None:
    """Was: spot_shock_pct=10 was ignored and the 5% default ran silently."""
    result = _run(_fn().execute(
        action="calc", pair="EURUSD", spot_rate=1.08, notional=1_000_000,
        base_rate=0.02, home_rate=0.03, spot_shock_pct=10.0,
    ))
    row = result.data["rows"][0]
    assert row["scenario_usd_strengthens_pct"] == pytest.approx(10.0)
    assert row["spot_if_home_strengthens"] == pytest.approx(1.08 * 0.90)


def test_fxh3_tenor_maps_to_days() -> None:
    """Was: tenor=1Y was ignored and 90 days was used."""
    result = _run(_fn().execute(
        action="calc", pair="EURUSD", spot_rate=1.08, notional=1_000_000,
        base_rate=0.02, home_rate=0.03, tenor="1Y",
    ))
    assert result.data["days_to_maturity"] == 365
    assert result.data["rows"][0]["days_to_maturity"] == 365


def test_fxh3_legacy_usd_shock_pct_decimal_still_wins() -> None:
    result = _run(_fn().execute(
        action="calc", pair="EURUSD", spot_rate=1.08, notional=1_000_000,
        base_rate=0.02, home_rate=0.03, usd_shock_pct=0.02,
    ))
    assert result.data["rows"][0]["scenario_usd_strengthens_pct"] == pytest.approx(2.0)


def test_fxh3_unknown_tenor_is_an_explicit_input_error() -> None:
    result = _run(_fn().execute(
        action="calc", pair="EURUSD", spot_rate=1.08, notional=1_000_000,
        base_rate=0.02, home_rate=0.03, tenor="7Y",
    ))
    assert result.data["status"] == "input_error"
    assert "tenor" in result.data["reason"].lower()
    assert result.data["rows"] == []


# ── FXH#1: exposure_side flips the hedge direction and P&L sign ─────────


def _book(side: str | None, **extra):
    kwargs = dict(
        action="calc", pair="EURUSD", spot_rate=1.08, notional=1_000_000,
        base_rate=0.02, home_rate=0.03, hedge_ratio=0.5, spot_shock_pct=5.0,
    )
    kwargs.update(extra)
    if side is not None:
        kwargs["exposure_side"] = side
    return _run(_fn().execute(**kwargs))


def test_fxh1_short_foreign_mirrors_long_foreign_pnl() -> None:
    """Was: exposure_side was never read, so short_foreign returned the same
    long-foreign P&L (pnl_if_home_strengthens negative for both)."""
    long_res = _book("long_foreign")
    short_res = _book("short_foreign")
    lr = long_res.data["rows"][0]
    sr = short_res.data["rows"][0]
    assert lr["pnl_if_home_strengthens"] < 0
    assert sr["pnl_if_home_strengthens"] == pytest.approx(-lr["pnl_if_home_strengthens"])
    assert sr["pnl_if_home_weakens"] == pytest.approx(-lr["pnl_if_home_weakens"])
    assert sr["carry_pnl_home"] == pytest.approx(-lr["carry_pnl_home"])
    assert short_res.data["total_pnl_if_home_strengthens"] == pytest.approx(
        -long_res.data["total_pnl_if_home_strengthens"]
    )


def test_fxh1_side_is_echoed_and_defaults_to_long() -> None:
    assert _book(None).data["rows"][0]["exposure_side"] == "long_foreign"
    assert _book("short_foreign").data["rows"][0]["exposure_side"] == "short_foreign"


def test_fxh1_unknown_side_is_an_explicit_input_error() -> None:
    result = _book("sideways")
    assert result.data["status"] == "input_error"
    assert "exposure_side" in result.data["reason"]
    assert result.data["rows"] == []


# ── FXH#2: manifest output contract (hedge_cost and named fields) ───────


_MUST_HAVE = (
    "pair", "spot", "exposure_notional", "hedge_notional", "residual_notional",
    "pnl_unhedged", "pnl_hedged", "hedge_cost", "as_of", "data_mode",
)


def test_fxh2_calc_returns_every_manifest_must_have_key() -> None:
    result = _run(_fn().execute(
        action="calc", pair="EURUSD", spot_rate=1.08, notional=1_000_000,
        base_rate=0.02, home_rate=0.03, hedge_ratio=0.5, spot_shock_pct=5.0,
        bid_ask_pips=2.0,
    ))
    for key in _MUST_HAVE:
        assert key in result.data, f"manifest must_have missing: {key}"


def test_fxh2_hedge_cost_is_hedge_notional_times_pips() -> None:
    """Manifest: hedge_cost = hedge_notional * bid_ask_pips / 10^4 (home ccy).
    500,000 hedged * 2 pips * 0.0001 = 100 USD."""
    result = _run(_fn().execute(
        action="calc", pair="EURUSD", spot_rate=1.08, notional=1_000_000,
        base_rate=0.02, home_rate=0.03, hedge_ratio=0.5, spot_shock_pct=5.0,
        bid_ask_pips=2.0,
    ))
    assert result.data["hedge_cost"] == pytest.approx(100.0)
    assert result.data["hedge_notional"] == pytest.approx(500_000.0)
    assert result.data["residual_notional"] == pytest.approx(500_000.0)
    assert result.data["pnl_unhedged"] == pytest.approx(1_000_000 * 1.08 * 0.05)
    assert result.data["pnl_hedged"] == pytest.approx(500_000 * 1.08 * 0.05 - 100.0)


def test_fxh2_jpy_home_uses_yen_pip_size() -> None:
    result = _run(_fn().execute(
        action="calc", pair="USDJPY", spot_rate=150.0, notional=1_000_000,
        base_rate=0.01, home_rate=0.02, hedge_ratio=0.5, spot_shock_pct=5.0,
        bid_ask_pips=2.0,
    ))
    # JPY quote pip = 0.01 -> 500,000 * 2 * 0.01 = 10,000 JPY
    assert result.data["hedge_cost"] == pytest.approx(10_000.0)


def test_fxh2_missing_bid_ask_is_flagged_not_silent() -> None:
    result = _run(_fn().execute(
        action="calc", pair="EURUSD", spot_rate=1.08, notional=1_000_000,
        base_rate=0.02, home_rate=0.03, hedge_ratio=0.5,
    ))
    assert "bid_ask_pips" in result.data["assumed_defaults"]
    assert result.data["assumed_values"]["bid_ask_pips"] == pytest.approx(2.0)
    assert result.data["hedge_cost"] == pytest.approx(100.0)


def test_fxh2_multi_currency_book_top_level_notionals_are_none_not_summed() -> None:
    """Foreign units of different currencies must never be summed."""
    result = _run(_fn().execute(
        action="calc", pair="EURUSD", hedge_ratio=0.5, spot_shock_pct=5.0,
        base_rate=0.02, home_rate=0.03, bid_ask_pips=2.0,
        exposures=[
            {"currency": "EUR", "notional": 100_000, "spot_rate": 1.08},
            {"currency": "GBP", "notional": 50_000, "spot_rate": 1.27},
        ],
    ))
    assert result.data["exposure_notional"] is None
    assert result.data["hedge_notional"] is None
    assert len(result.data["rows"]) == 2
    total_cost = sum(r["hedge_cost"] for r in result.data["rows"])
    assert result.data["hedge_cost"] == pytest.approx(total_cost)
