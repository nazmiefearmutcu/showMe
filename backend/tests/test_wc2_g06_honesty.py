"""WC2-G06 honesty regressions: OVME placeholder inputs, TAUC template horizon.

Each test reproduces a finding through the public handler with the network
patched out (no adapter is reachable here).
"""
from __future__ import annotations

import asyncio

from showme.engine.functions.derivative.ovme import OVMEFunction


def _run_ovme(**params):
    fn = OVMEFunction()
    fn.deps = None
    return asyncio.run(fn.execute(**params))


def test_ovme_with_no_inputs_does_not_price_a_demo_option() -> None:
    res = _run_ovme()
    assert res.data["status"] == "needs_input"
    assert "price" not in res.data
    assert res.data["curve"] == []
    assert set(res.data["missing_inputs"]) == {"spot", "strike", "years_to_expiry", "vol"}


def test_ovme_missing_spot_is_not_filled_with_100() -> None:
    res = _run_ovme(strike=100, years_to_expiry=0.5, vol=0.25)
    assert res.data["status"] == "needs_input"
    assert res.data["missing_inputs"] == ["spot"]
    assert "price" not in res.data


def test_ovme_non_numeric_input_is_an_input_error_not_a_crash() -> None:
    res = _run_ovme(spot="abc", strike=100, years_to_expiry=0.5, vol=0.25)
    assert res.data["status"] == "input_error"
    assert any("spot" in w for w in res.warnings)


# ---------------------------------------------------------------- TAUC#2
from datetime import date, timedelta  # noqa: E402

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.functions.bond.tauc import TAUCFunction  # noqa: E402


def _tauc_reference(**params):
    return asyncio.run(TAUCFunction(FunctionDeps()).execute(reference=True, **params))


def test_tauc_reference_model_honours_the_horizon() -> None:
    res = _tauc_reference(horizon_days=7)
    today = date.today()
    rows = res.data["rows"]
    assert rows, "the 7-day window still holds the nearest model auctions"
    for row in rows:
        day = date.fromisoformat(row["auction_date"][:10])
        assert today - timedelta(days=1) <= day <= today + timedelta(days=7), row


def test_tauc_reference_model_honours_the_limit() -> None:
    res = _tauc_reference(horizon_days=30, limit=2)
    assert len(res.data["rows"]) == 2


def test_tauc_reference_model_invents_no_offering_sizes() -> None:
    res = _tauc_reference(horizon_days=30)
    assert res.data["rows"]
    for row in res.data["rows"]:
        assert row["offering_amount"] is None, row
    assert all(slot["total_offering"] is None for slot in res.data["by_type"])


# ---------------------------------------------------------------- FSRC#1-RQ
from showme.engine.functions.screen._funcs import FSRCFunction  # noqa: E402


def test_fsrc_rows_mark_expense_and_dividend_as_curated_reference() -> None:
    out = asyncio.run(FSRCFunction(deps=FunctionDeps()).execute(query="expenseRatio <= 0.001"))
    assert out.data["rows"]
    for row in out.data["rows"]:
        assert row.get("expense_state") == "reference", row["symbol"]
        assert row.get("dividend_state") == "reference", row["symbol"]


def test_fsrc_field_dictionary_documents_reference_states() -> None:
    out = asyncio.run(FSRCFunction(deps=FunctionDeps()).execute(query="expenseRatio <= 0.001"))
    fields = {entry["field"] for entry in out.data["field_dictionary"]}
    assert {"expense_state", "dividend_state"} <= fields


# ---------------------------------------------------------------- BTUNE#3-RQ
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from datetime import datetime as _datetime  # noqa: E402

from showme.engine.core.instrument import AssetClass, Instrument  # noqa: E402
from showme.engine.functions.portfolio.btune import BTUNEFunction  # noqa: E402
from showme.manifest.seeds.btune_seed import btune as _BTUNE_SEED  # noqa: E402


class _BtuneFakeYF:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    async def fetch(self, request):  # noqa: ARG002 - in-memory, no network
        return self.frame


def _btune_frame(bars: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.012, bars)))
    index = pd.bdate_range(end=_datetime(2026, 10, 30), periods=bars)
    return pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99,
                         "close": close, "volume": 1_000_000}, index=index)


_AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
_SMALL_GRID = {"fast": [5, 10], "slow": [30, 50]}


def _btune(deps, **params):
    return asyncio.run(BTUNEFunction(deps).execute(instrument=_AAPL, **params))


def test_btune_methodology_ranks_on_the_train_slice_like_the_seed() -> None:
    res = _btune(FunctionDeps(yfinance=_BtuneFakeYF(_btune_frame())),
                 live_backtest=True, grid=_SMALL_GRID)
    assert res.data["status"] == "ok"
    text = res.data["methodology"]
    assert "out-of-sample value" not in text
    assert "ranked by the in-sample (train-slice) value" in text


def test_btune_non_ok_results_carry_every_seed_must_have_field() -> None:
    cases = {
        "needs_input": _btune(FunctionDeps()),
        "provider_unavailable": _btune(FunctionDeps(), live_backtest=True, grid=_SMALL_GRID),
        "input_error": _btune(FunctionDeps(), live_backtest=True, metric="bogus"),
    }
    for label, res in cases.items():
        missing = [k for k in _BTUNE_SEED.output_contract.must_have if k not in res.data]
        assert missing == [], (label, missing)
        assert res.data["symbol"] == "AAPL", label


def test_btune_results_carry_the_card_slot_fields() -> None:
    ok = _btune(FunctionDeps(yfinance=_BtuneFakeYF(_btune_frame())),
                live_backtest=True, grid=_SMALL_GRID)
    off = _btune(FunctionDeps())
    for label, res in (("ok", ok), ("needs_input", off)):
        for slot in ("evaluations_count", "paper_mode", "data_mode"):
            assert slot in res.data, (label, slot)
    assert ok.data["data_mode"] == "live_yfinance"
    assert off.data["data_mode"] == "unavailable"


def test_ovme_heston_non_numeric_parameter_is_an_input_error_not_a_crash() -> None:
    res = _run_ovme(spot=100, strike=100, years_to_expiry=0.5, vol=0.25,
                    model="heston", kappa="fast", paths=2000, steps=20)
    assert res.data["status"] == "input_error"
    assert "price" not in res.data
    assert any("kappa" in w for w in res.warnings)


def test_ovme_heston_non_finite_parameter_is_an_input_error() -> None:
    res = _run_ovme(spot=100, strike=100, years_to_expiry=0.5, vol=0.25,
                    model="heston", rho="nan", paths=2000, steps=20)
    assert res.data["status"] == "input_error"
    assert any("rho" in w for w in res.warnings)
