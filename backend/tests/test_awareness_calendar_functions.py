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
    assert block["next_close_utc"].startswith("2026-11-09T06:30")


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
