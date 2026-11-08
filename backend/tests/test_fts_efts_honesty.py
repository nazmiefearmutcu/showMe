"""FTS honesty: snippets are matched filing text only; rows carry their own issuer.

Regression for FTS#1 (inc_states mapped to snippet) and FTS#2 (every row
stamped with the instrument symbol). The EFTS HTTP call is served by an
httpx.MockTransport, so no network is used.
"""

from __future__ import annotations

import asyncio
import json

import httpx

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.data_sources.equity.sec_efts_adapter import SECFullTextSearch
from showme.engine.functions.equity.fts import FTSFunction

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)

EFTS_HITS = {
    "hits": {
        "hits": [
            {
                "_id": "0000950170-25-000001:doc.htm",
                "_score": 9.5,
                "_source": {
                    "adsh": "0000950170-25-000001",
                    "form": "8-K",
                    "file_date": "2025-03-04",
                    "ciks": ["0001234567"],
                    "display_names": ["US ENERGY CORP  (USEG)  (CIK 0001234567)"],
                    "inc_states": ["WY"],
                },
            }
        ]
    }
}


def _adapter_with_hits() -> SECFullTextSearch:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=EFTS_HITS)

    adapter = SECFullTextSearch()
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return adapter


class _SecReturning:
    def __init__(self, rows):
        self._rows = rows

    async def search(self, query, forms=None, start=None, end=None, limit=50):
        return self._rows


def _run(coro):
    return asyncio.run(coro)


def test_adapter_never_maps_incorporation_state_to_snippet() -> None:
    rows = _run(_adapter_with_hits().search("supply chain"))
    assert len(rows) == 1
    # inc_states is an incorporation state, not matched filing text.
    assert rows[0]["snippet"] in (None, "")


def test_adapter_uses_highlight_text_when_provider_returns_it() -> None:
    hit = dict(EFTS_HITS["hits"]["hits"][0])
    hit["highlight"] = {"body": ["…exposure to <em>supply chain</em> disruption…"]}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"hits": {"hits": [hit]}})

    adapter = SECFullTextSearch()
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    rows = _run(adapter.search("supply chain"))
    assert "supply chain" in rows[0]["snippet"]


def test_adapter_parses_ticker_from_display_name() -> None:
    rows = _run(_adapter_with_hits().search("supply chain"))
    assert rows[0]["ticker"] == "USEG"


def test_fts_handler_does_not_label_other_issuer_as_instrument() -> None:
    sec = _SecReturning([
        {"company": "US ENERGY CORP  (USEG)  (CIK 0001234567)", "form": "8-K",
         "filing_date": "2025-03-04", "accession": "0000950170-25-000001",
         "ticker": "USEG", "cik": "0001234567", "snippet": None, "score": 9.5},
    ])
    result = _run(FTSFunction(FunctionDeps(sec_efts=sec)).execute(instrument=AAPL, query="supply chain"))
    row = result.data["rows"][0]
    assert row["symbol"] == "USEG"
    assert row["symbol"] != "AAPL"
    assert row["issuer_match"] is False


def test_fts_handler_row_snippet_is_not_state_code() -> None:
    adapter = _adapter_with_hits()
    result = _run(FTSFunction(FunctionDeps(sec_efts=adapter)).execute(instrument=AAPL, query="supply chain"))
    row = result.data["rows"][0]
    assert row["snippet"] in (None, "")
    assert row["symbol"] == "USEG"
    assert row["issuer_match"] is False
