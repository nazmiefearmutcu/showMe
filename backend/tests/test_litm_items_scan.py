"""LITM reads 8-K item codes from the Awareness SEC filing index (through CACT's events_8k).

Offline by construction: the real CACT and LITM run, and the Awareness client is replaced by the same
``Routes`` fake the CACT tests use (keyed by endpoint path, raising ``AwarenessUnavailable`` on demand).
Honesty rules under test: a filing with no item codes is a provider gap, not an empty result; no 8-K in
the window is ``empty`` with the "not a verified absence" wording; an unreachable Awareness is
``provider_unavailable`` with the client's reason.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.core.instrument import AssetClass, Instrument  # noqa: E402
from showme.engine.data_sources.awareness import AwarenessResponse, AwarenessUnavailable  # noqa: E402
from showme.engine.functions.calendar import _common as aw_common  # noqa: E402
from showme.engine.functions.misc._bonus import LITMFunction  # noqa: E402

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
OK_PROVIDERS = [{"provider": "sec.edgar", "status": "ok", "last_ok_at": None, "last_error": None}]
ITEM_LABELS = {
    "1.03": "Bankruptcy or Receivership",
    "2.02": "Results of Operations and Financial Condition",
    "5.02": "Departure/Election of Directors or Officers",
    "9.01": "Financial Statements and Exhibits",
}


def _day(offset: int) -> str:
    return (datetime.now(UTC).date() + timedelta(days=offset)).isoformat()


class Routes:
    """Awareness fake keyed by the endpoint path the function asks for (without ``/v1/markets``)."""

    def __init__(self, table: dict[str, Any] | None = None, *, down: str | None = None,
                 providers: list[dict[str, Any]] | None = None) -> None:
        self.table = table or {}
        self.down = down
        self.providers = providers or OK_PROVIDERS
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get(self, path: str, params: dict[str, Any] | None = None) -> AwarenessResponse:
        self.calls.append((path, dict(params or {})))
        if self.down:
            raise AwarenessUnavailable(self.down)
        payload = self.table.get(path, [])
        if isinstance(payload, Exception):
            raise payload
        meta = {"generated_at": "2026-11-08T00:00:00+00:00", "providers": self.providers,
                "notes": [], "filters": dict(params or {})}
        return AwarenessResponse(data=payload, meta=meta, url=path)


def _filing(fid: str, accession: str, offset: int, form: str, codes: list[str]) -> dict[str, Any]:
    return {
        "id": fid, "type": "filing", "symbol": "AAPL", "company": "Apple", "date": _day(offset),
        "time_of_day": None, "status": "filed",
        "fields": {
            "form": form, "accession": accession, "cik": "0000320193",
            "url": f"https://www.sec.gov/Archives/{accession}.htm",
            "items": [{"code": c, "label": ITEM_LABELS.get(c, c)} for c in codes],
            "material": True,
        },
        "sources": [{"provider": "sec.edgar", "url": None, "fetched_at": None, "basis": "native"}],
    }


def _aapl_filings() -> list[dict[str, Any]]:
    """Newest 8-K first item is 2.02; the 5.02 sits on the second item of an older 8-K/A."""
    return [
        _filing("f-10q", "A-1", -120, "10-Q", []),
        _filing("f-new", "A-2", -6, "8-K", ["2.02", "9.01"]),
        _filing("f-mid", "A-3", -68, "8-K/A", ["2.02", "5.02"]),
        _filing("f-old", "A-5", -202, "8-K", ["5.02"]),
    ]


def _run_litm(monkeypatch, table: dict[str, Any] | None = None, *, down: str | None = None,
              params: dict[str, Any] | None = None, instrument: Instrument = AAPL):
    routes = Routes(table or {"/calendar/corporate": [], "/filings": []}, down=down)
    monkeypatch.setattr(aw_common, "get_awareness_client", lambda: routes)
    result = asyncio.run(LITMFunction(FunctionDeps()).execute(instrument=instrument, **(params or {})))
    return result, routes


def test_litm_reports_item_502_from_non_newest_8k(monkeypatch) -> None:
    result, _ = _run_litm(monkeypatch, {"/filings": _aapl_filings(), "/calendar/corporate": []})
    assert result.data["status"] == "ok", result.data
    codes = [r["item_code"] for r in result.data["rows"]]
    assert "5.02" in codes
    accessions = {r["accession"] for r in result.data["rows"]}
    # A-3's first item is 2.02, so the de-duplicated 5.02 must come from the one-entry-per-filing events_8k.
    assert "A-3" in accessions and "A-5" in accessions
    assert "2.02" not in " ".join(codes)
    assert all(r["source_mode"] == "awareness_sec_8k" for r in result.data["rows"])


def test_litm_scans_every_8k_filing_not_just_one(monkeypatch) -> None:
    result, _ = _run_litm(monkeypatch, {"/filings": _aapl_filings(), "/calendar/corporate": []})
    assert result.data["all_8k_events"] == 3
    assert result.data["scanned_8k"] == 3


def test_litm_uses_awareness_sources_and_no_sec_edgar(monkeypatch) -> None:
    result, routes = _run_litm(monkeypatch, {"/filings": _aapl_filings(), "/calendar/corporate": []})
    assert "awareness:filings" in result.sources
    assert all(src.startswith("awareness:") for src in result.sources)
    filings_calls = [params for path, params in routes.calls if path == "/filings"]
    assert filings_calls and filings_calls[0]["days"] == 365


def test_litm_without_item_codes_is_not_reported_as_empty(monkeypatch) -> None:
    filings = [_filing("f-new", "A-2", -6, "8-K", []), _filing("f-old", "A-5", -202, "8-K", [])]
    result, _ = _run_litm(monkeypatch, {"/filings": filings, "/calendar/corporate": []})
    # Filing rows give no way to classify items: that is a provider gap, not
    # a verified absence of litigation events.
    assert result.data["status"] == "provider_unavailable"
    assert result.data["rows"][0]["event_type"] == "item_codes_unavailable"
    assert result.data["rows"][0]["event_type"] != "no_litigation_event_found"
    assert "not a verified absence" in result.data["reason"]
    assert result.metadata["live"] is False


def test_litm_partial_item_codes_keep_status_and_count_the_gap(monkeypatch) -> None:
    filings = [_filing("f-new", "A-2", -6, "8-K", []), _filing("f-old", "A-5", -202, "8-K", ["5.02"])]
    result, _ = _run_litm(monkeypatch, {"/filings": filings, "/calendar/corporate": []})
    assert result.data["status"] == "ok"
    assert result.data["unclassified_8k"] == 1
    assert [r["accession"] for r in result.data["rows"]] == ["A-5"]


def test_litm_no_8k_in_window_is_empty_not_a_verified_absence(monkeypatch) -> None:
    filings = [_filing("f-10q", "A-1", -120, "10-Q", [])]
    result, _ = _run_litm(monkeypatch, {"/filings": filings, "/calendar/corporate": []})
    assert result.data["status"] == "empty"
    assert result.data["rows"][0]["event_type"] == "no_8k_filings_in_window"
    assert "not a verified absence" in result.data["reason"]


def test_litm_no_litigation_item_among_scanned_8ks_is_empty(monkeypatch) -> None:
    filings = [_filing("f-new", "A-2", -6, "8-K", ["2.02", "9.01"])]
    result, _ = _run_litm(monkeypatch, {"/filings": filings, "/calendar/corporate": []})
    assert result.data["status"] == "empty"
    row = result.data["rows"][0]
    assert row["event_type"] == "no_litigation_event_found"
    assert row["scanned_8k"] == 1


def test_litm_awareness_down_is_provider_unavailable_with_reason(monkeypatch) -> None:
    result, _ = _run_litm(monkeypatch, down="awareness service is not running at http://127.0.0.1:8086")
    assert result.data["status"] == "provider_unavailable"
    assert "not running" in result.data["reason"]
    assert result.metadata["live"] is False
    assert result.metadata["data_mode"] == "provider_unavailable"


def test_litm_filings_leg_down_is_provider_unavailable_not_empty(monkeypatch) -> None:
    table = {"/calendar/corporate": [], "/filings": AwarenessUnavailable("filings endpoint timed out")}
    result, _ = _run_litm(monkeypatch, table)
    assert result.data["status"] == "provider_unavailable"
    assert "filings endpoint timed out" in result.data["reason"]
    assert result.data["rows"][0]["event_type"] == "provider_unavailable"


def test_litm_reference_flag_keeps_the_labelled_model_and_skips_awareness(monkeypatch) -> None:
    result, routes = _run_litm(monkeypatch, {"/filings": _aapl_filings()}, params={"reference": "true"})
    assert result.sources == ["litigation_monitor_model"]
    assert result.metadata["data_mode"] == "modeled"
    assert routes.calls == []


def test_litm_requires_an_instrument() -> None:
    with pytest.raises(ValueError):
        asyncio.run(LITMFunction(FunctionDeps()).execute(instrument=None))
