"""FTS live contract: filing URL, honest live switch, date bounds and total hits.

Regressions for:
- FTS#3: no filing link was ever produced (adapter dropped the EDGAR URL).
- FTS#5: the ``live`` input was ignored (only ``reference`` was read).
- FTS#6: date_from/date_to were not read and EFTS ``hits.total`` was dropped.

The EFTS HTTP call is served by an httpx.MockTransport, so no network is used.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.data_sources.equity.sec_efts_adapter import SECFullTextSearch
from showme.engine.functions.equity.fts import FTSFunction

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)

EFTS_BODY = {
    "hits": {
        "total": {"value": 1775, "relation": "eq"},
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
                },
            }
        ],
    }
}

EXPECTED_URL = (
    "https://www.sec.gov/Archives/edgar/data/1234567/"
    "000095017025000001/0000950170-25-000001-index.htm"
)


def _run(coro):
    return asyncio.run(coro)


def _adapter(capture: list[httpx.Request] | None = None, body: dict[str, Any] | None = None) -> SECFullTextSearch:
    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture.append(request)
        return httpx.Response(200, json=body if body is not None else EFTS_BODY)

    adapter = SECFullTextSearch()
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return adapter


class _RecordingSec:
    def __init__(self, rows: list[dict[str, Any]] | None = None, total: int | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._rows = rows or []
        self.total = total

    async def search(self, query, forms=None, start=None, end=None, limit=50):
        self.calls.append({"query": query, "forms": forms, "start": start, "end": end, "limit": limit})
        out = list(self._rows)
        if self.total is not None:
            out = _Hits(out, total=self.total)
        return out


class _Hits(list):
    def __init__(self, items, total):
        super().__init__(items)
        self.total = total


# ── FTS#3: filing URL ─────────────────────────────────────────────────────


def test_adapter_builds_edgar_filing_url_from_cik_and_accession() -> None:
    rows = _run(_adapter().search("supply chain"))
    assert len(rows) == 1
    assert rows[0]["url"] == EXPECTED_URL


def test_adapter_has_no_url_when_cik_is_missing() -> None:
    body = {"hits": {"hits": [{
        "_id": "0000950170-25-000001:doc.htm",
        "_source": {"adsh": "0000950170-25-000001", "form": "8-K", "file_date": "2025-03-04"},
    }]}}
    rows = _run(_adapter(body=body).search("supply chain"))
    assert rows[0]["url"] is None


def test_fts_handler_row_carries_filing_url() -> None:
    result = _run(FTSFunction(FunctionDeps(sec_efts=_adapter())).execute(instrument=AAPL, query="supply chain"))
    assert result.data["rows"][0]["url"] == EXPECTED_URL


# ── FTS#5: live input is honoured ─────────────────────────────────────────


def test_live_false_skips_provider_and_reports_empty_with_reason() -> None:
    sec = _RecordingSec(rows=[{"company": "X", "form": "8-K", "accession": "A", "url": None}])
    result = _run(FTSFunction(FunctionDeps(sec_efts=sec)).execute(instrument=AAPL, query="supply chain", live=False))
    assert sec.calls == []
    assert result.data["status"] == "empty"
    assert result.data["rows"] == []
    assert "skipped" in result.data["reason"]
    assert result.metadata["live"] is False


def test_live_true_still_searches() -> None:
    sec = _RecordingSec(rows=[])
    _run(FTSFunction(FunctionDeps(sec_efts=sec)).execute(instrument=AAPL, query="supply chain", live="true"))
    assert len(sec.calls) == 1


def test_reference_true_still_skips_provider() -> None:
    sec = _RecordingSec(rows=[])
    _run(FTSFunction(FunctionDeps(sec_efts=sec)).execute(instrument=AAPL, query="supply chain", reference=True))
    assert sec.calls == []


# ── FTS#6: date bounds and total_hits ─────────────────────────────────────


def test_date_from_and_date_to_reach_the_adapter() -> None:
    sec = _RecordingSec(rows=[])
    _run(FTSFunction(FunctionDeps(sec_efts=sec)).execute(
        instrument=AAPL, query="supply chain", date_from="2025-01-01", date_to="2025-03-31"))
    assert sec.calls[0]["start"] == "2025-01-01"
    assert sec.calls[0]["end"] == "2025-03-31"


def test_adapter_sends_custom_date_range_params() -> None:
    captured: list[httpx.Request] = []
    _run(_adapter(capture=captured).search("supply chain", start="2025-01-01", end="2025-03-31"))
    params = captured[0].url.params
    assert params["dateRange"] == "custom"
    assert params["startdt"] == "2025-01-01"
    assert params["enddt"] == "2025-03-31"


def test_adapter_returns_efts_total_on_result() -> None:
    hits = _run(_adapter().search("supply chain"))
    assert getattr(hits, "total", None) == 1775


def test_fts_handler_returns_total_hits() -> None:
    result = _run(FTSFunction(FunctionDeps(sec_efts=_adapter())).execute(instrument=AAPL, query="supply chain"))
    assert result.data["total_hits"] == 1775


def test_fts_handler_total_hits_is_none_when_provider_does_not_report_it() -> None:
    sec = _RecordingSec(rows=[])
    result = _run(FTSFunction(FunctionDeps(sec_efts=sec)).execute(instrument=AAPL, query="supply chain"))
    assert result.data["total_hits"] is None
