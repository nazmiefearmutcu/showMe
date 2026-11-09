"""HFS — holder rows come only from the local 13F store, never static tables.

With no populated 13F store, HFS used to serve the static AAPL reference
holders from ``_common.REFERENCE_PROFILES`` under ``status='ok'``,
``sources=['sec_13f']`` and ``metadata.live=True``. Those constants have no
reporting date and are not a 13F feed. The contract now is:

* rows only when the local SEC 13F store returns holdings for the issuer;
* otherwise an explicit ``provider_unavailable`` / ``empty`` state with
  ``next_actions`` and no rows;
* the envelope never claims a live source for the static table.
"""

from __future__ import annotations

import asyncio

import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.equity.hfs import HFSFunction


def _run(coro):
    return asyncio.run(coro)


class _EmptySec13F:
    async def query_holdings_by_security(self, **_kwargs):
        return pd.DataFrame()


class _PopulatedSec13F:
    async def query_holdings_by_security(self, **_kwargs):
        return pd.DataFrame(
            [
                {"filer": "Example Capital LP", "shares": 1_000_000, "market_value": 2.5e8,
                 "quarter": "2026-06-30", "source_mode": "sec_13f"},
            ]
        )


class _BoomSec13F:
    async def query_holdings_by_security(self, **_kwargs):
        raise RuntimeError("duckdb locked")


def _fn(sec=None):
    deps = FunctionDeps()
    if sec is not None:
        deps.sec_13f = sec
    return HFSFunction(deps)


def test_live_aapl_without_store_returns_no_static_holders():
    result = _run(_fn(_EmptySec13F()).execute(issuer="AAPL", live=True))
    data = result.data

    assert isinstance(data, dict)
    assert data["status"] != "ok"
    assert data["status"] == "provider_unavailable"
    assert data["rows"] == []
    assert result.metadata.get("live") is not True
    assert any("ingest_13f" in a for a in data["next_actions"])


def test_default_aapl_lookup_does_not_serve_static_reference_rows():
    result = _run(_fn(_EmptySec13F()).execute(issuer="AAPL"))
    data = result.data

    assert isinstance(data, dict), "HFS must return a status envelope, not a bare row list"
    assert data["rows"] == []
    assert data["status"] != "ok"
    assert all(
        "reference" not in str(row.get("source_mode", "")) for row in data["rows"]
    )


def test_unwired_store_is_honest_unavailable_without_rows():
    result = _run(_fn().execute(issuer="AAPL", live=True))
    assert result.data["status"] == "provider_unavailable"
    assert result.data["rows"] == []


def test_store_error_is_provider_unavailable_without_fake_no_match_row():
    result = _run(_fn(_BoomSec13F()).execute(issuer="AAPL", live=True))
    assert result.data["status"] == "provider_unavailable"
    assert result.data["rows"] == []
    assert result.metadata["provider_errors"]


def test_populated_store_returns_real_rows_marked_ok():
    result = _run(_fn(_PopulatedSec13F()).execute(issuer="ZZZZ", live=True))
    data = result.data
    assert data["status"] == "ok"
    assert [r["filer"] for r in data["rows"]] == ["Example Capital LP"]
    assert result.sources == ["sec_13f"]
    assert result.metadata["live"] is False


def test_populated_store_does_not_fall_back_to_static_rows_for_missing_issuer():
    """A populated store with no rows for the issuer must say so, not borrow AAPL rows."""
    result = _run(_fn(_EmptySec13F()).execute(issuer="AAPL", live=True, cusip=None))
    assert result.data["rows"] == []
    assert result.data["status"] == "provider_unavailable"
