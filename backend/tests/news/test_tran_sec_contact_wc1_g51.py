"""Regression tests for TRAN#4: the SEC User-Agent carried a placeholder contact
(``contact@example.com``). SEC fair-access asks for the operator's real contact
address, so the value now comes from ``SEC_EDGAR_USER_AGENT`` and a missing
value is reported rather than replaced by a made-up address. No network is used.
"""

from __future__ import annotations

import asyncio

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.news import tran as tran_mod
from showme.engine.functions.news.tran import TRANFunction

_CIK = "0000320193"
_ACCESSION = "0000320193-26-000024"


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


class _RecordingSecClient:
    def __init__(self) -> None:
        self.user_agents: list[str] = []

    async def get(self, url, headers=None, **kwargs):  # noqa: ARG002
        self.user_agents.append((headers or {}).get("User-Agent", ""))
        nodash = _ACCESSION.replace("-", "")
        if url.endswith(f"/submissions/CIK{_CIK}.json"):
            return _Resp({"filings": {"recent": {
                "form": ["8-K"],
                "accessionNumber": [_ACCESSION],
                "primaryDocument": ["a.htm"],
                "reportDate": ["2026-10-30"],
                "filingDate": ["2026-10-30"],
                "items": ["2.02"],
            }}})
        if url.endswith(f"/{nodash}/{_ACCESSION}-index.json"):
            return _Resp({"directory": {"item": [{"name": "ex99-1.htm"}]}})
        if url.endswith(f"/{nodash}/ex99-1.htm"):
            return _Resp(text="<p>Apple reports fourth quarter results.</p>")
        return _Resp(status_code=404)


def _run_with_recorder(monkeypatch) -> _RecordingSecClient:
    client = _RecordingSecClient()

    async def _fake_client():
        return client

    async def _fake_cik(symbol, deps=None):  # noqa: ARG001
        return _CIK

    from showme.engine.services import transcripts_archive as archive

    monkeypatch.setattr(tran_mod, "_http_client", _fake_client)
    monkeypatch.setattr(tran_mod, "_resolve_cik", _fake_cik)
    monkeypatch.setattr(archive, "list_for_symbol", lambda *a, **k: [])
    asyncio.run(TRANFunction().execute(Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)))
    return client


def test_tran4_configured_sec_contact_is_sent(monkeypatch) -> None:
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "showMe Research ops@showme-desk.org")
    client = _run_with_recorder(monkeypatch)
    assert client.user_agents, "SEC requests must be made"
    assert set(client.user_agents) == {"showMe Research ops@showme-desk.org"}


def test_tran4_unconfigured_contact_never_sends_placeholder(monkeypatch) -> None:
    monkeypatch.delenv("SEC_EDGAR_USER_AGENT", raising=False)
    client = _run_with_recorder(monkeypatch)
    assert client.user_agents
    assert all("example.com" not in ua for ua in client.user_agents)


def test_tran4_unconfigured_contact_is_reported_as_a_warning(monkeypatch) -> None:
    monkeypatch.delenv("SEC_EDGAR_USER_AGENT", raising=False)

    client = _RecordingSecClient()

    async def _fake_client():
        return client

    async def _fake_cik(symbol, deps=None):  # noqa: ARG001
        return _CIK

    from showme.engine.services import transcripts_archive as archive

    monkeypatch.setattr(tran_mod, "_http_client", _fake_client)
    monkeypatch.setattr(tran_mod, "_resolve_cik", _fake_cik)
    monkeypatch.setattr(archive, "list_for_symbol", lambda *a, **k: [])
    result = asyncio.run(
        TRANFunction().execute(Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY))
    )
    assert any("SEC_EDGAR_USER_AGENT" in w for w in result.warnings)
