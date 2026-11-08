"""OVDV data policy: no realized-vol history means an explicit provider_unavailable state.

Before this fix, when yfinance returned no usable daily closes the pane emitted a
full tenor x delta surface with status ok, built from hard-coded reference vols
(0.085 / 0.095 / 0.22) plus an invented +0.0015 per-tenor slope. A tenor whose
realized vol was exactly zero was silently replaced by the same constant.

Network is patched: ``_close_series`` is replaced so no provider is called.
"""
from __future__ import annotations

import asyncio

import pytest

from showme.engine.functions.fx import _funcs as fx

REFERENCE_CONSTANTS_PCT = (8.5, 9.5, 22.0)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def no_history(monkeypatch):
    async def _empty_close_series(fn, pair, params):  # noqa: ARG001
        return []

    monkeypatch.setattr(fx, "_close_series", _empty_close_series)


@pytest.fixture
def flat_history(monkeypatch):
    async def _flat_close_series(fn, pair, params):  # noqa: ARG001
        return [1.10] * 400

    monkeypatch.setattr(fx, "_close_series", _flat_close_series)


def test_no_history_is_explicit_provider_unavailable_not_a_surface(no_history):
    result = _run(fx.OVDVFunction().execute(pair="EURUSD"))
    data = result.data

    assert data["status"] == "provider_unavailable"
    assert isinstance(data.get("reason"), str) and data["reason"].strip()
    assert data.get("next_actions"), "unavailable state must say what to do next"
    assert data["surface"] == [], "no surface may be emitted from reference constants"
    assert data["series"] == []
    assert data["cards"]["atm_vol_pct"] is None
    assert data["cards"]["risk_reversal_25d_pct"] is None
    assert data["cards"]["butterfly_25d_pct"] is None
    assert data["vol_source"] != "reference_fx_vol_model"
    assert "reference_fx_vol_model" not in result.sources
    assert result.warnings, "unavailable state must carry a warning"


def test_no_history_never_emits_reference_constants(no_history):
    result = _run(fx.OVDVFunction().execute(pair="GBPUSD"))
    values = {round(float(row["vol"]), 6) for row in result.data["surface"]}
    for constant in REFERENCE_CONSTANTS_PCT:
        assert constant not in values


def test_no_history_with_explicit_atm_is_still_honoured(no_history):
    result = _run(fx.OVDVFunction().execute(pair="EURUSD", atm_vol=0.11))
    data = result.data

    assert data.get("status") in (None, "ok")
    assert data["vol_source"] == "user_inputs"
    atm = [row["vol"] for row in data["surface"] if row["delta"] == "ATM"]
    assert atm and all(abs(v - 11.0) < 1e-6 for v in atm), atm


def test_zero_realized_vol_is_not_replaced_by_a_reference_constant(flat_history):
    result = _run(fx.OVDVFunction().execute(pair="EURUSD"))
    data = result.data

    assert data["status"] == "provider_unavailable"
    assert data["surface"] == []
    assert "reference_fx_vol_model" not in result.sources


def test_reference_vol_helper_is_gone():
    # The hard-coded reference ATM table must not survive as a silent source.
    assert not hasattr(fx, "_reference_atm_vol")
