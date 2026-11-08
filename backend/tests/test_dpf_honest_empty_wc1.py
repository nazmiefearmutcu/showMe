"""DPF honest-empty regressions (wc1-g48: DPF#2, DPF#3).

DPF#2: with no FINRA rows the card KPIs (latest_ats_volume, latest_dark_pool_pct)
        must be null, not shape-model numbers the pane would display.
DPF#3: an empty FINRA frame must carry a specific, non-null reason and sources
        must not claim a provider that returned nothing.

No network: FINRA is a stand-in; yfinance is never reached on these paths.
"""
from __future__ import annotations

import asyncio

import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.dpf import DPFFunction


def _run(coro):
    return asyncio.run(coro)


class _EmptyFinra:
    async def ats_weekly(self, symbol=None, limit=200):
        return pd.DataFrame()


@pytest.mark.parametrize("symbol", ["ZZQX", "AAPL"])
def test_dpf_empty_finra_card_kpis_are_null(symbol) -> None:
    inst = Instrument(symbol=symbol, asset_class=AssetClass.EQUITY)
    res = _run(DPFFunction(deps=FunctionDeps(finra=_EmptyFinra())).execute(instrument=inst))
    assert res.data["status"] == "provider_unavailable"
    assert res.data["latest_ats_volume"] is None
    assert res.data["latest_dark_pool_pct"] is None
    assert res.data["as_of"] is None


def test_dpf_empty_finra_reason_names_symbol_and_cause() -> None:
    inst = Instrument(symbol="ZZQX", asset_class=AssetClass.EQUITY)
    res = _run(DPFFunction(deps=FunctionDeps(finra=_EmptyFinra())).execute(instrument=inst))
    reason = res.data["reason"]
    assert isinstance(reason, str) and reason.strip()
    assert "ZZQX" in reason
    assert "no weeks returned by FINRA" in reason
    assert res.warnings == [reason]


def test_dpf_empty_finra_claims_no_source() -> None:
    inst = Instrument(symbol="ZZQX", asset_class=AssetClass.EQUITY)
    res = _run(DPFFunction(deps=FunctionDeps(finra=_EmptyFinra())).execute(instrument=inst))
    assert res.sources == []
