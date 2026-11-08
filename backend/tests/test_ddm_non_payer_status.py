"""DDM#3: a non-dividend payer is not a live valuation.

A provider reporting no trailing dividend must come back as not_applicable with a null
fair value, never status ok with fair value 0 (the pane would then show a live pill).
No network: the yfinance adapter is faked.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.dcf import DDMFunction

AMZN = Instrument(symbol="AMZN", asset_class=AssetClass.EQUITY)


class _Yf:
    def __init__(self, raw: dict) -> None:
        self._raw = raw

    async def fetch(self, request):
        return SimpleNamespace(extras={"raw": self._raw}, shares_outstanding=None)


def _run(raw: dict, **params):
    return asyncio.run(DDMFunction(FunctionDeps(yfinance=_Yf(raw))).execute(AMZN, **params))


def test_non_dividend_payer_is_not_applicable_not_ok() -> None:
    res = _run({"trailingAnnualDividendRate": 0, "dividendRate": None})
    assert res.data["status"] == "not_applicable", res.data
    assert res.data["fair_value_per_share"] is None
    assert res.data["surface"] == []
    assert res.data["rows"] == []
    assert res.data["status"] != "ok"


def test_forward_only_dividend_needs_input_not_zero_value() -> None:
    res = _run({"trailingAnnualDividendRate": 0, "dividendRate": 2.0})
    assert res.data["status"] == "needs_input", res.data
    assert res.data["fair_value_per_share"] is None


def test_failed_reference_data_is_provider_unavailable() -> None:
    res = _run({"info_error": "rate limited"})
    assert res.data["status"] == "provider_unavailable", res.data
    assert res.data["fair_value_per_share"] is None


def test_non_payer_payload_has_no_zero_fair_value_anywhere() -> None:
    res = _run({"trailingAnnualDividendRate": 0})
    assert res.data["fair_value_per_share"] is None
    assert not any(w.startswith("fair value") for w in res.warnings)
    assert all(v != 0.0 for k, v in res.data.items() if k == "fair_value_per_share")


@pytest.mark.parametrize("d0", [0, 0.0, None])
def test_explicit_zero_dividend_input_is_still_not_a_valuation(d0) -> None:
    res = asyncio.run(DDMFunction(FunctionDeps()).execute(AMZN, dividend_ttm=d0))
    assert res.data["status"] != "ok"
    assert res.data["fair_value_per_share"] is None
