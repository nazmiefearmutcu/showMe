"""GEX#3 regression: the underlying the user sends through the real router.

The router (`_route_function_params`) sets ``__explicit_symbol=False`` when the
caller sent ``underlying`` but no ``symbol``. The handler must still honour the
user's ``underlying``, must not price a router-injected default ticker, and the
manifest must not serve a silent SPY default.

No network: the yfinance adapter is an in-test stub that records the instrument
each request was made for.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pandas as pd

from showme.engine.core.base_data_source import DataKind
from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.derivative.gex import GEXFunction
from showme.server_routes._agent_runtime import _route_function_params

FUTURE_EXPIRY = "2099-12-31"


def _run(coro):
    return asyncio.run(coro)


class _RecordingChainStub:
    def __init__(self) -> None:
        self.symbols: list[str] = []
        self._calls = pd.DataFrame([{
            "strike": 100.0, "openInterest": 10, "impliedVolatility": 0.3,
            "lastTradeDate": pd.Timestamp(datetime.now(timezone.utc)),
        }])

    async def fetch(self, request):  # noqa: ANN001
        if request.kind != DataKind.OPTIONS_CHAIN:
            return None
        self.symbols.append(request.instrument.symbol)
        if request.extra.get("expiry") is None:
            return {"expiries": [FUTURE_EXPIRY]}
        return {"calls": self._calls, "puts": pd.DataFrame()}


def _routed(params: dict) -> dict:
    return _route_function_params("GEX", params)


def test_router_keeps_user_underlying_and_marks_symbol_not_explicit() -> None:
    routed = _routed({"underlying": "NVDA", "asset_class": "EQUITY", "live_options": True})
    assert routed.get("__explicit_symbol") is False
    assert routed.get("underlying") == "NVDA"


def test_underlying_sent_through_router_selects_the_symbol() -> None:
    stub = _RecordingChainStub()
    fn = GEXFunction(deps=FunctionDeps(yfinance=stub))
    routed = _routed({"underlying": "NVDA", "asset_class": "EQUITY",
                      "live_options": True, "spot": 100.0})
    result = _run(fn.execute(**routed))
    assert result.data["status"] == "ok", result.data.get("reason")
    assert result.data["symbol"] == "NVDA"
    assert result.data["underlying"] == "NVDA"


def test_router_default_instrument_is_not_priced_when_user_sent_underlying() -> None:
    # The dispatcher may hand the handler an instrument built from the router
    # default ticker; the data fetched must be for the user's underlying.
    stub = _RecordingChainStub()
    fn = GEXFunction(deps=FunctionDeps(yfinance=stub))
    routed = _routed({"underlying": "NVDA", "asset_class": "EQUITY",
                      "live_options": True, "spot": 100.0})
    default_inst = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    result = _run(fn.execute(instrument=default_inst, **routed))
    assert result.data["status"] == "ok", result.data.get("reason")
    assert stub.symbols and set(stub.symbols) == {"NVDA"}


def test_router_without_any_underlying_is_still_needs_input() -> None:
    stub = _RecordingChainStub()
    fn = GEXFunction(deps=FunctionDeps(yfinance=stub))
    routed = _routed({"live_options": True, "spot": 100.0})
    result = _run(fn.execute(**routed))
    assert result.data["status"] == "needs_input"
    assert result.data["rows"] == []
    assert stub.symbols == []


def test_manifest_declares_no_silent_spy_default_for_underlying() -> None:
    from showme.manifest import REGISTRY, load_seeds

    load_seeds()
    entry = REGISTRY.get("GEX")
    assert "underlying" not in (entry.defaults or {})
