"""WEI — honest session / freshness labelling (finding WEI#1).

The yfinance quote path does not report a market (quote) time or an exchange
session state: the adapter stamps ``Quote.timestamp`` with the request clock.
WEI must therefore never label a row ``live`` by default, and must never stamp
``as_of`` with the request time. Offline: the provider is an injected fake.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.quote import Quote
from showme.engine.functions.screen._funcs import WEIFunction, _world_index_symbols


class _OneQuoteProvider:
    name = "yfinance"

    def __init__(self, symbol: str = "^GSPC"):
        self.symbol = symbol

    async def fetch(self, request: object) -> Quote | None:
        symbol = str(getattr(getattr(request, "instrument", None), "symbol", ""))
        if symbol != self.symbol:
            return None
        return Quote(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            last=7376.86,
            close_prev=7350.0,
        )


def test_live_rows_do_not_default_to_live_market_state() -> None:
    out = asyncio.run(
        WEIFunction(deps=FunctionDeps(yfinance=_OneQuoteProvider())).execute()
    )
    by_symbol = {row["symbol"]: row for row in out.data["rows"]}
    gspc = by_symbol["^GSPC"]
    # The provider reports no session state, so the row must not claim "live".
    assert gspc["market_state"] != "live", gspc
    assert gspc["market_state"] == "unknown", gspc
    # Unresolved rows keep their explicit state.
    assert by_symbol[next(s for s in _world_index_symbols() if s != "^GSPC")]["market_state"] == "unavailable"


def test_live_payload_does_not_stamp_request_time_as_as_of() -> None:
    out = asyncio.run(
        WEIFunction(deps=FunctionDeps(yfinance=_OneQuoteProvider())).execute()
    )
    # as_of must not be the request clock: the provider gave no quote time.
    assert "as_of" not in out.data, out.data.get("as_of")
    assert out.data.get("quote_time") is None
    assert out.data.get("fetched_at"), "retrieval time must be labelled fetched_at"
    assert out.data.get("source_mode") == "yfinance_live"


def test_reference_template_envelope_is_not_status_ok() -> None:
    """WEI#3: a model/reference template must not present as an ok snapshot."""
    out = asyncio.run(WEIFunction().execute(reference=True))
    assert out.data["source_mode"] == "world_index_template"
    assert out.data["status"] == "model", out.data["status"]
    assert out.data["status"] != "ok"
    assert out.metadata.get("live") is False
    assert all(row["market_state"] == "model" for row in out.data["rows"])
    # The request clock is not a data freshness stamp for a deterministic model.
    assert "as_of" not in out.data
    assert out.data.get("generated_at")
