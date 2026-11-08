"""S2a — calendar functions on the Awareness data service (ECO, MEET, EVTS, DVD, CACT, TRDH, ERN, IPO).

Offline by construction: every test injects a route fake through the ``_awareness`` seam, so no
test touches the live awareness-markets service. Honesty rules under test: an answered call with
no rows is ``empty`` (never ``ok``), an unreachable service is ``provider_unavailable`` with the
client's reason, and a stale provider keeps the rows but flips ``live`` off.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.data_sources.awareness import AwarenessResponse, AwarenessUnavailable  # noqa: E402
from showme.engine.functions.comm import meet as meet_mod  # noqa: E402
from showme.engine.functions.calendar import ern as ern_mod  # noqa: E402
from showme.engine.functions.calendar import ipo as ipo_mod  # noqa: E402
from showme.engine.functions.equity.cact import CACTFunction  # noqa: E402
from showme.engine.functions.equity.dvd import DVDFunction  # noqa: E402
from showme.engine.functions.macro import eco as eco_mod  # noqa: E402
from showme.engine.functions.macro import trdh as trdh_mod  # noqa: E402
from showme.engine.functions.news.evts import EVTSFunction  # noqa: E402
from showme.engine.services import world_events as we  # noqa: E402

OK_PROVIDERS = [{"provider": "test.fixture", "status": "ok", "last_ok_at": None, "last_error": None}]


def _run(coro):
    return asyncio.run(coro)


def _today() -> date:
    return datetime.now(UTC).date()


def _day(offset: int) -> str:
    return (_today() + timedelta(days=offset)).isoformat()


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


def _econ(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": "e1", "country": "US", "currency": "USD", "title": "CPI MoM", "category": "cpi",
        "scheduled_at": f"{_day(1)}T12:30:00Z", "all_day": False, "importance": 3,
        "actual": None, "forecast": "0.2%", "previous": "0.1%", "revised": None,
        "actual_value": None, "forecast_value": 0.2, "previous_value": 0.1, "unit": "%",
        "surprise": None, "surprise_direction": None, "status": "scheduled",
        "description": None, "sources": [],
    }
    row.update(overrides)
    return row


# ── ECO ────────────────────────────────────────────────────────────────

def test_eco_rows_pass_through_from_awareness_without_rescaling():
    fn = eco_mod.ECOFunction(FunctionDeps())
    fn._awareness = Routes({"/calendar/economic": [
        _econ(id="k1", title="Initial Jobless Claims", actual="215K", actual_value=215000.0, unit="K"),
    ], "/calendar/holidays": []})
    result = _run(fn.execute(country="US", days=7))
    row = result.data["rows"][0]
    assert result.data["status"] == "ok"
    # Awareness already scaled the value: ECO must not multiply the K suffix again.
    assert row["actual_value"] == 215000.0
    assert row["unit"] == "K"
    assert result.sources == ["awareness:econ", "awareness:holidays"]


def test_eco_empty_window_is_empty_not_ok():
    fn = eco_mod.ECOFunction(FunctionDeps())
    fn._awareness = Routes({"/calendar/economic": [], "/calendar/holidays": []})
    result = _run(fn.execute(country="TR", days=3))
    assert result.data["status"] == "empty"
    assert result.data["rows"] == []


def test_eco_unavailable_is_honest_and_carries_reason():
    fn = eco_mod.ECOFunction(FunctionDeps())
    fn._awareness = Routes(down="awareness service is not running at http://127.0.0.1:8086")
    result = _run(fn.execute(country="US"))
    assert result.data["status"] == "provider_unavailable"
    assert "not running" in result.data["reason"]
    assert result.data["rows"] == []
    assert result.metadata["live"] is False


def test_eco_stale_provider_serves_rows_as_cached_snapshot():
    fn = eco_mod.ECOFunction(FunctionDeps())
    stale = [{"provider": "econ.nasdaq", "status": "down", "last_ok_at": None, "last_error": "timeout"}]
    fn._awareness = Routes({"/calendar/economic": [_econ()], "/calendar/holidays": []}, providers=stale)
    result = _run(fn.execute(country="US"))
    assert result.data["status"] == "ok"
    assert result.metadata["data_mode"] == "cached_snapshot"
    assert result.metadata["live"] is False


def test_eco_reference_schedule_is_removed():
    fn = eco_mod.ECOFunction(FunctionDeps())
    fn._awareness = Routes({})
    result = _run(fn.execute(reference="true"))
    assert result.data["status"] == "input_error"
    assert "reference schedule removed" in result.data["reason"]


def test_eco_next_high_impact_is_first_scheduled_high_row():
    fn = eco_mod.ECOFunction(FunctionDeps())
    fn._awareness = Routes({"/calendar/economic": [
        _econ(id="low", importance=1, title="Minor", scheduled_at=f"{_day(1)}T09:00:00Z"),
        _econ(id="hi", importance=3, title="FOMC Rate Decision", scheduled_at=f"{_day(2)}T18:00:00Z"),
    ], "/calendar/holidays": []})
    result = _run(fn.execute(country="US", importance=1, days=7))
    assert result.data["next_high_impact"]["id"] == "hi"
    assert result.data["rows"][0]["id"] == "low"
    assert result.data["rows"][1]["is_central_bank"] is True


def test_eco_holidays_ride_along_for_selected_countries():
    fn = eco_mod.ECOFunction(FunctionDeps())
    holiday = {"date": _day(1), "country": "TR", "exchange": None, "name": "Republic Day",
               "local_name": None, "kind": "public", "early_close_time": None, "source": {"provider": "nager"}}
    fn._awareness = Routes({"/calendar/economic": [_econ(country="TR", title="TCMB Rate")],
                            "/calendar/holidays": [holiday]})
    result = _run(fn.execute(country="UK", days=7))
    assert result.data["holidays"][0]["name"] == "Republic Day"
    assert result.data["filters"]["countries"] == ["GB"]


# ── TRDH ────────────────────────────────────────────────────────────────

def _tokyo_sessions() -> list[dict[str, Any]]:
    return [{
        "date": "2026-11-09", "open_utc": "2026-11-09T00:00:00+00:00", "close_utc": "2026-11-09T06:30:00+00:00",
        "break_start_utc": "2026-11-09T02:30:00+00:00", "break_end_utc": "2026-11-09T03:30:00+00:00",
        "open_local": "09:00", "close_local": "15:30", "break_local": "11:30-12:30", "early_close": False,
    }]


def _freeze_now(monkeypatch, module, when: datetime) -> None:
    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return when if tz is None else when.astimezone(tz)

    monkeypatch.setattr(module, "datetime", _Frozen)


def test_trdh_tokyo_lunch_break_counts_as_closed(monkeypatch):
    _freeze_now(monkeypatch, trdh_mod, datetime(2026, 11, 9, 3, 0, tzinfo=UTC))
    fn = trdh_mod.TRDHFunction(FunctionDeps())
    fn._awareness = Routes({"/calendar/sessions": {"timezone": "Asia/Tokyo", "regular_close_local": "15:30",
                                                    "sessions": _tokyo_sessions()},
                            "/calendar/holidays": []})
    result = _run(fn.execute(exchanges="TSE"))
    block = result.data["exchanges"][0]
    assert block["mic"] == "XTKS"
    assert block["is_open_now"] is False, "03:00 UTC is inside the 11:30-12:30 JST lunch break"
    assert block["today"]["date"] == "2026-11-09"


def test_trdh_open_before_lunch_and_next_close_reported(monkeypatch):
    _freeze_now(monkeypatch, trdh_mod, datetime(2026, 11, 9, 1, 0, tzinfo=UTC))
    fn = trdh_mod.TRDHFunction(FunctionDeps())
    fn._awareness = Routes({"/calendar/sessions": {"timezone": "Asia/Tokyo", "regular_close_local": "15:30",
                                                    "sessions": _tokyo_sessions()},
                            "/calendar/holidays": []})
    block = _run(fn.execute(exchanges="XTKS")).data["exchanges"][0]
    assert block["is_open_now"] is True
    # Before the 11:30 JST lunch break the next close is the break start (02:30 UTC), not the 06:30 UTC close.
    assert block["next_close_utc"].startswith("2026-11-09T02:30")
    # The next open event after the morning session is the lunch-break end (reopening), not tomorrow's open.
    assert block["next_open_utc"].startswith("2026-11-09T03:30")


def test_trdh_nyse_early_close_is_flagged_and_closure_listed(monkeypatch):
    _freeze_now(monkeypatch, trdh_mod, datetime(2026, 11, 27, 15, 0, tzinfo=UTC))
    early = {"date": "2026-11-27", "open_utc": "2026-11-27T14:30:00+00:00", "close_utc": "2026-11-27T18:00:00+00:00",
             "break_start_utc": None, "break_end_utc": None, "open_local": "09:30", "close_local": "13:00",
             "break_local": None, "early_close": True}
    closure = {"date": "2026-11-26", "country": "US", "exchange": "XNYS", "name": "Thanksgiving",
               "local_name": None, "kind": "market_closed", "early_close_time": None, "source": {}}
    fn = trdh_mod.TRDHFunction(FunctionDeps())
    fn._awareness = Routes({"/calendar/sessions": {"timezone": "America/New_York", "regular_close_local": "16:00",
                                                    "sessions": [early]},
                            "/calendar/holidays": [closure]})
    block = _run(fn.execute(exchanges="NYSE")).data["exchanges"][0]
    assert block["today"]["early_close"] is True
    assert block["today"]["close_local"] == "13:00"
    assert block["closures"][0]["name"] == "Thanksgiving"


def test_trdh_unavailable_and_unknown_codes(monkeypatch):
    fn = trdh_mod.TRDHFunction(FunctionDeps())
    fn._awareness = Routes(down="awareness service is not running")
    result = _run(fn.execute(exchanges="XNYS"))
    assert result.data["status"] == "provider_unavailable"
    fn2 = trdh_mod.TRDHFunction(FunctionDeps())
    fn2._awareness = Routes(down="x")
    skipped = _run(fn2.execute(exchanges="bad!!"))
    assert any("Unknown exchange" in w for w in skipped.warnings)


# ── EVTS ────────────────────────────────────────────────────────────────

def test_evts_upcoming_ascending_recent_descending_and_symbol_required():
    fn = EVTSFunction(FunctionDeps())
    fn._awareness = Routes({
        "/calendar/corporate": [
            {"id": "a", "type": "earnings", "symbol": "AAPL", "company": "Apple", "date": _day(10),
             "time_of_day": "amc", "status": "scheduled", "fields": {"eps_estimate": 1.5}, "sources": []},
            {"id": "b", "type": "earnings", "symbol": "AAPL", "company": "Apple", "date": _day(3),
             "time_of_day": "bmo", "status": "scheduled", "fields": {}, "sources": []},
            {"id": "c", "type": "dividend", "symbol": "AAPL", "company": "Apple", "date": _day(-5),
             "time_of_day": None, "status": "confirmed", "fields": {"amount": 0.25}, "sources": []},
            {"id": "d", "type": "split", "symbol": "AAPL", "company": "Apple", "date": _day(-40),
             "time_of_day": None, "status": "confirmed", "fields": {}, "sources": []},
        ],
    })
    result = _run(fn.execute(symbol="aapl", types="earnings,dividend,split"))
    data = result.data
    assert data["status"] == "ok"
    assert [r["date"] for r in data["upcoming"]] == sorted(r["date"] for r in data["upcoming"])
    assert [r["date"] for r in data["recent"]] == sorted((r["date"] for r in data["recent"]), reverse=True)
    assert data["rows"] == data["upcoming"] + data["recent"]
    assert data["rows"][0]["event"] == "Earnings report"
    missing = _run(EVTSFunction(FunctionDeps()).execute())
    assert missing.data["status"] == "input_required"


def test_evts_empty_and_unavailable():
    fn = EVTSFunction(FunctionDeps())
    fn._awareness = Routes({"/calendar/corporate": []})
    assert _run(fn.execute(symbol="ZZZZ")).data["status"] == "empty"
    fn2 = EVTSFunction(FunctionDeps())
    fn2._awareness = Routes(down="awareness down")
    down = _run(fn2.execute(symbol="AAPL"))
    assert down.data["status"] == "provider_unavailable"
    assert down.metadata["live"] is False


# ── DVD ─────────────────────────────────────────────────────────────────

def test_dvd_upcoming_from_awareness_and_no_template_when_empty():
    fn = DVDFunction(FunctionDeps())
    fn._awareness = Routes({"/calendar/corporate": [{
        "id": "d1", "type": "dividend", "symbol": "AAPL", "company": "Apple", "date": _day(4),
        "time_of_day": None, "status": "confirmed",
        "fields": {"amount": 0.27, "annual_amount": 1.08, "record_date": _day(4), "pay_date": _day(8)},
        "sources": [],
    }]})
    result = _run(fn.execute(symbol="AAPL", history=False))
    assert result.data["status"] == "ok"
    assert result.data["upcoming"][0]["amount"] == 0.27
    assert result.data["summary"]["next_ex_date"] == _day(4)
    empty = DVDFunction(FunctionDeps())
    empty._awareness = Routes({"/calendar/corporate": []})
    none = _run(empty.execute(symbol="ZZZZ", history=False))
    assert none.data["status"] == "empty"
    assert "dividends" not in none.data, "the fabricated dividend template is gone"


def test_dvd_unavailable_is_honest():
    fn = DVDFunction(FunctionDeps())
    fn._awareness = Routes(down="awareness down")
    result = _run(fn.execute(symbol="AAPL", history=False))
    assert result.data["status"] == "provider_unavailable"


# ── CACT ────────────────────────────────────────────────────────────────

def test_cact_dedupes_and_labels_sources_and_uses_split_ratio():
    fn = CACTFunction(FunctionDeps())
    dividend = {"id": "x", "type": "dividend", "symbol": "AAPL", "company": "Apple", "date": _day(-10),
                "time_of_day": None, "status": "confirmed", "fields": {"amount": 0.25}, "sources": []}
    split = {"id": "s", "type": "split", "symbol": "AAPL", "company": "Apple", "date": _day(-20),
             "time_of_day": None, "status": "confirmed",
             "fields": {"ratio": "1:4", "ratio_from": 1.0, "ratio_to": 4.0}, "sources": []}
    eight_k = {"id": "f", "type": "filing", "symbol": None, "company": "Apple", "date": _day(-15),
               "time_of_day": None, "status": "filed",
               "fields": {"form": "8-K", "accession": "0001", "url": "https://sec.example/x"}, "sources": []}
    fn._awareness = Routes({
        "/calendar/corporate": [dividend, dict(dividend, id="dup"), split],
        "/filings": [eight_k],
    })
    result = _run(fn.execute(symbol="AAPL"))
    rows = result.data["rows"]
    assert result.data["status"] == "ok"
    assert result.data["duplicates_dropped"] == 1
    assert [r["action_type"] for r in rows].count("dividend") == 1
    split_row = next(r for r in rows if r["action_type"] == "split")
    assert split_row["value"] == 4.0
    assert {r["source"] for r in rows} == {"awareness:corporate", "awareness:filings"}
    assert result.sources == ["awareness:corporate", "awareness:filings"]


def test_cact_requires_symbol_and_reports_unavailable():
    assert _run(CACTFunction(FunctionDeps()).execute()).data["status"] == "input_required"
    fn = CACTFunction(FunctionDeps())
    fn._awareness = Routes(down="awareness down")
    result = _run(fn.execute(symbol="AAPL"))
    assert result.data["status"] == "provider_unavailable"


# ── MEET ────────────────────────────────────────────────────────────────

def test_meet_empty_forward_calendar_is_empty_not_ok():
    fn = meet_mod.MEETFunction(FunctionDeps())
    fn._awareness = Routes({"/calendar/economic": [], "/news": []})
    result = _run(fn.execute(limit=50))
    assert result.data["status"] == "empty"
    assert result.data["rows"] == []


def test_meet_unavailable_is_provider_unavailable():
    fn = meet_mod.MEETFunction(FunctionDeps())
    fn._awareness = Routes(down="awareness service is not running")
    result = _run(fn.execute(limit=50))
    assert result.data["status"] == "provider_unavailable"
    assert "not running" in result.data["reason"]


def test_meet_geopolitics_impact_comes_from_awareness_topics_and_importance():
    fn = meet_mod.MEETFunction(FunctionDeps())
    news = [{
        "id": "n1", "title": "Sanctions tighten on regional oil exporters", "url": "https://news.example/a",
        "publisher_name": "Wire", "published_at": datetime.now(UTC).isoformat(),
        "summary": "New sanctions and tariffs announced.", "topics": ["sanctions"], "symbols": [],
        "countries": ["RU"], "importance": 82, "quality_label": "standard",
    }, {
        "id": "n2", "title": "Quarterly pricing update for widgets", "url": "https://news.example/b",
        "publisher_name": "Trade", "published_at": datetime.now(UTC).isoformat(),
        "summary": "Routine trade note.", "topics": [], "symbols": [], "countries": [],
        "importance": 30, "quality_label": "standard",
    }]
    fn._awareness = Routes({"/calendar/economic": [_econ()], "/calendar/holidays": [], "/news": news})
    result = _run(fn.execute(limit=100))
    rows = {r["title"]: r for r in result.data["rows"] if r.get("kind") == "world"}
    sanction = rows["Sanctions tighten on regional oil exporters"]
    assert sanction["impact"] == "high"
    assert sanction["details"]["awareness_topics"] == ["sanctions"]
    routine = rows["Quarterly pricing update for widgets"]
    assert routine["impact"] == "low"
    assert "awareness:news" in result.sources


def test_meet_awareness_news_stream_is_topic_scoped_without_countries():
    fn = meet_mod.MEETFunction(FunctionDeps())
    routes = Routes({"/calendar/economic": [_econ()], "/calendar/holidays": [], "/news": []})
    fn._awareness = routes
    _run(fn.execute(limit=20))
    news_calls = [params for path, params in routes.calls if path == "/news"]
    assert news_calls and "topics" in news_calls[0]
    assert set(news_calls[0]["topics"].split(",")) == {"geopolitics", "sanctions", "trade_tariffs"}
    assert news_calls[0]["min_quality"] == "standard"


def test_meet_holidays_come_from_awareness_for_followed_countries():
    fn = meet_mod.MEETFunction(FunctionDeps())
    holiday = {"date": _day(2), "country": "TR", "exchange": None, "name": "Victory Day", "local_name": None,
               "kind": "public", "early_close_time": None, "source": {"provider": "nager"}}
    routes = Routes({"/calendar/economic": [_econ()], "/calendar/holidays": [holiday], "/news": []})
    fn._awareness = routes
    result = _run(fn.execute(countries="TR", limit=50))
    assert any(r["title"].startswith("Public Holiday: Victory Day") for r in result.data["rows"])
    assert "awareness:holidays" in result.sources
    holiday_calls = [params for path, params in routes.calls if path == "/calendar/holidays"]
    assert holiday_calls and holiday_calls[0]["countries"] == "TR"


# ── ERN ─────────────────────────────────────────────────────────────────

def _earn(symbol: str, date_text: str, cap: float, tod: str = "amc") -> dict[str, Any]:
    return {"id": symbol + date_text, "type": "earnings", "symbol": symbol, "company": symbol + " Inc",
            "date": date_text, "time_of_day": tod, "status": "scheduled",
            "fields": {"eps_estimate": 1.0, "num_estimates": 5, "fiscal_quarter": "Sep/2026",
                       "market_cap": cap, "last_year_eps": 0.8, "last_year_report_date": _day(-360)},
            "sources": []}


def test_ern_sorts_by_date_then_market_cap_and_flags_watchlist():
    fn = ern_mod.ERNFunction(FunctionDeps())
    fn._awareness = Routes({
        "/calendar/corporate": [
            _earn("SMALL", _day(2), 1e9, "bmo"),
            _earn("BIG", _day(2), 9e12, "amc"),
            _earn("MID", _day(1), 5e10, "amc"),
        ],
        "/watchlist": ["BIG", "NVDA"],
    })
    result = _run(fn.execute(days=7))
    symbols = [r["symbol"] for r in result.data["rows"]]
    assert symbols == ["MID", "BIG", "SMALL"]
    big = next(r for r in result.data["rows"] if r["symbol"] == "BIG")
    assert big["in_watchlist"] is True
    assert next(r for r in result.data["rows"] if r["symbol"] == "SMALL")["in_watchlist"] is False
    assert result.data["by_day"] == {_day(1): 1, _day(2): 2}
    assert result.data["watchlist_count"] == 1


def test_ern_filters_market_cap_and_timing_and_reports_empty():
    fn = ern_mod.ERNFunction(FunctionDeps())
    fn._awareness = Routes({"/calendar/corporate": [
        _earn("A", _day(1), 2e10, "amc"),
        _earn("B", _day(1), 5e9, "bmo"),
    ], "/watchlist": []})
    result = _run(fn.execute(days=3, min_market_cap="1e10", time_of_day="amc"))
    assert [r["symbol"] for r in result.data["rows"]] == ["A"]
    empty = ern_mod.ERNFunction(FunctionDeps())
    empty._awareness = Routes({"/calendar/corporate": [], "/watchlist": []})
    assert _run(empty.execute(days=3)).data["status"] == "empty"


def test_ern_unavailable_and_metadata_contract():
    fn = ern_mod.ERNFunction(FunctionDeps())
    fn._awareness = Routes(down="awareness down")
    result = _run(fn.execute(days=3))
    assert result.data["status"] == "provider_unavailable"
    assert result.sources == ["no_live_source"]


# ── IPO ─────────────────────────────────────────────────────────────────

def test_ipo_sections_split_by_status_and_registration_form():
    fn = ipo_mod.IPOFunction(FunctionDeps())
    # The function asks for types=ipo and types=filing; answer both through one typed fake.
    class _ByType(Routes):
        async def get(self, path, params=None):
            kind = (params or {}).get("types")
            if kind == "ipo":
                payload = [{"id": "p1", "type": "ipo", "symbol": "NEWC", "company": "New Co", "exchange": "NASDAQ",
                            "date": _day(-3), "time_of_day": None, "status": "priced",
                            "fields": {"price": 18.0, "price_range": "16-18", "shares_offered": 5_000_000,
                                       "deal_size_usd": 90_000_000}, "sources": []},
                           {"id": "u1", "type": "ipo", "symbol": "SOON", "company": "Soon Inc", "exchange": "NYSE",
                            "date": _day(20), "time_of_day": None, "status": "scheduled", "fields": {},
                            "sources": []}]
            else:
                payload = [{"id": "f1", "type": "filing", "symbol": None, "company": "Filer", "exchange": None,
                            "date": _day(-5), "time_of_day": None, "status": "filed",
                            "fields": {"form": "S-1/A"}, "sources": []},
                           {"id": "f2", "type": "filing", "symbol": None, "company": "Quitter", "exchange": None,
                            "date": _day(-6), "time_of_day": None, "status": "filed",
                            "fields": {"form": "RW"}, "sources": []},
                           {"id": "f3", "type": "filing", "symbol": None, "company": "Other", "exchange": None,
                            "date": _day(-7), "time_of_day": None, "status": "filed",
                            "fields": {"form": "8-K"}, "sources": []}]
            meta = {"generated_at": "2026-11-08T00:00:00+00:00", "providers": OK_PROVIDERS, "notes": [],
                    "filters": dict(params or {})}
            return AwarenessResponse(data=payload, meta=meta, url=path)

    fn._awareness = _ByType()
    result = _run(fn.execute(days_back=30, days_ahead=60))
    sections = result.data["sections"]
    assert [r["symbol"] for r in sections["priced"]] == ["NEWC"]
    assert sections["priced"][0]["price"] == 18.0
    assert [r["symbol"] for r in sections["upcoming"]] == ["SOON"]
    assert [r["company"] for r in sections["filed"]] == ["Filer"]
    assert [r["company"] for r in sections["withdrawn"]] == ["Quitter"]
    assert result.data["status"] == "ok"


def test_ipo_empty_and_unavailable():
    fn = ipo_mod.IPOFunction(FunctionDeps())
    fn._awareness = Routes({"/calendar/corporate": []})
    assert _run(fn.execute()).data["status"] == "empty"
    down = ipo_mod.IPOFunction(FunctionDeps())
    down._awareness = Routes(down="awareness down")
    result = _run(down.execute())
    assert result.data["status"] == "provider_unavailable"


# ── cross-cutting ───────────────────────────────────────────────────────

@pytest.mark.parametrize("fn_cls, params", [
    (eco_mod.ECOFunction, {"country": "US"}),
    (trdh_mod.TRDHFunction, {"exchanges": "XNYS"}),
    (ern_mod.ERNFunction, {"days": 3}),
    (ipo_mod.IPOFunction, {}),
])
def test_unavailable_never_claims_live(fn_cls, params):
    fn = fn_cls(FunctionDeps())
    fn._awareness = Routes(down="awareness down")
    result = _run(fn.execute(**params))
    assert result.metadata.get("live") is False
    assert result.metadata.get("data_mode") == "provider_unavailable"


def test_world_events_helpers_still_import_for_meet():
    # MEET's calendar rows depend on world_events' economic_rows; keep the seam honest.
    rows, dropped = we.economic_rows([{"event": "CPI", "date": f"{_day(1)}T12:30:00Z", "country": "US",
                                       "importance": "high"}], now=datetime.now(UTC))
    assert rows and dropped == 0


def test_cact_exposes_decoded_8k_items_for_litm() -> None:
    from showme.engine.functions.equity.cact import _events_8k, _filing_row

    row = _filing_row({
        "date": "2026-11-05",
        "fields": {"form": "8-K", "accession": "0001-26-1", "url": "https://www.sec.gov/x",
                   "items": [{"code": "5.02", "label": "Departure/Election of Directors or Officers"},
                             {"code": "9.01", "label": "Financial Statements and Exhibits"}]},
    })
    events = _events_8k([row])
    assert [e["code"] for e in events] == ["5.02", "9.01"]
    assert events[0]["filing_date"] == "2026-11-05" and events[0]["accession"] == "0001-26-1"


def test_routed_defaults_never_narrow_ern_to_a_peer_group() -> None:
    from showme.server_routes._agent_runtime import _route_function_params

    routed = _route_function_params("ERN", {"days": 5})
    assert "symbols" not in routed and routed["days"] == 5
    explicit = _route_function_params("ERN", {"symbols": "NVDA,AAPL"})
    assert explicit["symbols"] == "NVDA,AAPL"


# ── F2 regressions: live-shaped fixtures (captured from awareness-markets, 2026-11-08) ─────────

_LIVE_DIR = Path(__file__).resolve().parent / "fixtures" / "awareness_live"


def _live(name: str) -> Any:
    """Live awareness ``data`` array or object, read from the captured fixture (UTF-8)."""
    import json

    return json.loads((_LIVE_DIR / name).read_text(encoding="utf-8"))["data"]


def _live_meta(name: str) -> list[dict[str, Any]]:
    import json

    return json.loads((_LIVE_DIR / name).read_text(encoding="utf-8"))["meta"]["providers"]


# C1: live holiday rows carry ``source`` as a ProviderRef object. ECO must hand out the provider name.
def test_c1_eco_renders_live_holiday_source_as_provider_name():
    import json

    fn = eco_mod.ECOFunction(FunctionDeps())
    # Both live shapes: nager public holidays (basis native) and exchange_calendars closures (basis derived).
    live_holidays = _live("holidays_week.json") + _live("holidays_us.json")
    fn._awareness = Routes({
        "/calendar/economic": _live("economic_week.json")[:5],
        "/calendar/holidays": live_holidays,
    }, providers=_live_meta("economic_week.json"))
    result = _run(fn.execute(country="all", days=7))
    holidays = result.data["holidays"]
    assert holidays, "the live holiday window has closures"
    for holiday in holidays:
        assert isinstance(holiday["source"], str) and holiday["source"] in {"nager", "exchange_calendars"}
    assert {h["source"] for h in holidays} == {"nager", "exchange_calendars"}
    assert holidays[0]["source_ref"]["provider"] == holidays[0]["source"]
    json.dumps(result.data)  # the payload must serialise for the pane


def test_c1_holiday_row_flattens_provider_ref_and_keeps_strings():
    from showme.engine.functions.calendar._common import holiday_row

    live = holiday_row({"date": "2026-11-26", "country": "US", "exchange": "XNYS", "name": "Thanksgiving",
                        "kind": "market_closed", "source": {"provider": "exchange_calendars", "url": None,
                                                              "fetched_at": "x", "basis": "derived"}})
    assert live["source"] == "exchange_calendars"
    assert live["source_ref"]["basis"] == "derived"
    plain = holiday_row({"date": "2026-11-26", "country": "US", "name": "X", "source": "nager"})
    assert plain["source"] == "nager" and plain["source_ref"] is None


# I2: distinct 8-K filings on one date stay distinct; the same accession still collapses.
def test_i2_two_same_day_8ks_with_different_items_are_both_kept():
    fn = CACTFunction(FunctionDeps())
    first = {"id": "f1", "type": "filing", "symbol": None, "company": "Acme", "date": _day(-15),
             "time_of_day": None, "status": "filed",
             "fields": {"form": "8-K", "accession": "0001493152-26-050546", "url": "https://sec.example/a",
                        "items": [{"code": "1.03", "label": "Bankruptcy"}]}, "sources": []}
    second = dict(first, id="f2", fields={"form": "8-K", "accession": "0001493152-26-050548",
                                          "url": "https://sec.example/b",
                                          "items": [{"code": "5.02", "label": "Departure of officers"}]})
    fn._awareness = Routes({"/filings": [first, second], "/calendar/corporate": []})
    result = _run(fn.execute(symbol="ACME"))
    assert result.data["counts"]["8-K"] == 2
    assert {r["accession"] for r in result.data["rows"]} == {"0001493152-26-050546", "0001493152-26-050548"}
    assert {e["code"] for e in result.data["events_8k"]} == {"1.03", "5.02"}, "LITM keeps both litigation items"
    assert result.data["duplicates_dropped"] == 0


def test_i2_same_accession_twice_still_collapses():
    fn = CACTFunction(FunctionDeps())
    filing = {"id": "f1", "type": "filing", "symbol": None, "company": "Acme", "date": _day(-15),
              "time_of_day": None, "status": "filed",
              "fields": {"form": "8-K", "accession": "0001", "url": "https://sec.example/a", "items": []},
              "sources": []}
    fn._awareness = Routes({"/filings": [filing, dict(filing, id="copy")], "/calendar/corporate": []})
    result = _run(fn.execute(symbol="ACME"))
    assert result.data["counts"]["8-K"] == 1
    assert result.data["duplicates_dropped"] == 1


# I1: lunch-break boundaries, live XHKG sessions (12:00-13:00 HKT = 04:00-05:00 UTC).
def test_i1_xhkg_during_lunch_next_open_is_break_end(monkeypatch):
    _freeze_now(monkeypatch, trdh_mod, datetime(2026, 11, 9, 4, 30, tzinfo=UTC))
    fn = trdh_mod.TRDHFunction(FunctionDeps())
    fn._awareness = Routes({"/calendar/sessions": {"exchange": "XHKG", "timezone": "Asia/Hong_Kong",
                                                    "regular_close_local": "16:00", "sessions": _live("sessions_xhkg.json")["sessions"]},
                            "/calendar/holidays": []})
    block = _run(fn.execute(exchanges="XHKG")).data["exchanges"][0]
    assert block["is_open_now"] is False
    assert block["next_open_utc"].startswith("2026-11-09T05:00")
    assert block["next_close_utc"].startswith("2026-11-09T08:00")


def test_i1_xhkg_before_lunch_next_close_is_break_start(monkeypatch):
    _freeze_now(monkeypatch, trdh_mod, datetime(2026, 11, 9, 2, 0, tzinfo=UTC))
    fn = trdh_mod.TRDHFunction(FunctionDeps())
    fn._awareness = Routes({"/calendar/sessions": {"exchange": "XHKG", "timezone": "Asia/Hong_Kong",
                                                    "regular_close_local": "16:00", "sessions": _live("sessions_xhkg.json")["sessions"]},
                            "/calendar/holidays": []})
    block = _run(fn.execute(exchanges="XHKG")).data["exchanges"][0]
    assert block["is_open_now"] is True
    assert block["next_close_utc"].startswith("2026-11-09T04:00")


def test_i1_tokyo_during_lunch_next_open_is_break_end(monkeypatch):
    _freeze_now(monkeypatch, trdh_mod, datetime(2026, 11, 9, 2, 45, tzinfo=UTC))
    fn = trdh_mod.TRDHFunction(FunctionDeps())
    fn._awareness = Routes({"/calendar/sessions": {"timezone": "Asia/Tokyo", "regular_close_local": "15:30",
                                                    "sessions": _tokyo_sessions()},
                            "/calendar/holidays": []})
    block = _run(fn.execute(exchanges="XTKS")).data["exchanges"][0]
    assert block["is_open_now"] is False
    assert block["next_open_utc"].startswith("2026-11-09T03:30")
    assert block["next_close_utc"].startswith("2026-11-09T06:30")


# I3-I5: MEET provenance, stale providers, symbol-news errors, impact and methodology.
def test_i3_meet_reports_stale_provider_as_cached_snapshot_with_meta():
    stale = [{"provider": "news.feeds", "status": "degraded", "last_ok_at": None, "last_error": "timeout"}]
    fn = meet_mod.MEETFunction(FunctionDeps())
    fn._awareness = Routes({"/calendar/economic": [_econ()], "/calendar/holidays": [], "/news": []},
                           providers=stale)
    result = _run(fn.execute(limit=20))
    assert result.metadata["data_mode"] == "cached_snapshot"
    assert result.metadata["live"] is False
    assert result.metadata["providers"] == stale
    assert result.data["data_mode"] == "cached_snapshot"
    assert result.data["meta"]["providers"] == stale
    assert "generated_at" in result.data["meta"] and "notes" in result.data["meta"]


def test_i3_meet_live_provenance_uses_sanctioned_mode():
    fn = meet_mod.MEETFunction(FunctionDeps())
    fn._awareness = Routes({"/calendar/economic": [_econ()], "/calendar/holidays": [], "/news": []})
    result = _run(fn.execute(limit=20))
    assert result.metadata["data_mode"] == "live_official"
    assert result.metadata["live"] is True
    assert result.data["data_mode"] == "live_official"
    assert set(result.sources) <= {"awareness:econ", "awareness:holidays", "awareness:news"}


def test_i5_meet_symbol_news_error_is_a_warning_not_silence():
    fn = meet_mod.MEETFunction(FunctionDeps())
    news_down = {"/calendar/economic": [_econ()], "/calendar/holidays": [], "/news": []}

    class _NewsDown(Routes):
        async def get(self, path, params=None):
            if path == "/news" and "symbols" in (params or {}):
                raise AwarenessUnavailable("awareness news is not answering")
            return await super().get(path, params)

    fn._awareness = _NewsDown(news_down)
    result = _run(fn.execute(symbols="BTC", limit=20))
    assert any(w.startswith("symbol_events: awareness news unavailable") for w in result.warnings)


def test_i5_meet_urlless_headline_takes_awareness_impact_not_keywords():
    # "war" in the title makes the keyword classifier say high; Awareness says low importance, no topics.
    news = [{"id": "n9", "title": "War of words over a widget price", "url": "",
             "publisher_name": "Trade", "published_at": datetime.now(UTC).isoformat(),
             "summary": "", "topics": [], "symbols": [], "countries": [], "importance": 12,
             "quality_label": "standard"}]
    fn = meet_mod.MEETFunction(FunctionDeps())
    fn._awareness = Routes({"/calendar/economic": [_econ()], "/calendar/holidays": [], "/news": news})
    result = _run(fn.execute(limit=50))
    row = next(r for r in result.data["rows"] if r.get("kind") == "world")
    assert row["impact"] == "low"
    assert row["details"]["impact_basis"] == "awareness_topics_importance"


def test_i4_meet_methodology_describes_awareness_only():
    fn = meet_mod.MEETFunction(FunctionDeps())
    fn._awareness = Routes({"/calendar/economic": [_econ()], "/calendar/holidays": [], "/news": []})
    text = _run(fn.execute(limit=20)).data["methodology"]
    for stale in ("TradingEconomics", "Finnhub", "ForexFactory", "FinanceCalendar", "Nager", "GDELT", "Google News"):
        assert stale not in text, stale
    assert "/calendar/economic" in text and "/news" in text and "/calendar/holidays" in text


# Stale (cached_snapshot, live False) per function: rows are kept, never presented as live.
def _stale_case(fn_cls, params, table):
    stale = [{"provider": "test.stale", "status": "down", "last_ok_at": None, "last_error": "timeout"}]
    fn = fn_cls(FunctionDeps())
    fn._awareness = Routes(table, providers=stale)
    return _run(fn.execute(**params))


def test_stale_providers_serve_cached_snapshot_for_every_calendar_function():
    corp = {"id": "c1", "type": "dividend", "symbol": "AAPL", "company": "Apple", "date": _day(4),
            "time_of_day": None, "status": "confirmed", "fields": {"amount": 0.27}, "sources": []}
    cases = [
        (eco_mod.ECOFunction, {"country": "US"}, {"/calendar/economic": [_econ()], "/calendar/holidays": []}),
        (meet_mod.MEETFunction, {"limit": 20}, {"/calendar/economic": [_econ()], "/calendar/holidays": [], "/news": []}),
        (EVTSFunction, {"symbol": "AAPL"}, {"/calendar/corporate": [corp], "/filings": []}),
        (DVDFunction, {"symbol": "AAPL", "history": False}, {"/calendar/corporate": [corp]}),
        (CACTFunction, {"symbol": "AAPL"}, {"/calendar/corporate": [corp], "/filings": []}),
        (trdh_mod.TRDHFunction, {"exchanges": "XHKG"},
         {"/calendar/sessions": {"timezone": "Asia/Hong_Kong", "sessions": _live("sessions_xhkg.json")["sessions"]},
          "/calendar/holidays": []}),
        (ern_mod.ERNFunction, {"days": 3}, {"/calendar/corporate": [_earn("AAPL", _day(1), 3e12)], "/watchlist": []}),
        (ipo_mod.IPOFunction, {}, {"/calendar/corporate": [{"id": "p", "type": "ipo", "symbol": "NEWC",
                                                            "company": "New Co", "date": _day(-2),
                                                            "status": "priced", "fields": {"price": 18.0},
                                                            "sources": []}]}),
    ]
    for fn_cls, params, table in cases:
        result = _stale_case(fn_cls, params, table)
        assert result.metadata.get("data_mode") == "cached_snapshot", fn_cls.__name__
        assert result.metadata.get("live") is False, fn_cls.__name__
        assert result.data.get("status") in {"ok", "empty"}, (fn_cls.__name__, result.data.get("status"))
        assert result.metadata.get("providers") == [{"provider": "test.stale", "status": "down", "last_ok_at": None,
                                                     "last_error": "timeout"}], fn_cls.__name__


def test_m1_ipo_unknown_status_is_not_guessed_as_upcoming():
    fn = ipo_mod.IPOFunction(FunctionDeps())
    fn._awareness = Routes({"/calendar/corporate": [
        {"id": "p1", "type": "ipo", "symbol": "PSTP", "company": "Postponed Co", "date": _day(20),
         "status": "postponed", "fields": {}, "sources": []},
        {"id": "p2", "type": "ipo", "symbol": "SOON", "company": "Soon Inc", "date": _day(20),
         "status": "scheduled", "fields": {}, "sources": []},
    ]})
    result = _run(fn.execute(days_back=30, days_ahead=60))
    assert [r["symbol"] for r in result.data["sections"]["upcoming"]] == ["SOON"]
    assert all(r["symbol"] != "PSTP" for rows in result.data["sections"].values() for r in rows)
    assert any("postponed" in w for w in result.warnings)
