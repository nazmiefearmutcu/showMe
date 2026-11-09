"""FSRC — AUM and YTD are not served from stale constants (finding FSRC#1).

ShowMe has no keyless provider for fund AUM or YTD, so the curated AUM and YTD
constants were removed from the served universe. The screen must not present
any AUM/YTD number, must not invent an as-of date for them, and must refuse
(honest provider_unavailable state) a predicate that filters on them instead of
silently matching against nothing or against stale values.

Offline: the quote provider is an injected fake or absent.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.quote import Quote
from showme.engine.functions.screen._funcs import FSRCFunction


class _QuoteProvider:
    name = "yfinance"

    def __init__(self) -> None:
        self.calls = 0

    async def fetch(self, request: object) -> Quote | None:
        self.calls += 1
        symbol = str(getattr(getattr(request, "instrument", None), "symbol", ""))
        return Quote(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            last=100.0,
            close_prev=99.0,
        )


def _run(query: str | None = None, **params):
    kwargs = dict(params)
    if query is not None:
        kwargs["query"] = query
    return asyncio.run(FSRCFunction(deps=FunctionDeps()).execute(**kwargs))


def test_no_served_row_carries_a_numeric_aum_or_ytd() -> None:
    out = _run("expenseRatio <= 0.01", limit=250)
    assert out.data["rows"], "expected rows for the fee predicate"
    for row in out.data["rows"]:
        assert row.get("aum_usd") is None, row["symbol"]
        assert row.get("ytd_return_pct") is None, row["symbol"]


def test_aum_and_ytd_state_is_unavailable_on_every_row() -> None:
    out = _run("expenseRatio <= 0.01", limit=250)
    for row in out.data["rows"]:
        assert row.get("aum_state") == "unavailable", row["symbol"]
        assert row.get("ytd_state") == "unavailable", row["symbol"]


def test_no_as_of_stamp_is_invented_for_aum_or_ytd() -> None:
    out = _run("expenseRatio <= 0.01", limit=250)
    for row in out.data["rows"]:
        assert "aum_as_of" not in row, row["symbol"]
        assert "ytd_as_of" not in row, row["symbol"]
    # The verification date that was wrongly attached to AUM/YTD is gone from
    # the whole payload, not just the rows.
    assert "2026-09-15" not in json.dumps(out.data, default=str)
    assert "2026-09-15" not in json.dumps(out.warnings, default=str)


def test_warning_says_aum_and_ytd_are_not_served() -> None:
    out = _run("expenseRatio <= 0.01")
    text = " ".join(out.warnings).lower()
    assert "aum" in text and "ytd" in text
    assert "not served" in text


def test_field_dictionary_describes_aum_and_ytd_as_not_served() -> None:
    out = _run("expenseRatio <= 0.01")
    fields = {entry["field"]: entry["meaning"] for entry in out.data["field_dictionary"]}
    assert "not served" in fields["aum_usd"].lower()
    assert "not served" in fields["ytd_return_pct"].lower()
    assert "aum_as_of" not in fields and "ytd_as_of" not in fields


def test_default_query_is_servable_and_returns_rows() -> None:
    out = asyncio.run(FSRCFunction(deps=FunctionDeps()).execute())
    assert out.data["status"] == "ok", out.data.get("reason")
    assert out.data["rows"]
    assert all(row["expenseRatio"] < 0.01 for row in out.data["rows"])


def test_predicate_on_aum_is_refused_not_matched_against_nothing() -> None:
    out = _run("aum_usd > 10000000000")
    assert out.data["status"] == "provider_unavailable"
    assert out.data["rows"] == []
    assert "aum_usd" in out.data["reason"]
    assert out.data["next_actions"]
    assert out.data["unsupported_columns"] == ["aum_usd"]


def test_alias_predicate_on_aum_is_refused_too() -> None:
    out = _run("aum > 1000 AND expenseRatio < 0.01")
    assert out.data["status"] == "provider_unavailable"
    assert out.data["rows"] == []


def test_predicate_on_ytd_is_refused() -> None:
    out = _run("ytd_return_pct > 0")
    assert out.data["status"] == "provider_unavailable"
    assert out.data["rows"] == []


def test_live_overlay_keeps_aum_and_ytd_unserved() -> None:
    provider = _QuoteProvider()
    out = asyncio.run(
        FSRCFunction(deps=FunctionDeps(yfinance=provider)).execute(
            query="expenseRatio <= 0.001", limit=50
        )
    )
    assert provider.calls > 0
    assert out.data["rows"]
    live = [row for row in out.data["rows"] if row.get("quote_state") == "live"]
    assert live, "fake quote provider should overlay some rows"
    for row in out.data["rows"]:
        assert row.get("aum_usd") is None, row["symbol"]
        assert row.get("ytd_return_pct") is None, row["symbol"]
        assert row.get("aum_state") == "unavailable", row["symbol"]


def test_manifest_default_query_does_not_filter_on_unserved_columns() -> None:
    from showme.manifest import REGISTRY, load_seeds

    load_seeds()
    entry = REGISTRY.get("FSRC")
    assert "aum_usd" not in str(entry.defaults.get("query", ""))
    assert all("aum" not in col.key for col in entry.table_schema.columns)
