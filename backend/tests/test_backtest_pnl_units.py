"""Dimensional correctness of the backtest P&L, and the walk-forward contract.

These are the tests that would have caught the shipped bug: equity was marked
as ``cash += pos * (price - last_price)`` — the P&L of ONE SHARE — while the
fee was charged on ``notional = cash`` (~$10,000). On a $100 stock a 1% move
earned $1 while one round trip at 5 bps cost ~$5, so every Sharpe / CAGR /
Calmar / drawdown BTFW reported was dominated by a unit error.

Position basis under test: ``pos`` is an exposure fraction of current equity,
and both the mark-to-market and the fee use that same basis.
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from showme.engine.services.backtest_framework import (
    Backtest,
    LeakageError,
    WalkForwardBacktest,
)


def _bars(closes: list[float], start: str = "2024-01-01") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(closes), freq="B")
    return pd.DataFrame({"close": closes}, index=idx)


def _always_long(bars, state):
    return 1


def _always_flat(bars, state):
    return 0


# ── the dimensional bug ────────────────────────────────────────────────────
def test_position_is_not_earned_on_the_bar_it_was_opened():
    """No same-bar lookahead: a position decided at bar i earns from bar i+1.

    Every expectation below carries a leading flat bar for this reason.
    """
    res = Backtest(_bars([100.0, 101.0]), _always_long, warmup=0,
                   fee_bps=0.0, initial_cash=10_000.0).run()
    assert res.final_equity == pytest.approx(10_000.0, rel=1e-12)


def test_one_percent_move_on_long_is_exactly_one_percent_equity():
    """With zero fees, +1% price on a full long must be +1% equity.

    Under the old share-based mark this produced +$1 on $10,000 (+0.01%),
    i.e. it was wrong by a factor of the share price.
    """
    bars = _bars([100.0, 100.0, 101.0])
    res = Backtest(bars, _always_long, warmup=0, fee_bps=0.0,
                   initial_cash=10_000.0).run()
    assert res.final_equity == pytest.approx(10_100.0, rel=1e-12)


def test_percent_move_is_independent_of_price_level():
    """The same % move must give the same equity change at any price level.

    This is the sharpest statement of the bug: the old code's P&L scaled with
    the absolute price, so a $10 stock and a $1000 stock with identical
    returns produced 100x different equity curves.
    """
    cheap = Backtest(_bars([10.0, 10.0, 10.1]), _always_long, warmup=0,
                     fee_bps=0.0, initial_cash=10_000.0).run()
    dear = Backtest(_bars([1000.0, 1000.0, 1010.0]), _always_long, warmup=0,
                    fee_bps=0.0, initial_cash=10_000.0).run()
    assert cheap.final_equity == pytest.approx(dear.final_equity, rel=1e-12)
    assert cheap.final_equity == pytest.approx(10_100.0, rel=1e-12)


def test_short_position_earns_on_a_fall():
    bars = _bars([100.0, 100.0, 99.0])
    res = Backtest(bars, lambda b, s: -1, warmup=0, fee_bps=0.0,
                   initial_cash=10_000.0).run()
    assert res.final_equity == pytest.approx(10_100.0, rel=1e-12)


def test_flat_position_never_moves_equity():
    bars = _bars([100.0, 130.0, 70.0, 105.0])
    res = Backtest(bars, _always_flat, warmup=0, fee_bps=0.0,
                   initial_cash=10_000.0).run()
    assert res.final_equity == pytest.approx(10_000.0, rel=1e-12)


def test_compounding_is_multiplicative():
    """Two consecutive +10% bars must give +21%, not +20%."""
    bars = _bars([100.0, 100.0, 110.0, 121.0])
    res = Backtest(bars, _always_long, warmup=0, fee_bps=0.0,
                   initial_cash=10_000.0).run()
    assert res.final_equity == pytest.approx(12_100.0, rel=1e-12)


# ── fees charged on the traded notional ────────────────────────────────────
def test_single_entry_costs_exactly_the_configured_bps():
    """Opening 0 -> +1 turns over 1x equity, so it costs exactly fee_bps."""
    bars = _bars([100.0, 100.0, 100.0])          # flat price isolates the fee
    res = Backtest(bars, _always_long, warmup=1, fee_bps=25.0,
                   initial_cash=10_000.0).run()
    assert len(res.trades) == 1
    assert res.trades[0]["notional"] == pytest.approx(10_000.0, rel=1e-12)
    assert res.final_equity == pytest.approx(10_000.0 * (1 - 0.0025), rel=1e-12)


def test_round_trip_cost_equals_bps_on_actual_traded_notional():
    """0 -> +1 -> 0 turns over 1x equity twice, so it costs 2 x fee_bps."""
    closes = [100.0] * 6
    state = {"n": 0}

    def enter_then_exit(bars, s):
        state["n"] += 1
        return 1 if state["n"] <= 2 else 0

    res = Backtest(_bars(closes), enter_then_exit, warmup=1, fee_bps=10.0,
                   initial_cash=10_000.0).run()
    assert len(res.trades) == 2, res.trades
    total_fee = sum(t["fee"] for t in res.trades)
    traded_notional = sum(t["notional"] for t in res.trades)
    # The invariant: fees are exactly bps x the notional actually traded.
    assert total_fee == pytest.approx(traded_notional * 0.0010, rel=1e-12)
    # And a round trip at 10 bps costs ~20 bps of equity (second leg is
    # charged on the slightly reduced equity, hence the loose tolerance).
    assert res.final_equity == pytest.approx(10_000.0 * (1 - 0.0020), rel=1e-4)


def test_flip_turns_over_double_an_open():
    """+1 -> -1 changes exposure by 2, so it must cost 2x a 0 -> +1 open."""
    closes = [100.0] * 6
    state = {"n": 0}

    def long_then_flip(bars, s):
        state["n"] += 1
        return 1 if state["n"] <= 2 else -1

    res = Backtest(_bars(closes), long_then_flip, warmup=1, fee_bps=10.0,
                   initial_cash=10_000.0).run()
    assert len(res.trades) == 2
    open_trade, flip_trade = res.trades
    assert flip_trade["notional"] == pytest.approx(2 * open_trade["notional"], rel=1e-3)


def test_zero_fee_means_zero_cost():
    closes = [100.0] * 8
    state = {"n": 0}

    def churn(bars, s):
        state["n"] += 1
        return 1 if state["n"] % 2 else -1

    res = Backtest(_bars(closes), churn, warmup=1, fee_bps=0.0,
                   initial_cash=10_000.0).run()
    assert res.trades, "strategy should have traded"
    assert res.final_equity == pytest.approx(10_000.0, rel=1e-12)


def test_single_pass_is_labelled_in_sample():
    """Backtest.run() must not let a caller mistake it for an OOS result."""
    res = Backtest(_bars([100.0] * 5), _always_long, warmup=1).run()
    assert res.metrics["in_sample"] is True


# ── walk-forward ───────────────────────────────────────────────────────────
def _trend_bars(n: int = 600) -> pd.DataFrame:
    closes = [100.0]
    for i in range(n - 1):
        closes.append(closes[-1] * (1.0 + 0.0004 + 0.004 * math.sin(i / 11.0)))
    return _bars(closes)


def test_walk_forward_test_slices_are_strictly_after_train():
    """The manifest's btfw_test_slices_are_strictly_after_train, enforced."""
    wf = WalkForwardBacktest(_trend_bars(), "sma_crossover", n_splits=4)
    res = wf.run()
    assert len(res.folds) >= 2
    for f in res.folds:
        assert f.train_end < f.test_start, (
            f"fold {f.fold}: train ends {f.train_end}, test starts {f.test_start}"
        )


def test_walk_forward_folds_advance_monotonically():
    res = WalkForwardBacktest(_trend_bars(), "sma_crossover", n_splits=4).run()
    starts = [f.test_start for f in res.folds]
    assert starts == sorted(starts)
    for a, b in zip(res.folds, res.folds[1:]):
        assert a.test_end <= b.test_start


def test_walk_forward_leakage_tripwire_fires():
    """The boundary is asserted, not assumed — prove the tripwire is live."""
    wf = WalkForwardBacktest(_trend_bars(), "sma_crossover", n_splits=4)
    original = wf._fit

    def _sabotage(bars, train_lo, train_hi):
        raise LeakageError("simulated")

    wf._fit = _sabotage
    with pytest.raises(LeakageError):
        wf.run()
    wf._fit = original


def test_anchored_train_window_grows_rolling_does_not():
    bars = _trend_bars()
    anchored = WalkForwardBacktest(bars, "sma_crossover", n_splits=4,
                                   mode="anchored").run()
    rolling = WalkForwardBacktest(bars, "sma_crossover", n_splits=4,
                                  mode="rolling").run()
    a_lens = [f.train_bars for f in anchored.folds]
    r_lens = [f.train_bars for f in rolling.folds]
    assert a_lens == sorted(a_lens) and a_lens[-1] > a_lens[0], (
        f"anchored train window should expand, got {a_lens}"
    )
    assert max(r_lens) - min(r_lens) <= 2, (
        f"rolling train window should stay ~constant, got {r_lens}"
    )


def test_walk_forward_reports_worst_fold_and_is_not_in_sample():
    res = WalkForwardBacktest(_trend_bars(), "sma_crossover", n_splits=4).run()
    worst = res.summary["worst_fold"]
    assert worst is not None
    assert worst["oos_return"] == min(f.oos_return for f in res.folds)
    assert res.summary["in_sample"] is False
    assert 0.0 <= res.summary["positive_steps_pct"] <= 1.0


def test_walk_forward_fits_parameters_on_train_slices():
    """Fitting must actually happen — a grid strategy picks per-fold params."""
    res = WalkForwardBacktest(_trend_bars(), "sma_crossover", n_splits=4).run()
    for f in res.folds:
        assert set(f.params) == {"fast", "slow"}
        assert f.params["fast"] < f.params["slow"]


def test_walk_forward_oos_curve_starts_at_initial_cash():
    res = WalkForwardBacktest(_trend_bars(), "sma_crossover", n_splits=4,
                              initial_cash=25_000.0).run()
    assert float(res.oos_equity_curve.iloc[0]) == pytest.approx(25_000.0)
    assert len(res.oos_equity_curve) > len(res.folds)


def test_walk_forward_rejects_too_little_history():
    with pytest.raises(ValueError):
        WalkForwardBacktest(_bars([100.0] * 40), "sma_crossover",
                            n_splits=5, warmup=30).run()


def test_walk_forward_rejects_bad_configuration():
    bars = _trend_bars()
    with pytest.raises(ValueError):
        WalkForwardBacktest(bars, "sma_crossover", n_splits=1)
    with pytest.raises(ValueError):
        WalkForwardBacktest(bars, "sma_crossover", train_pct=0.99)
    with pytest.raises(ValueError):
        WalkForwardBacktest(bars, "sma_crossover", mode="sideways")
    with pytest.raises(ValueError):
        WalkForwardBacktest(bars, "no_such_strategy")


# ── BTFW end-to-end: the shipped function must return real OOS output ──────
def test_btfw_reports_out_of_sample_not_in_sample():
    """BTFW's user-facing payload must match what its manifest promises.

    It shipped `"methodology": "Single-symbol walk-forward backtest"` while
    Backtest.run() was a single in-sample pass with no train/test split at all.
    """
    import asyncio

    from showme.engine.core.instrument import AssetClass, Instrument
    from showme.engine.functions.portfolio.btfw import BTFWFunction

    inst = Instrument(symbol="TEST", asset_class=AssetClass.EQUITY)
    res = asyncio.run(BTFWFunction().execute(instrument=inst, live=True,
                                             strategy="sma_crossover"))
    d = res.data
    assert d["status"] == "ok"
    # The manifest's declared output contract, actually delivered.
    for key in ("oos_equity_curve", "per_step_metrics", "summary"):
        assert key in d, f"missing manifest-promised field {key!r}"
    s = d["summary"]
    assert s["in_sample"] is False
    assert s["n_splits"] >= 2
    assert s["worst_fold"] is not None, "worst fold must always be reported"
    assert len(d["per_step_metrics"]) == s["n_splits"]
    # Every fold's test slice starts strictly after its train slice.
    for step in d["per_step_metrics"]:
        assert step["train_end"] < step["test_start"]


def test_btfw_placeholder_reports_no_metrics():
    """The no-backtest path must not ship invented Sharpe/drawdown numbers.

    It used to return a hardcoded sharpe=1.18 / max_drawdown=-0.061 / trades=8
    under `"status": "reference"`.
    """
    import asyncio

    from showme.engine.core.instrument import AssetClass, Instrument
    from showme.engine.functions.portfolio.btfw import BTFWFunction

    inst = Instrument(symbol="TEST", asset_class=AssetClass.EQUITY)
    res = asyncio.run(BTFWFunction().execute(instrument=inst, live=False,
                                             strategy="sma_crossover"))
    d = res.data
    assert d["is_placeholder"] is True
    assert d["measured"] is False
    assert d["metrics"]["sharpe"] is None
    assert d["metrics"]["max_drawdown"] is None
    assert d["summary"]["oos_sharpe"] is None
    assert res.warnings, "a placeholder payload must carry a warning"
    assert "walk-forward" not in d["methodology"].lower()
