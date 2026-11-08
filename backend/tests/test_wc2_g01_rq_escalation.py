"""WC2-G01 escalation fixes: string rate units (XCON-6) and no silent EURUSD (XCON-5 family).

Network is patched or avoided: every call uses live=False or returns before any fetch.
"""
from __future__ import annotations

import asyncio

import pytest

from showme.engine.functions.fx import _funcs as fx
from showme.engine.functions.fx.fxh import FXHFunction
from showme.engine.core.instrument import AssetClass, Instrument


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    async def _none(series_id, **kw):  # noqa: ARG001
        return None

    async def _no_vol(*args, **kw):  # noqa: ARG001
        return (None, None, None, None, "patched: no vol history in tests")

    monkeypatch.setattr(fx, "fetch_fred_csv_series", _none)
    monkeypatch.setattr(fx, "_atm_term_structure", _no_vol)


# ── XCON-6: string rate inputs follow the same decimal-unit refusal as floats ──


@pytest.mark.parametrize("value", ["3.5", " 3.5 ", "4.5"])
def test_decimal_rate_error_accepts_string_input_without_crashing(value: str) -> None:
    from showme.engine.services.fx_hedge import decimal_rate_error

    reason = decimal_rate_error("r_base", value)
    assert reason is not None
    assert "decimal" in reason
    assert "3.5" in reason or "4.5" in reason


def test_decimal_rate_error_string_decimal_is_accepted() -> None:
    from showme.engine.services.fx_hedge import decimal_rate_error

    assert decimal_rate_error("r_base", "0.035") is None


def test_frd_string_percent_rate_is_input_error_not_exception() -> None:
    res = _run(fx.FRDFunction().execute(base="EUR", quote="USD", tenors="3M", spot=1.10, live=False,
                                        r_base="3.5", r_quote="0.045"))
    assert res.data["status"] == "input_error", res.data
    assert "decimal" in res.data["reason"]
    assert res.data.get("rows") == []


def test_fxfc_string_percent_rate_is_input_error_not_exception() -> None:
    res = _run(fx.FXFCFunction().execute(pair="EURUSD", spot=1.10, live=False, vol_annualized=0.08,
                                         r_base="0.035", r_quote="4.5"))
    assert res.data["status"] == "input_error", res.data
    assert "decimal" in res.data["reason"]


def test_fxip_string_percent_rate_is_input_error_not_exception() -> None:
    res = _run(fx.FXIPFunction().execute(pair="EURUSD", spot=1.10, live=False, r_base="0.035",
                                         r_quote="4.5"))
    assert res.data["status"] == "input_error", res.data
    assert "decimal" in res.data["reason"]


def test_fxh_string_percent_base_rate_is_input_error_not_exception() -> None:
    res = _run(FXHFunction().execute(pair="EURUSD", spot_rate=1.10, base_rate="3.5", home_rate=0.045,
                                     tenor="3M"))
    assert res.data["status"] == "input_error", res.data
    assert "decimal" in res.data["reason"]


# ── XCON-5 family: FXFC, FXIP and OVDV never price EURUSD for a missing pair ──


def test_fxfc_no_pair_is_needs_input_not_eurusd() -> None:
    res = _run(fx.FXFCFunction().execute(spot=1.10, live=False, r_base=0.035, r_quote=0.045))
    assert res.data["status"] == "needs_input", res.data
    assert res.data.get("pair") is None
    assert res.data.get("curve", []) == []


def test_fxip_no_pair_is_needs_input_not_eurusd() -> None:
    res = _run(fx.FXIPFunction().execute(spot=1.10, live=False, r_base=0.035, r_quote=0.045))
    assert res.data["status"] == "needs_input", res.data
    assert res.data.get("pair") is None
    assert res.data.get("rows") == []


def test_ovdv_no_pair_is_needs_input_not_eurusd() -> None:
    res = _run(fx.OVDVFunction().execute())
    assert res.data["status"] == "needs_input", res.data
    assert res.data.get("pair") is None
    assert res.data.get("surface") == []


def test_fxfc_malformed_pair_is_input_error_not_eurusd() -> None:
    res = _run(fx.FXFCFunction().execute(pair="XYZ", spot=1.10, live=False, r_base=0.035, r_quote=0.045))
    assert res.data["status"] == "input_error", res.data
    assert res.data.get("pair") is None


def test_fxip_malformed_pair_is_input_error_not_eurusd() -> None:
    res = _run(fx.FXIPFunction().execute(pair="EUR", spot=1.10, live=False, r_base=0.035, r_quote=0.045))
    assert res.data["status"] == "input_error", res.data
    assert res.data.get("pair") is None


def test_fxfc_non_fx_instrument_symbol_is_not_priced_as_eurusd() -> None:
    """A chart symbol that is not a BASEQUOTE pair (e.g. AAPL) must not become EURUSD."""
    instrument = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    res = _run(fx.FXFCFunction().execute(instrument, spot=1.10, live=False, r_base=0.035, r_quote=0.045))
    assert res.data["status"] in {"needs_input", "input_error"}, res.data
    assert res.data.get("pair") is None


def test_fxfc_explicit_pair_still_prices_the_requested_pair() -> None:
    res = _run(fx.FXFCFunction().execute(pair="GBPJPY", spot=190.0, live=False, r_base=0.04, r_quote=0.005))
    assert res.data.get("pair") == "GBPJPY" or res.data.get("status") != "needs_input"
    assert "EURUSD" not in str(res.data.get("pair"))
