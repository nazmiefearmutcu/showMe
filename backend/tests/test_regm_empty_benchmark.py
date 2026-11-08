"""REGM never classifies an empty benchmark as a live regime (REGM#1).

When yfinance returns no rows for a ticker (Yahoo 404 / quote not found), the
handler used to classify an empty close array and return status ok with
data_state live and a yfinance source. It must report provider_unavailable.
Network is patched: yfinance and the keyless FRED client are fakes.
"""
from __future__ import annotations

import asyncio

import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.macro.regm import REGMFunction
from showme.engine.functions._fred_csv import reset_fred_csv_cache


class _EmptyYahoo:
    async def fetch(self, request):
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


class _FakeResp:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        return None


class _FakeFredClient:
    async def get(self, url, timeout=None):  # noqa: ANN001
        last = "3.40" if "DGS10" in str(url) else "4.20"
        return _FakeResp(f"observation_date,value\n2026-09-01,4.00\n2026-09-02,{last}\n")


def _run_empty_benchmark(symbol: str):
    reset_fred_csv_cache()
    fn = REGMFunction(FunctionDeps(yfinance=_EmptyYahoo()))
    fn._http_client = _FakeFredClient()
    return asyncio.run(fn.execute(symbol=symbol, days=1095))


def test_empty_benchmark_is_provider_unavailable_not_ok():
    result = _run_empty_benchmark("ZZZQX9")
    assert result.data["status"] == "provider_unavailable", result.data
    assert result.data["rows"] == []
    assert result.data["current"] == {}
    assert result.warnings, "the unavailable benchmark must be explained in warnings"


def test_empty_benchmark_does_not_claim_a_yfinance_source():
    result = _run_empty_benchmark("ZZZQX9")
    assert "yfinance" not in result.sources, result.sources
    assert result.metadata["provider_error"]


def test_empty_benchmark_never_reports_live_regime_cards():
    result = _run_empty_benchmark("ZZZQX9")
    values = {card["label"]: card["value"] for card in result.data["cards"]}
    assert values == {"Regime": "—", "Trend": "—", "Vol": "—", "Curve": "—"}, values
