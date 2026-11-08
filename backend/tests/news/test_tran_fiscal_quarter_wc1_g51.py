"""TRAN#3 follow-up: a requested fiscal quarter must select the fiscal period.

The earlier fix matched the requested quarter against the 8-K report date by
calendar quarter. For a December fiscal-year company, "Q1 FY26" then returned
the February 2026 release, which reports Q4 FY25. The lookup now derives the
fiscal quarter from the report date and the SEC submissions ``fiscalYearEnd``.
SEC is faked; no network is used.
"""

from __future__ import annotations

import asyncio

import pytest

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.news import tran as tran_mod
from showme.engine.functions.news.tran import TRANFunction

_CIK = "0000123456"
_ACC_APR = "0000123456-26-000008"  # report 2026-04-28 -> fiscal Q1 FY26 (Dec year end)
_ACC_FEB = "0000123456-26-000002"  # report 2026-02-10 -> fiscal Q4 FY25 (Dec year end)

_SUBMISSIONS_DEC = {
    "fiscalYearEnd": "1231",
    "filings": {
        "recent": {
            "form": ["8-K", "8-K"],
            "accessionNumber": [_ACC_APR, _ACC_FEB],
            "primaryDocument": ["a.htm", "b.htm"],
            "reportDate": ["2026-04-28", "2026-02-10"],
            "filingDate": ["2026-04-28", "2026-02-10"],
            "items": ["2.02,9.01", "2.02,9.01"],
        }
    }
}

_SUBMISSIONS_NO_FYE = {
    "filings": {
        "recent": {
            "form": ["8-K"],
            "accessionNumber": [_ACC_APR],
            "primaryDocument": ["a.htm"],
            "reportDate": ["2026-04-28"],
            "filingDate": ["2026-04-28"],
            "items": ["2.02,9.01"],
        }
    }
}

_RELEASE_TEXT = {
    _ACC_APR: "Acme reports first quarter results. Q1 FY26 release text.",
    _ACC_FEB: "Acme reports fourth quarter results. Q4 FY25 release text.",
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
    def __init__(self, submissions) -> None:
        self._submissions = submissions

    async def get(self, url, headers=None, **kwargs):  # noqa: ARG002
        if url.endswith(f"/submissions/CIK{_CIK}.json"):
            return _Resp(self._submissions)
        for accession, text in _RELEASE_TEXT.items():
            nodash = accession.replace("-", "")
            if url.endswith(f"/{nodash}/{accession}-index.json"):
                return _Resp({"directory": {"item": [{"name": "ex99-1.htm"}]}})
            if url.endswith(f"/{nodash}/ex99-1.htm"):
                return _Resp(text=f"<html><body><p>{text}</p></body></html>")
        return _Resp(status_code=404)


def _patch(monkeypatch, submissions, archived=None) -> None:
    client = _FakeSecClient(submissions)

    async def _fake_client():
        return client

    async def _fake_cik(symbol, deps=None):  # noqa: ARG001
        return _CIK

    from showme.engine.services import transcripts_archive as archive

    monkeypatch.setattr(tran_mod, "_http_client", _fake_client)
    monkeypatch.setattr(tran_mod, "_resolve_cik", _fake_cik)
    monkeypatch.setattr(archive, "list_for_symbol", lambda *a, **k: list(archived or []))


def _run(**params):
    instrument = Instrument(symbol="ACME", asset_class=AssetClass.EQUITY)
    return asyncio.run(TRANFunction().execute(instrument, **params))


# --- the fiscal quarter mapping itself -------------------------------------

@pytest.mark.parametrize(
    ("report_date", "fye", "expected"),
    [
        # Apple-style September year end
        ("2026-01-29", "0926", "Q1 FY26"),
        ("2026-04-30", "0926", "Q2 FY26"),
        ("2026-07-30", "0926", "Q3 FY26"),
        ("2026-10-30", "0926", "Q4 FY26"),
        # December year end: the February release reports Q4 of the prior year
        ("2026-02-10", "1231", "Q4 FY25"),
        ("2026-04-28", "1231", "Q1 FY26"),
        ("2026-07-28", "1231", "Q2 FY26"),
        ("2026-10-27", "1231", "Q3 FY26"),
        # March year end
        ("2026-05-05", "0331", "Q4 FY26"),
        ("2026-08-05", "0331", "Q1 FY27"),
    ],
)
def test_fiscal_quarter_follows_the_fiscal_calendar(report_date, fye, expected) -> None:
    assert tran_mod._fiscal_quarter(report_date, fye) == expected


def test_fiscal_quarter_is_none_without_a_usable_fiscal_year_end() -> None:
    assert tran_mod._fiscal_quarter("2026-04-28", None) is None
    assert tran_mod._fiscal_quarter("2026-04-28", "") is None
    assert tran_mod._fiscal_quarter("2026-04-28", "13xx") is None
    assert tran_mod._fiscal_quarter(None, "1231") is None


# --- end to end on a December year-end company -----------------------------

def test_december_year_end_q1_fy26_returns_the_april_release(monkeypatch) -> None:
    _patch(monkeypatch, _SUBMISSIONS_DEC)
    data = _run(quarter="Q1 FY26").data
    assert data["status"] == "ok"
    assert data["event"]["accession"] == _ACC_APR
    assert data["event"]["quarter"] == "Q1 FY26"
    texts = " ".join(r["utterance"] for r in data["utterances"])
    assert "Q1 FY26 release text" in texts
    assert "Q4 FY25 release text" not in texts


def test_december_year_end_q4_fy25_returns_the_february_release(monkeypatch) -> None:
    _patch(monkeypatch, _SUBMISSIONS_DEC)
    data = _run(quarter="Q4 FY25").data
    assert data["status"] == "ok"
    assert data["event"]["accession"] == _ACC_FEB
    assert data["event"]["quarter"] == "Q4 FY25"


def test_returned_quarter_label_always_matches_the_request(monkeypatch) -> None:
    _patch(monkeypatch, _SUBMISSIONS_DEC)
    for requested in ("Q1 FY26", "Q4 FY25"):
        data = _run(quarter=requested).data
        assert data["status"] == "ok"
        assert data["event"]["quarter"] == requested


def test_quarter_basis_names_the_fiscal_derivation(monkeypatch) -> None:
    _patch(monkeypatch, _SUBMISSIONS_DEC)
    basis = _run(quarter="Q1 FY26").data["event"]["quarter_basis"].lower()
    assert "fiscal" in basis
    assert "report date" in basis
    assert "calendar" not in basis


def test_missing_fiscal_year_end_is_an_honest_empty_state(monkeypatch) -> None:
    _patch(monkeypatch, _SUBMISSIONS_NO_FYE)
    data = _run(quarter="Q1 FY26").data
    assert data["status"] != "ok"
    assert data["utterances"] == []
    assert "fiscal year end" in data["reason"].lower()
    assert data["data_mode"] != "provider_unavailable"


def test_without_quarter_a_missing_fiscal_year_end_leaves_the_label_empty(monkeypatch) -> None:
    _patch(monkeypatch, _SUBMISSIONS_NO_FYE)
    data = _run().data
    assert data["status"] == "ok"
    assert data["event"]["accession"] == _ACC_APR
    assert data["event"].get("quarter") is None
    assert "fiscal" in data["event"]["quarter_basis"].lower()


def test_archive_label_basis_is_disclosed_as_ingested(monkeypatch) -> None:
    archived = [{
        "quarter": "Q1 FY26",
        "title": "ACME Q1 FY26 call",
        "event_date": "2026-04-28",
        "utterances": [{"section": "prepared_remarks", "speaker": "CEO",
                        "role": "CEO", "utterance": "Archived remarks."}],
    }]
    _patch(monkeypatch, _SUBMISSIONS_DEC, archived=archived)
    data = _run(quarter="Q1 FY26").data
    assert data["status"] == "ok"
    assert data["data_mode"] == "cached_snapshot"
    assert "as ingested" in data["event"]["quarter_basis"].lower()
