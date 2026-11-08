"""BTUNE#3 / BTUNE#4 regressions: out-of-sample ranking, declared inputs,
and counted (not silent) skipped parameter combinations.

Network is never touched; yfinance is replaced by an in-memory fake.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio import btune as btune_mod
from showme.engine.functions.portfolio.btune import BTUNEFunction


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def equity() -> Instrument:
    return Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


def _price_frame(bars: int = 400, seed: int = 7) -> pd.DataFrame:
    """Deterministic random-walk OHLCV used as the fake yfinance payload."""
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.012, bars)))
    index = pd.bdate_range(end=datetime(2026, 10, 30), periods=bars)
    return pd.DataFrame(
        {"open": close, "high": close * 1.01, "low": close * 0.99,
         "close": close, "volume": 1_000_000},
        index=index,
    )


class _FakeYF:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    async def fetch(self, request):  # noqa: ARG002 - mirrors the adapter signature
        return self.frame


# ── BTUNE#3: out-of-sample ranking and declared inputs honoured ──────────


def _live_deps(bars: int = 400) -> FunctionDeps:
    return FunctionDeps(yfinance=_FakeYF(_price_frame(bars)))


def test_btune_ranks_by_out_of_sample_metric(equity):
    res = _run(BTUNEFunction(_live_deps()).execute(
        instrument=equity, live_backtest=True, grid={"fast": [5, 10], "slow": [30, 50]},
    ))
    assert res.data["status"] == "ok"
    rows = res.data["full_results"]
    assert len(rows) == 4
    best = res.data["best_params"]
    top_is = res.data["top_n_results"][0]
    assert top_is["params"] == best
    assert top_is["metric_in_sample"] == max(r["metric_in_sample"] for r in rows if r["metric_in_sample"] is not None)
    assert res.data["best_metric_oos"] == top_is["metric_oos"]
    assert all("metric_in_sample" in r and "overfit_gap" in r for r in rows)


class _Stats:
    def __init__(self, metrics):
        self.metrics = metrics


class _TaggedStrategy:
    def __init__(self, params):
        self.params = params

    def __call__(self, bars, state):  # pragma: no cover - never executed by the fake
        return None


def _strategy_probe(name, params):  # noqa: ARG001 - mirrors _build_strategy signature
    return _TaggedStrategy(dict(params))


class _SplitAdversarialBacktest:
    """Train slice favours large fast; test slice favours small fast (adversarial)."""

    def __init__(self, df, strategy, initial_cash, fee_bps, eval_start=None):  # noqa: ARG002
        self.strategy = strategy
        self.eval_start = eval_start

    def run(self):
        p = self.strategy.params
        is_value = p["fast"] * 10 + p["slow"] / 100
        oos_value = -(p["fast"] * 10) + p["slow"] / 100
        value = oos_value if self.eval_start is not None else is_value
        metrics = {
            "sharpe": value, "cagr": 0.1, "calmar": 1.0, "sortino": 1.0,
            "total_return": 0.1, "max_drawdown": -0.1, "trades": 3,
        }
        return _Stats(metrics)


def test_btune_selects_on_train_slice_not_test_slice(equity, monkeypatch):
    monkeypatch.setattr(btune_mod, "_build_strategy", _strategy_probe)
    monkeypatch.setattr(btune_mod, "Backtest", _SplitAdversarialBacktest)
    res = _run(BTUNEFunction(_live_deps()).execute(
        instrument=equity, live_backtest=True, grid={"fast": [5, 10, 30], "slow": [30, 50]},
    ))
    assert res.data["status"] == "ok"
    # Chosen on the train slice: fast=30 has the best in-sample sharpe.
    assert res.data["best_params"] == {"fast": 30, "slow": 50}
    # The reported out-of-sample figure is the chosen set's own test-slice value,
    # not the grid maximum on the test slice (which belongs to fast=5).
    assert res.data["best_metric_oos"] == pytest.approx(-300 + 0.5)
    assert res.data["top_n_results"][0]["params"] == {"fast": 30, "slow": 50}
    assert res.data["top_n_results"][0]["metric_in_sample"] == pytest.approx(300.5)
    assert max(r["metric_oos"] for r in res.data["full_results"]) == pytest.approx(-50 + 0.5)


def test_btune_declared_inputs_are_honoured(equity):
    res = _run(BTUNEFunction(_live_deps()).execute(
        instrument=equity, live_backtest=True,
        param_grid={"fast": [5, 10, 15], "slow": [30, 50]},
        top_n=2, metric="calmar", train_pct=0.6, fee_bps=20,
    ))
    assert res.data["status"] == "ok"
    assert len(res.data["top_n_results"]) == 2
    assert res.data["metric"] == "calmar"
    assert res.data["fee_bps"] == 20
    split = res.data["split"]
    assert split["train_pct"] == 0.6
    assert split["train_bars"] + split["test_bars"] == 400
    assert split["train_bars"] == int(400 * 0.6)


def test_btune_random_search_samples_n_combinations(equity):
    res = _run(BTUNEFunction(_live_deps()).execute(
        instrument=equity, live_backtest=True, search_mode="random", n_samples=10,
        param_grid={"fast": [5, 10, 15, 20, 30], "slow": [30, 50, 100, 200]},
    ))
    assert res.data["status"] == "ok"
    assert res.data["combos_tested"] == 10
    assert len(res.data["full_results"]) == 10


def test_btune_unsupported_metric_is_input_error(equity):
    res = _run(BTUNEFunction(_live_deps()).execute(
        instrument=equity, live_backtest=True, metric="profit_factor",
    ))
    assert res.data["status"] == "input_error"
    assert res.data["best_params"] is None
    assert res.data.get("reason")


# ── BTUNE#4: skipped combinations are counted and surfaced ───────────────


def test_btune_counts_and_warns_on_skipped_combinations(equity, monkeypatch):
    real_build = btune_mod._build_strategy

    def flaky_build(name, params):
        if params["fast"] == 15:
            raise RuntimeError("boom for fast=15")
        return real_build(name, params)

    monkeypatch.setattr(btune_mod, "_build_strategy", flaky_build)
    res = _run(BTUNEFunction(_live_deps()).execute(
        instrument=equity, live_backtest=True, grid={"fast": [5, 10, 15], "slow": [30, 50]},
    ))
    assert res.data["status"] == "ok"
    assert res.data["combos_tested"] == 4
    assert res.data["combos_skipped"] == 2
    assert any("skipped" in w and "2" in w for w in res.warnings)


# ── BTUNE#3 seed: declared options are the ones the handler honours ─────


def test_btune_seed_declares_only_supported_options():
    from showme.manifest.seeds.btune_seed import btune

    inputs = {i.name: i for i in btune.inputs}
    assert "live_backtest" in inputs
    assert "profit_factor" not in (inputs["metric"].options or [])
    assert inputs["frequency"].options == ["1d"]
    assert set(inputs["strategy_id"].options or []) == {"sma_crossover", "rsi_meanrev"}


def test_btune_seed_declares_fee_and_describes_train_selection():
    from showme.manifest.seeds.btune_seed import btune

    inputs = {i.name: i for i in btune.inputs}
    assert "fee_bps" in inputs
    assert "ranked by metric_oos" not in btune.methodology
    assert "metric_in_sample" in btune.methodology
    assert "test slice is not used" in btune.methodology
    names = [t.name for t in btune.semantic_tests]
    assert "btune_best_params_picked_on_oos_not_in_sample" not in names
    assert "btune_best_params_picked_on_train_not_test" in names


def test_btune_seed_provider_chain_matches_handler():
    from showme.manifest.seeds.btune_seed import btune

    assert btune.provider_chain.primary == "yfinance"
    assert btune.provider_chain.fallbacks == []
    assert "MODELED" not in [m.name for m in btune.provider_chain.acceptable_modes]


def test_btune_seed_fraction_columns_are_not_percent_kind():
    from showme.manifest.seeds.btune_seed import btune

    cols = {c.key: c for c in btune.table_schema.columns}
    for key in ("cagr", "max_drawdown"):
        assert cols[key].kind != "percent"
        assert cols[key].unit in (None, "")
