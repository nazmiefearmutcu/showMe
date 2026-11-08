"""DES#2 follow-up: a zero placeholder is not a company profile.

A provider answer whose only populated fields are zero placeholders
(market_cap=0.0, shares_outstanding=0.0) used to count as profile content, so
DES listed that provider as the source and showed a zero market cap for an
unknown symbol. Zero is "no value" for these numeric profile fields.
No network: providers are in-test fakes.
"""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.core.refdata import ReferenceData
from showme.engine.functions.equity.des import DESFunction, _has_profile_content


def _instrument() -> Instrument:
    return Instrument(symbol="XYZQ", asset_class=AssetClass.EQUITY, exchange="NMS",
                      currency="USD", name="XYZQ")


class _Provider:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    async def fetch(self, request: Any) -> Any:  # noqa: ARG002
        return self._payload


def test_zero_only_reference_data_is_not_profile_content() -> None:
    rd = ReferenceData(symbol="XYZQ", market_cap=0.0, shares_outstanding=0.0, source="finnhub")
    assert _has_profile_content(rd) is False


def test_zero_only_raw_info_is_not_profile_content() -> None:
    rd = ReferenceData(symbol="XYZQ", source="yfinance",
                       extras={"raw": {"marketCap": 0, "fullTimeEmployees": 0}})
    assert _has_profile_content(rd) is False


def test_zero_placeholder_provider_is_not_listed_as_a_source() -> None:
    placeholder = ReferenceData(symbol="XYZQ", market_cap=0.0, shares_outstanding=0.0,
                                source="finnhub")
    fn = DESFunction()
    fn.deps = FunctionDeps(yfinance=_Provider(None), finnhub=_Provider(placeholder))

    result = asyncio.run(fn.execute(_instrument()))
    assert result.data["status"] == "provider_unavailable"
    assert result.sources == []
    assert result.data["market_cap"] is None
