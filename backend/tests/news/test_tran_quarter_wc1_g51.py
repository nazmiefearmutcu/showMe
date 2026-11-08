"""Regression tests for TRAN#3: the requested quarter was silently ignored.

The SEC EDGAR lookup always returned the newest 8-K, and the inferred quarter
then overwrote the requested one. SEC, the ticker map and the transcript
archive are faked, so no network is used.
"""

from __future__ import annotations

import asyncio

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.news import tran as tran_mod
from showme.engine.functions.news.tran import TRANFunction

_CIK = "0000320193"

_SUBMISSIONS = {
    "filings": {
        "recent": {
            "form": ["8-K", "8-K", "10-Q"],
            "accessionNumber": [
                "0000320193-26-000024",
                "0000320193-26-000010",
                "0000320193-26-000001",
            ],
            "primaryDocument": ["a.htm", "b.htm", "c.htm"],
            # Period end of each 8-K; the quarter label is derived from it.
            "reportDate": ["2026-10-30", "2026-07-30", "2026-04-30"],
            "filingDate": ["2026-10-30", "2026-07-30", "2026-04-30"],
            "items": ["2.02,9.01", "2.02,9.01", ""],
        }
    }
}

_RELEASE_TEXT = {
    "0000320193-26-000024": "Apple reports fourth quarter results. Q4 release text.",
    "0000320193-26-000010": "Apple reports third quarter results. Q3 release text.",
}


class _Resp:
    def __init__(self, payload=None, text: str = "", status_code: int = 200):
        self._payload = payload
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _FakeSecClient:
    async def get(self, url, headers=None, **kwargs):  # noqa: ARG002
        if url.endswith(f"/submissions/CIK{_CIK}.json"):
            return _Resp(_SUBMISSIONS)
        for accession, text in _RELEASE_TEXT.items():
            nodash = accession.replace("-", "")
            if url.endswith(f"/{nodash}/{accession}-index.json"):
                return _Resp({"directory": {"item": [{"name": "ex99-1.htm"}]}})
            if url.endswith(f"/{nodash}/ex99-1.htm"):
                return _Resp(text=f"<html><body><p>{text}</p></body></html>")
        return _Resp(status_code=404)


def _patch_sec(monkeypatch) -> None:
    client = _FakeSecClient()

    async def _fake_client():
        return client

    async def _fake_cik(symbol, deps=None):  # noqa: ARG001
        return _CIK

    from showme.engine.services import transcripts_archive as archive

    monkeypatch.setattr(tran_mod, "_http_client", _fake_client)
    monkeypatch.setattr(tran_mod, "_resolve_cik", _fake_cik)
    monkeypatch.setattr(archive, "list_for_symbol", lambda *a, **k: [])


def _run(**params):
    instrument = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    return asyncio.run(TRANFunction().execute(instrument, **params))


def test_tran3_requested_quarter_selects_matching_8k(monkeypatch) -> None:
    _patch_sec(monkeypatch)
    data = _run(quarter="Q3 FY26").data
    assert data["status"] == "ok"
    # The Q3 release is returned, not the newest (Q4) one.
    assert data["event"]["accession"] == "0000320193-26-000010"
    assert data["event"]["quarter"] == "Q3 FY26"
    texts = " ".join(r["utterance"] for r in data["utterances"])
    assert "Q3 release text" in texts
    assert "Q4 release text" not in texts


def test_tran3_quarter_without_matching_8k_is_an_honest_empty_state(monkeypatch) -> None:
    _patch_sec(monkeypatch)
    data = _run(quarter="Q2 FY26").data
    assert data["status"] != "ok"
    assert data["utterances"] == []
    assert "Q2 FY26" in data["reason"]
    # A missing filing is not a network outage.
    assert data["data_mode"] != "provider_unavailable"


def test_tran3_unparseable_quarter_is_an_input_error(monkeypatch) -> None:
    _patch_sec(monkeypatch)
    data = _run(quarter="the big one").data
    assert data["status"] == "input_error"
    assert data["utterances"] == []
    assert data["next_actions"]


def test_tran3_quarter_spellings_normalise() -> None:
    assert tran_mod._normalize_quarter("Q3 FY26") == "Q3 FY26"
    assert tran_mod._normalize_quarter("q3 fy2026") == "Q3 FY26"
    assert tran_mod._normalize_quarter("Q3 2026") == "Q3 FY26"
    assert tran_mod._normalize_quarter("Q3'26") == "Q3 FY26"
    assert tran_mod._normalize_quarter("the big one") is None
    assert tran_mod._normalize_quarter("") is None
