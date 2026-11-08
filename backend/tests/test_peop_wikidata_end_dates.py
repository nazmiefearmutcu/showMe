"""PEOP#1 - ended Wikidata claims must not be reported as the current role.

Wikidata Q265852 (Tim Cook) has ``P39 = chief executive officer`` with the
qualifier ``P582 (end time) = 2026-08-31``. PEOP took the first P39 claim as
the current role and ignored the qualifier, so the live result still said
"chief executive officer" in November 2026.

Dates in these fixtures are derived from the wall clock (see ``_day``) so the
suite keeps its meaning on any run date; only the far-past and far-future
anchors are fixed.

These tests drive ``search_people`` with the HTTP layer faked (no network),
the same way the existing PEOP suite does.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from showme.engine.services import people_search as ps


_SUMMARY_BASE = "https://en.wikipedia.org/api/rest_v1/page/summary/"
_CEO = "Q484876"
_CHAIRMAN = "Q1138125"  # executive chairman (test-only label mapping)
_APPLE = "Q312"
_BUSINESSPERSON = "Q43845"


def _day(offset_days: int) -> str:
    """ISO date ``offset_days`` from today (UTC); negative means in the past."""
    return (datetime.now(timezone.utc) + timedelta(days=offset_days)).date().isoformat()


def _qualified_claim(qid: str, *, start: str | None = None, end: str | None = None,
                     rank: str = "normal") -> dict[str, Any]:
    qualifiers: dict[str, list[dict[str, Any]]] = {}
    if start is not None:
        qualifiers["P580"] = [_time_snak("P580", start)]
    if end is not None:
        qualifiers["P582"] = [_time_snak("P582", end)]
    claim: dict[str, Any] = {
        "rank": rank,
        "mainsnak": {"datavalue": {"value": {"id": qid}}},
    }
    if qualifiers:
        claim["qualifiers"] = qualifiers
    return claim


def _time_snak(prop: str, iso_date: str) -> dict[str, Any]:
    # Wikidata time values look like "+2026-08-31T00:00:00Z" with a precision code.
    return {
        "snaktype": "value",
        "property": prop,
        "datavalue": {
            "type": "time",
            "value": {"time": f"+{iso_date}T00:00:00Z", "precision": 11, "calendarmodel": "http://www.wikidata.org/entity/Q1985727"},
        },
    }


def _somevalue_snak(prop: str) -> dict[str, Any]:
    """Wikidata 'unknown value': the qualifier exists but its date is not known."""
    return {"snaktype": "somevalue", "property": prop}


def _novalue_snak(prop: str) -> dict[str, Any]:
    """Wikidata 'no value': the qualifier is explicitly absent."""
    return {"snaktype": "novalue", "property": prop}


def _plain_claim(qid: str) -> dict[str, Any]:
    return {"rank": "normal", "mainsnak": {"datavalue": {"value": {"id": qid}}}}


class _FakeWiki:
    def __init__(
        self,
        *,
        title: str,
        qid: str,
        entity: dict[str, Any],
        labels: dict[str, str],
        extract: str | None = None,
    ) -> None:
        self._title = title
        self._qid = qid
        self._entity = entity
        self._labels = labels
        self._extract = extract or f"{title} is an American business executive."

    def __call__(self, url: str, timeout: float) -> dict[str, Any]:  # noqa: ARG002
        if url.startswith("https://en.wikipedia.org/w/api.php"):
            return {"query": {"search": [{"title": self._title, "wordcount": 9000}]}}
        if url.startswith(_SUMMARY_BASE):
            return {
                "type": "standard",
                "title": self._title,
                "description": "American business executive",
                "extract": self._extract,
                "wikibase_item": self._qid,
                "timestamp": "2026-11-01T00:00:00Z",
                "content_urls": {"desktop": {"page": f"https://en.wikipedia.org/wiki/{self._title.replace(' ', '_')}"}},
            }
        if url.startswith("https://www.wikidata.org/w/api.php"):
            from urllib.parse import parse_qs, urlparse

            query = parse_qs(urlparse(url).query)
            ids = (query.get("ids") or [""])[0].split("|")
            props = (query.get("props") or [""])[0]
            if "claims" in props:
                return {"entities": {q: self._entity for q in ids if q == self._qid}}
            return {
                "entities": {
                    q: {"labels": {"en": {"value": self._labels[q]}}}
                    for q in ids
                    if q in self._labels
                }
            }
        raise AssertionError(f"unexpected URL: {url}")


def _install(monkeypatch: pytest.MonkeyPatch, fake: _FakeWiki) -> None:
    monkeypatch.setattr(ps, "_http_get_json", fake)
    ps.clear_cache()


def _timcook_entity(p39: list[dict[str, Any]], p108: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "claims": {
            "P31": [_plain_claim("Q5")],
            "P39": p39,
            "P108": p108 if p108 is not None else [_plain_claim(_APPLE)],
            "P106": [_plain_claim(_BUSINESSPERSON)],
        },
        "labels": {"en": {"value": "Tim Cook"}},
    }


_LABELS = {
    _CEO: "chief executive officer",
    _CHAIRMAN: "executive chairman",
    _APPLE: "Apple Inc.",
    _BUSINESSPERSON: "businessperson",
}


def test_ended_ceo_claim_is_not_reported_as_current_role(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tim Cook's CEO claim ended 2026-08-31; PEOP must not call it his current role."""
    entity = _timcook_entity(
        p39=[_qualified_claim(_CEO, start="2011-08-24", end=_day(-70))],
    )
    _install(monkeypatch, _FakeWiki(title="Tim Cook", qid="Q265852", entity=entity, labels=_LABELS))

    result = ps.search_people("Tim Cook", limit=5)

    assert result["ok"] is True
    item = result["items"][0]
    assert item["role"] != "chief executive officer", item
    assert item["role"] == "businessperson", item


def test_ended_employer_is_not_reported_as_current_company(monkeypatch: pytest.MonkeyPatch) -> None:
    entity = _timcook_entity(
        p39=[],
        p108=[_qualified_claim(_APPLE, start="1998-01-01", end="2020-01-01")],
    )
    _install(monkeypatch, _FakeWiki(title="Tim Cook", qid="Q265852", entity=entity, labels=_LABELS))

    item = ps.search_people("Tim Cook", limit=5)["items"][0]

    assert item["company"] != "Apple Inc.", item
    assert item["company_source"] != "wikidata:P108", item


def test_ended_employer_is_not_revived_from_summary_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """An ended P108 claim must not be replaced by a summary-text match that names it as current.

    The summary still says "chief executive officer of Apple Inc." (the former role). With
    the only employer claim ended, company must stay empty rather than read that text.
    """
    entity = _timcook_entity(
        p39=[],
        p108=[_qualified_claim(_APPLE, start="1998-01-01", end=_day(-70))],
    )
    _install(
        monkeypatch,
        _FakeWiki(
            title="Tim Cook", qid="Q265852", entity=entity, labels=_LABELS,
            extract="Tim Cook is the chief executive officer of Apple Inc.",
        ),
    )

    item = ps.search_people("Tim Cook", limit=5)["items"][0]

    assert item["company"] is None, item
    assert item["company_source"] is None, item


def test_current_role_with_ended_predecessor_picks_the_current_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    """When an ended claim and a current claim coexist, the current one is the role."""
    entity = _timcook_entity(
        p39=[
            _qualified_claim(_CEO, start="2011-08-24", end=_day(-70)),
            _qualified_claim(_CHAIRMAN, start=_day(-60)),
        ],
    )
    _install(monkeypatch, _FakeWiki(title="Tim Cook", qid="Q265852", entity=entity, labels=_LABELS))

    item = ps.search_people("Tim Cook", limit=5)["items"][0]

    assert item["role"] == "executive chairman", item


def test_claim_without_end_qualifier_is_still_current(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression guard: an unqualified / open-ended current claim keeps working."""
    entity = _timcook_entity(
        p39=[_qualified_claim(_CEO, start="2011-08-24")],
    )
    _install(monkeypatch, _FakeWiki(title="Tim Cook", qid="Q265852", entity=entity, labels=_LABELS))

    item = ps.search_people("Tim Cook", limit=5)["items"][0]

    assert item["role"] == "chief executive officer", item
    assert item["company"] == "Apple Inc."


def test_novalue_end_qualifier_means_no_end_and_stays_current(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression guard: P582 'no value' asserts there is no end, so the claim is current."""
    claim = _qualified_claim(_CEO, start="2011-08-24")
    claim["qualifiers"]["P582"] = [_novalue_snak("P582")]
    entity = _timcook_entity(p39=[claim])
    _install(monkeypatch, _FakeWiki(title="Tim Cook", qid="Q265852", entity=entity, labels=_LABELS))

    item = ps.search_people("Tim Cook", limit=5)["items"][0]

    assert item["role"] == "chief executive officer", item


def test_claim_with_unknown_end_time_is_not_current(monkeypatch: pytest.MonkeyPatch) -> None:
    """P582 'unknown value' says the claim ended on a date nobody recorded: not provably current."""
    claim = _qualified_claim(_CEO, start="2011-08-24")
    claim["qualifiers"]["P582"] = [_somevalue_snak("P582")]
    entity = _timcook_entity(p39=[claim])
    _install(monkeypatch, _FakeWiki(title="Tim Cook", qid="Q265852", entity=entity, labels=_LABELS))

    item = ps.search_people("Tim Cook", limit=5)["items"][0]

    assert item["role"] != "chief executive officer", item
    assert item["role"] == "businessperson", item


def test_claim_with_unknown_start_time_is_not_current(monkeypatch: pytest.MonkeyPatch) -> None:
    """P580 'unknown value' means the start is not provably in the past: not provably current."""
    claim = _qualified_claim(_CHAIRMAN)
    claim["qualifiers"] = {"P580": [_somevalue_snak("P580")]}
    entity = _timcook_entity(p39=[claim])
    _install(monkeypatch, _FakeWiki(title="Tim Cook", qid="Q265852", entity=entity, labels=_LABELS))

    item = ps.search_people("Tim Cook", limit=5)["items"][0]

    assert item["role"] != "executive chairman", item


def test_claim_starting_in_the_future_is_not_current(monkeypatch: pytest.MonkeyPatch) -> None:
    entity = _timcook_entity(
        p39=[_qualified_claim(_CHAIRMAN, start="2099-01-01")],
    )
    _install(monkeypatch, _FakeWiki(title="Tim Cook", qid="Q265852", entity=entity, labels=_LABELS))

    item = ps.search_people("Tim Cook", limit=5)["items"][0]

    assert item["role"] != "executive chairman", item


def _this_year() -> int:
    return datetime.now(timezone.utc).year


def test_year_precision_end_in_current_year_is_not_current(monkeypatch: pytest.MonkeyPatch) -> None:
    """P582 '+YYYY-00-00' (month and day unknown) in the current year: the claim ended this year.

    The earliest possible end (1 January) has already passed, so the claim is
    ended and must not be reported as the current role.
    """
    claim = _qualified_claim(_CEO, start="2011-08-24", end=f"{_this_year():04d}-00-00")
    entity = _timcook_entity(p39=[claim])
    _install(monkeypatch, _FakeWiki(title="Tim Cook", qid="Q265852", entity=entity, labels=_LABELS))

    item = ps.search_people("Tim Cook", limit=5)["items"][0]

    assert item["role"] != "chief executive officer", item
    assert item["role"] == "businessperson", item


def test_month_precision_end_in_current_month_is_not_current(monkeypatch: pytest.MonkeyPatch) -> None:
    """P582 '+YYYY-MM-00' (day unknown) in the current month: the earliest end (the 1st) has passed."""
    now = datetime.now(timezone.utc)
    claim = _qualified_claim(_CEO, start="2011-08-24", end=f"{now.year:04d}-{now.month:02d}-00")
    entity = _timcook_entity(p39=[claim])
    _install(monkeypatch, _FakeWiki(title="Tim Cook", qid="Q265852", entity=entity, labels=_LABELS))

    item = ps.search_people("Tim Cook", limit=5)["items"][0]

    assert item["role"] != "chief executive officer", item


def test_year_precision_end_in_past_year_is_not_current(monkeypatch: pytest.MonkeyPatch) -> None:
    claim = _qualified_claim(_CEO, start="2011-08-24", end="2020-00-00")
    entity = _timcook_entity(p39=[claim])
    _install(monkeypatch, _FakeWiki(title="Tim Cook", qid="Q265852", entity=entity, labels=_LABELS))

    item = ps.search_people("Tim Cook", limit=5)["items"][0]

    assert item["role"] != "chief executive officer", item


def test_year_precision_start_in_future_year_is_not_current(monkeypatch: pytest.MonkeyPatch) -> None:
    """P580 '+YYYY-00-00' in the next year: even the latest possible start is still ahead."""
    claim = _qualified_claim(_CHAIRMAN, start=f"{_this_year() + 1:04d}-00-00")
    entity = _timcook_entity(p39=[claim])
    _install(monkeypatch, _FakeWiki(title="Tim Cook", qid="Q265852", entity=entity, labels=_LABELS))

    item = ps.search_people("Tim Cook", limit=5)["items"][0]

    assert item["role"] != "executive chairman", item


def test_year_precision_start_in_past_year_is_current(monkeypatch: pytest.MonkeyPatch) -> None:
    """P580 '+2015-00-00': the latest possible start (31 December 2015) has passed, so the claim is current."""
    claim = _qualified_claim(_CHAIRMAN, start="2015-00-00")
    entity = _timcook_entity(p39=[claim])
    _install(monkeypatch, _FakeWiki(title="Tim Cook", qid="Q265852", entity=entity, labels=_LABELS))

    item = ps.search_people("Tim Cook", limit=5)["items"][0]

    assert item["role"] == "executive chairman", item


def test_uncertain_boundary_parse_direction() -> None:
    """Uncertain end takes the earliest date; uncertain start takes the latest date."""
    end = ps._parse_wikidata_time("+2026-00-00T00:00:00Z", end=True)
    start = ps._parse_wikidata_time("+2026-00-00T00:00:00Z", end=False)
    assert end == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert start == datetime(2026, 12, 31, tzinfo=timezone.utc)
    end_day = ps._parse_wikidata_time("+2026-11-00T00:00:00Z", end=True)
    start_day = ps._parse_wikidata_time("+2026-11-00T00:00:00Z", end=False)
    assert end_day == datetime(2026, 11, 1, tzinfo=timezone.utc)
    assert start_day == datetime(2026, 11, 30, tzinfo=timezone.utc)
