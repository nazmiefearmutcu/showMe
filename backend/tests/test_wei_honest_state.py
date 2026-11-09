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
    # WEI#3 follow-up: the template must not invent levels. Rows keep identity
    # only; every market field is null and labelled unavailable.
    rows = out.data["rows"]
    assert rows, "reference path must still show the universe"
    for row in rows:
        assert row["name"] and row["region"], row
        for field in ("last", "change", "change_pct", "high", "low", "prev_close"):
            assert row.get(field) is None, (row["symbol"], field, row.get(field))
        assert row["market_state"] == "unavailable", row
    # The request clock is not a data freshness stamp for a deterministic model.
    assert "as_of" not in out.data
    assert out.data.get("generated_at")
    assert out.data.get("reason")
    assert out.data.get("next_actions")


def test_provider_down_fallback_rows_carry_no_invented_levels() -> None:
    """WEI#3: the live provider-unavailable envelope must not paint model levels."""

    class _EmptyProvider:
        name = "yfinance"

        async def fetch(self, request: object) -> None:
            return None

    out = asyncio.run(WEIFunction(deps=FunctionDeps(yfinance=_EmptyProvider())).execute())
    assert out.data["status"] == "provider_unavailable"
    assert out.data["rows"], "fallback must still list the universe"
    for row in out.data["rows"]:
        for field in ("last", "change_pct", "high", "low"):
            assert row.get(field) is None, (row["symbol"], field, row.get(field))
    assert out.data.get("reason") and out.data.get("next_actions")


def test_region_param_filters_rows_server_side() -> None:
    """WEI#2: the region param is honoured by the API, not only by the pane."""
    out = asyncio.run(WEIFunction().execute(reference=True, region="europe"))
    rows = out.data["rows"]
    assert rows, "europe region returned no rows"
    assert {row["region"] for row in rows} == {"europe"}
    assert len(rows) < len(_world_index_symbols())


def test_unknown_region_is_an_input_error_not_the_full_board() -> None:
    out = asyncio.run(WEIFunction().execute(reference=True, region="mars"))
    assert out.data["status"] == "input_error"
    assert out.data["rows"] == []
    assert out.data.get("reason")


def test_source_labels_do_not_name_a_baseline_or_model_that_holds_no_data() -> None:
    """WEI#3 follow-up: the template holds identity only, so its source label
    must not claim a baseline table or a model that no longer exists."""
    ref = asyncio.run(WEIFunction().execute(reference=True))
    assert ref.sources == ["showme_world_index_identity"], ref.sources
    assert all("baseline" not in s and "model" not in s for s in ref.sources)

    class _EmptyProvider:
        name = "yfinance"

        async def fetch(self, request: object) -> None:
            return None

    down = asyncio.run(WEIFunction(deps=FunctionDeps(yfinance=_EmptyProvider())).execute())
    assert "world_index_identity" in down.sources, down.sources
    assert all("baseline" not in s and "model" not in s for s in down.sources), down.sources
