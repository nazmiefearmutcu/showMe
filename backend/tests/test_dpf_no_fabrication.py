"""DPF must not invent weekly ATS rows when FINRA gives nothing (P2a-g05, DPF#4).

The old fallback generated shape-model rows from a fixed 42M base and a
hard-coded 38.0 dark-pool percent. Those values are fabricated, so every
no-data path now returns an empty row set with an explicit provider_unavailable
status and a reason. No network: FINRA is a stand-in and yfinance is never reached
on these paths.
"""
from __future__ import annotations

import asyncio

import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity import dpf as dpf_mod
from showme.engine.functions.equity.dpf import DPFFunction


def _run(coro):
    return asyncio.run(coro)


def _instrument() -> Instrument:
    return Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


class _BoomFinra:
    async def ats_weekly(self, symbol=None, limit=200):
        raise RuntimeError("finra down")


class _EmptyFinra:
    async def ats_weekly(self, symbol=None, limit=200):
        return pd.DataFrame()


def _assert_no_fabricated_rows(data: dict) -> None:
    assert data["rows"] == []
    assert data["weekly"] == []
    assert data["history"] == []


def test_dpf_finra_error_returns_no_invented_rows() -> None:
    result = _run(DPFFunction(deps=FunctionDeps(finra=_BoomFinra())).execute(instrument=_instrument()))
    assert result.data["status"] == "provider_unavailable"
    assert result.data["reason"]
    _assert_no_fabricated_rows(result.data)
    assert not [s for s in result.sources if s != "no_live_source"]  # no provider claimed
    assert result.metadata.get("provider_errors")


def test_dpf_empty_finra_returns_no_invented_rows() -> None:
    result = _run(DPFFunction(deps=FunctionDeps(finra=_EmptyFinra())).execute(instrument=_instrument()))
    assert result.data["status"] == "provider_unavailable"
    assert "AAPL" in result.data["reason"]
    _assert_no_fabricated_rows(result.data)
    assert result.data["next_actions"]


def test_dpf_timeout_returns_no_invented_rows(monkeypatch) -> None:
    async def _boom(self, instrument, **params):  # noqa: ANN001
        raise asyncio.TimeoutError("dpf slow")

    monkeypatch.setattr(dpf_mod.DPFFunction, "_execute_inner", _boom)
    result = _run(DPFFunction(deps=FunctionDeps()).execute(instrument=_instrument()))
    assert result.data["status"] == "provider_unavailable"
    assert "timed out" in result.data["reason"]
    _assert_no_fabricated_rows(result.data)


def test_dpf_handler_no_longer_imports_shape_model() -> None:
    source = open(dpf_mod.__file__, encoding="utf-8").read()
    assert "recent_week_rows" not in source
    assert "42_000_000" not in source
