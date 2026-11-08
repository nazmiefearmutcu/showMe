"""Follow-up to TRAN#3 and TRAN#1-RQ: provenance and quarter labels must be honest.

The quarter selector matches the 8-K report date by calendar quarter, which is
not the company's fiscal quarter for most fiscal years. The seed still named
yfinance as the source and called the input a fiscal quarter. These tests pin
the corrected wording and the quarter_basis label on the returned event.
SEC, the ticker map and the transcript archive are faked, so no network is used.
"""

from __future__ import annotations

import asyncio

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.news import tran as tran_mod
from showme.engine.functions.news.tran import TRANFunction
from showme.manifest.seeds.tran_seed import tran as tran_manifest

_CIK = "0000320193"

_SUBMISSIONS = {
    "filings": {
        "recent": {
            "form": ["8-K", "8-K"],
            "accessionNumber": ["0000320193-26-000024", "0000320193-26-000010"],
            "primaryDocument": ["a.htm", "b.htm"],
            "reportDate": ["2026-10-30", "2026-07-30"],
            "filingDate": ["2026-10-30", "2026-07-30"],
            "items": ["2.02,9.01", "2.02,9.01"],
        }
    }
}

_RELEASE_TEXT = {
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


def _seed_texts() -> list[str]:
    texts = [tran_manifest.intent, tran_manifest.methodology]
    texts += [i.description or "" for i in tran_manifest.inputs]
    texts += [f.description for f in tran_manifest.field_dict.values()]
    texts += [f.source or "" for f in tran_manifest.field_dict.values()]
    return texts


def test_seed_does_not_name_yfinance_as_the_source() -> None:
    assert not any("yfinance" in t.lower() for t in _seed_texts())
    assert tran_manifest.provider_chain.primary == "sec_edgar"


def test_seed_quarter_input_is_described_as_the_8k_calendar_quarter() -> None:
    quarter = next(i for i in tran_manifest.inputs if i.name == "quarter")
    desc = (quarter.description or "").lower()
    assert not desc.startswith("fiscal quarter")
    assert "not necessarily the company's fiscal quarter" in desc
    assert "8-k" in desc
    assert "calendar" in desc


def test_matched_event_labels_the_quarter_basis(monkeypatch) -> None:
    _patch_sec(monkeypatch)
    instrument = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    data = asyncio.run(TRANFunction().execute(instrument, quarter="Q3 FY26")).data
    assert data["status"] == "ok"
    basis = data["event"]["quarter_basis"].lower()
    assert "report date" in basis
    assert "calendar" in basis
    assert "not necessarily the company's fiscal quarter" in basis
