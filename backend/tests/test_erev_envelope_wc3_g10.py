"""WC3-G10 EREV#4: an unavailable EREV envelope must not be labelled synthetic.

The reported envelope said data_state=synthetic for provider_unavailable. Probed
against the current code through the sidecar sanitizer (no network: Finnhub is
not wired, and a failing fake is used for the wired case), the label is
provider_unavailable with metadata.synthetic false. This test pins that.
"""

from __future__ import annotations

import asyncio

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.erev import EREVFunction
from showme.server import enforce_live_or_label_synthetic


def _aapl() -> Instrument:
    return Instrument(
        symbol="AAPL",
        asset_class=AssetClass.EQUITY,
        exchange=None,
        currency="USD",
        isin=None,
        cusip=None,
        figi=None,
        name="AAPL",
        metadata={},
    )


class _FailingFinnhub:
    async def recommendations(self, sym: str) -> list[dict]:
        raise RuntimeError("finnhub 429")


def _envelope(deps: FunctionDeps) -> dict:
    result = asyncio.run(EREVFunction(deps).execute(instrument=_aapl()))
    return enforce_live_or_label_synthetic("EREV", {"symbol": "AAPL"}, result.to_dict())


def test_unconfigured_erev_envelope_is_provider_unavailable_not_synthetic() -> None:
    out = _envelope(FunctionDeps())
    assert out["data"]["status"] == "provider_unavailable"
    assert out["data_state"] == "provider_unavailable"
    assert not (out.get("metadata") or {}).get("synthetic")
    assert out["data"]["rows"] == [] and out["data"]["trend"] == []


def test_failing_erev_provider_envelope_is_provider_unavailable_not_synthetic() -> None:
    out = _envelope(FunctionDeps(finnhub=_FailingFinnhub()))
    assert out["data"]["status"] == "provider_unavailable"
    assert out["data_state"] == "provider_unavailable"
    assert not (out.get("metadata") or {}).get("synthetic")
