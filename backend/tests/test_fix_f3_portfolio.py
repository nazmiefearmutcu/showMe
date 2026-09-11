"""F3 fix-lane regressions — portfolio-generic family.

Evidence pins for the 2026-09-11 function-audit fixes owned by lane F3:

* MGN — the fabricated sample book must be labelled on every surface so the
  shared ``portfolioDataMode`` classifier badges SAMPLE/MODEL (audit A4 C).
* BTFW — the live path that falls back to the synthetic sine history must
  declare ``synthetic_history`` + a warning (audit A4 M).
* BTUNE — model rows carry the parameter dict verbatim (audit A6 M).
* REBA — explicit zero-weight targets are kept and an all-zero book is an
  honest ``input_error`` instead of a ZeroDivisionError 500 (audit A1 M).
* STRS — the compare path and the empty-portfolio branch (audit A4 M).
"""

from __future__ import annotations

import asyncio

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio.btfw import BTFWFunction
from showme.engine.functions.portfolio.btune import BTUNEFunction
from showme.engine.functions.portfolio.mgn import MGNFunction
from showme.engine.functions.portfolio.reba import REBAFunction


def _run(coro):
    # Fresh event loop per test — mirrors test_session03_codes.py.
    return asyncio.run(coro)


@pytest.fixture
def deps() -> FunctionDeps:
    return FunctionDeps()


@pytest.fixture
def equity() -> Instrument:
    return Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


# ── MGN: sample book disclosure ─────────────────────────────────────────


def test_mgn_sample_book_is_labelled_on_every_surface(deps):
    """No positions supplied → the fabricated book must be unmistakably SAMPLE."""
    res = _run(MGNFunction(deps).execute())
    assert res.data["status"] == "sample"
    assert res.data["is_sample"] is True
    assert res.data["source_mode"] == "sample_margin_positions"
    assert "sample_margin_positions" in res.sources
    assert res.metadata["live"] is False
    assert res.metadata["is_sample"] is True
    assert res.warnings and "illustrative SAMPLE position" in res.warnings[0]
    # The table still renders — disclosure must not require wiping the rows.
    assert res.data["rows"]


def test_mgn_supplied_positions_are_not_labelled_sample(deps):
    """Real caller-supplied positions take the unlabelled path."""
    positions = [
        {
            "symbol": "AAPL",
            "asset_class": "EQUITY",
            "quantity": 10,
            "avg_cost": 100,
            "last": 110,
            "currency": "USD",
        }
    ]
    res = _run(MGNFunction(deps).execute(positions=positions))
    assert res.data.get("status") != "sample"
    assert res.data.get("is_sample") is not True
    assert "sample_margin_positions" not in res.sources


# ── BTFW: synthetic-history admission ───────────────────────────────────


def test_btfw_live_without_provider_flags_synthetic_history(deps):
    """live=true with no yfinance runs real folds on a SYNTHETIC sine ramp —
    that substitution must be a machine-readable flag + visible warning."""
    res = _run(
        BTFWFunction(deps).execute(
            instrument=Instrument(symbol="TEST", asset_class=AssetClass.EQUITY),
            live=True,
            strategy="sma_crossover",
        )
    )
    assert res.data["status"] == "ok"
    assert res.metadata.get("synthetic_history") is True
    assert any("synthetic placeholder history" in w for w in (res.warnings or []))
    assert "local_backtest_model" in res.sources


# ── BTUNE: params dict shipped verbatim ─────────────────────────────────


def test_btune_model_rows_carry_params_dict(deps, equity):
    """The pane renders rows[].params; it must be a dict (never flattened to
    a string on the backend)."""
    res = _run(BTUNEFunction(deps).execute(instrument=equity))
    assert res.data["status"] == "reference"
    first = res.data["rows"][0]
    assert isinstance(first["params"], dict)
    assert {"fast", "slow"} <= set(first["params"])


# ── REBA: zero-weight targets + zero-sum guard ──────────────────────────


def test_reba_zero_sum_targets_do_not_500(deps):
    """An all-zero book has nothing to normalize; previously v / s raised
    ZeroDivisionError and the request 500'd."""
    res = _run(REBAFunction(deps).execute(targets={"QQQ": 0.0}))
    assert res.data["status"] == "input_error"
    assert res.data["rows"] == []
    assert res.data["reason"]
    assert res.warnings


def test_reba_keeps_explicit_zero_weight_targets(deps):
    """'SPY:60, QQQ:0' is a full-exit intent — QQQ must stay in the target
    weights (at 0), and the supplied capital must drive the notional."""
    res = _run(
        REBAFunction(deps).execute(targets={"SPY": 0.6, "QQQ": 0.0}, max_notional=250_000)
    )
    assert res.data["target_weights_pct"]["QQQ"] == 0.0
    assert res.data["target_weights_pct"]["SPY"] == pytest.approx(100.0)
    assert res.data["total_value"] == pytest.approx(250_000.0)


# ── STRS: compare + empty-portfolio coverage ────────────────────────────


def _fake_portfolio_module(monkeypatch, positions):
    from showme.engine.functions.portfolio import strs as strs_mod

    class _Portfolio:
        def __init__(self):
            self.positions = positions

        def import_legacy_crypto(self):
            return None

    monkeypatch.setattr(strs_mod, "PortfolioState", _Portfolio)
    return strs_mod


class _Position:
    def __init__(self, symbol: str, quantity: float, avg_cost: float):
        self.instrument = Instrument(symbol=symbol, asset_class=AssetClass.EQUITY)
        self.quantity = quantity
        self.avg_cost = avg_cost


def test_strs_compare_path_returns_rows_and_summary(monkeypatch):
    strs_mod = _fake_portfolio_module(
        monkeypatch, [_Position("AAPL", 10.0, 100.0)]
    )
    res = _run(strs_mod.STRSFunction().execute(action="compare"))
    assert res.data["comparisons"], "compare must produce at least one scenario"
    assert res.data["rows"] == res.data["comparisons"]
    assert res.data["summary"]["price_source"] == "portfolio_state_cost"
    assert res.data["summary"]["positions"] == 1


def test_strs_empty_portfolio_stays_honest(monkeypatch):
    strs_mod = _fake_portfolio_module(monkeypatch, [])
    res = _run(strs_mod.STRSFunction().execute(action="compare"))
    assert res.data["status"] == "empty_portfolio"
    assert res.data["rows"] == []
    assert res.data["next_actions"]
