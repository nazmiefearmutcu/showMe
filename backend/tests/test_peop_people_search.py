"""PEOP live people search — Wikipedia/Wikidata mapping + honesty contract.

Pins the keyless live search behind the PEOP pane:

* candidate discovery hits ``list=search`` with a bounded ``srlimit``;
* summaries map into the pane row schema (name / role / company /
  description / summary / nationality / profile_url) with Wikidata
  ``P39``/``P106``/``P108``/``P27`` enrichment;
* person filtering drops non-humans (P31 != Q5) and disambiguation pages,
  with the description heuristic as the disclosed fallback for pages that
  have no Wikidata claims;
* provider failures surface as ``ok=False`` with a reason (never rows) and
  the PEOP function routes that to ``status='provider_unavailable'``;
* the in-process cache absorbs repeat searches without re-hitting HTTP.

Every test fakes ``people_search._http_get_json`` so the suite is offline
and fast; the live throttle (1 req/s) is a module constant pinned here.
"""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from showme.engine.functions.comm import peop as peop_mod
from showme.engine.services import people_directory as pd
from showme.engine.services import people_search as ps

_SUMMARY_BASE = "https://en.wikipedia.org/api/rest_v1/page/summary/"


def _run(coro):
    return asyncio.run(coro)


def _summary(
    title: str,
    *,
    qid: str | None,
    description: str,
    extract: str,
    page_type: str = "standard",
    timestamp: str = "2026-09-11T16:51:37Z",
) -> dict[str, Any]:
    page = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
    return {
        "type": page_type,
        "title": title,
        "description": description,
        "extract": extract,
        "wikibase_item": qid,
        "timestamp": timestamp,
        "content_urls": {"desktop": {"page": page}},
        "thumbnail": {"source": f"https://upload.wikimedia.org/{title.replace(' ', '_')}.jpg"},
    }


class FakeWiki:
    """Routes faked HTTP by URL and counts calls per endpoint family."""

    def __init__(
        self,
        *,
        search_hits: list[dict[str, Any]],
        summaries: dict[str, dict[str, Any]],
        entities: dict[str, dict[str, Any]] | None = None,
        labels: dict[str, str] | None = None,
        fail_search: bool = False,
    ) -> None:
        self.search_hits = search_hits
        self.summaries = summaries
        self.entities = entities or {}
        self.labels = labels or {}
        self.fail_search = fail_search
        self.calls: list[str] = []
        self.search_query: dict[str, list[str]] = {}

    def __call__(self, url: str, timeout: float) -> dict[str, Any]:
        self.calls.append(url)
        query = parse_qs(urlparse(url).query)
        if url.startswith("https://en.wikipedia.org/w/api.php"):
            self.search_query = query
            if self.fail_search:
                raise RuntimeError("wikipedia 503 from api.php")
            return {"query": {"search": self.search_hits}}
        if url.startswith(_SUMMARY_BASE):
            title = unquote(url[len(_SUMMARY_BASE):]).replace("_", " ")
            payload = self.summaries.get(title)
            if payload is None:
                raise RuntimeError(f"http 404 from summary/{title}")
            return payload
        if url.startswith("https://www.wikidata.org/w/api.php"):
            ids = (query.get("ids") or [""])[0].split("|")
            props = (query.get("props") or [""])[0]
            if "claims" in props:
                return {
                    "entities": {
                        qid: self.entities[qid]
                        for qid in ids
                        if qid in self.entities
                    }
                }
            return {
                "entities": {
                    qid: {"labels": {"en": {"value": self.labels[qid]}}}
                    for qid in ids
                    if qid in self.labels
                }
            }
        raise AssertionError(f"unexpected URL: {url}")

    @property
    def summary_titles(self) -> list[str]:
        return [
            unquote(url[len(_SUMMARY_BASE):]).replace("_", " ")
            for url in self.calls
            if url.startswith(_SUMMARY_BASE)
        ]


def _jensen_corpus() -> FakeWiki:
    hits = [
        {"title": "Jensen", "wordcount": 198},
        {"title": "Jensen (gamer)", "wordcount": 1463},
        {"title": "Jensen Huang", "wordcount": 5703},
        {"title": "Jensen Interceptor", "wordcount": 1551},
        {"title": "Jensen Ackles", "wordcount": 3319},
    ]
    summaries = {
        "Jensen": _summary(
            "Jensen",
            qid="Q1661418",
            description="Topics referred to by the same term",
            extract="Jensen may refer to:",
            page_type="disambiguation",
        ),
        "Jensen (gamer)": _summary(
            "Jensen (gamer)",
            qid="Q22278396",
            description="Danish professional League of Legends player",
            extract="Nicolaj Jensen is a Danish former professional League of Legends player.",
        ),
        "Jensen Huang": _summary(
            "Jensen Huang",
            qid="Q305177",
            description="American entrepreneur and businessman; founder and CEO of Nvidia",
            extract=(
                "Jen-Hsun \"Jensen\" Huang is a Taiwanese and American business executive "
                "and electrical engineer who is the founder, president, and CEO of Nvidia."
            ),
        ),
        "Jensen Interceptor": _summary(
            "Jensen Interceptor",
            qid="Q1687448",
            description="British grand touring car made 1966-1976",
            extract="The Jensen Interceptor is a grand touring car.",
        ),
        "Jensen Ackles": _summary(
            "Jensen Ackles",
            qid="Q193513",
            description="American actor",
            extract="Jensen Ross Ackles is an American actor and musician.",
        ),
    }
    entities = {
        "Q1661418": {"claims": {"P31": [_claim("Q4167410")]}, "labels": {"en": {"value": "Jensen"}}},
        "Q22278396": {"claims": {"P31": [_claim("Q5")], "P106": [_claim("Q4379701")]}, "labels": {"en": {"value": "Nicolaj Jensen"}}},
        "Q305177": {
            "claims": {
                "P31": [_claim("Q5")],
                "P39": [_claim("Q484876")],
                "P106": [_claim("Q131524"), _claim("Q81096")],
                "P108": [_claim("Q182477")],
                "P27": [_claim("Q865"), _claim("Q30")],
            },
            "labels": {"en": {"value": "Jensen Huang"}},
        },
        "Q1687448": {"claims": {"P31": [_claim("Q3231690")]}, "labels": {"en": {"value": "Jensen Interceptor"}}},
        "Q193513": {"claims": {"P31": [_claim("Q5")], "P106": [_claim("Q33999")]}, "labels": {"en": {"value": "Jensen Ackles"}}},
    }
    labels = {
        "Q484876": "chief executive officer",
        "Q131524": "entrepreneur",
        "Q81096": "engineer",
        "Q182477": "Nvidia",
        "Q865": "Taiwan",
        "Q30": "United States",
        "Q33999": "actor",
        "Q4379701": "professional gamer",
    }
    return FakeWiki(search_hits=hits, summaries=summaries, entities=entities, labels=labels)


def _claim(qid: str) -> dict[str, Any]:
    return {
        "rank": "normal",
        "mainsnak": {"datavalue": {"value": {"id": qid}}},
    }


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    ps.clear_cache()


def _install(monkeypatch: pytest.MonkeyPatch, fake: FakeWiki) -> FakeWiki:
    monkeypatch.setattr(ps, "_http_get_json", fake)
    return fake


# ---------------------------------------------------------------------------
# Search → summary → map
# ---------------------------------------------------------------------------


def test_live_search_maps_jensen_huang_with_wikidata_enrichment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install(monkeypatch, _jensen_corpus())
    result = ps.search_people("jensen", limit=25)

    assert result["ok"] is True
    names = [row["full_name"] for row in result["items"]]
    # Non-humans (car, disambiguation) are filtered; the persons survive.
    assert "Jensen Huang" in names
    assert "Jensen Interceptor" not in names
    assert "Jensen" not in names
    # Prominence ranking puts the NVIDIA CEO first for "jensen".
    assert names[0] == "Jensen Huang"
    assert result["sources"] == ["wikipedia", "wikidata"]

    huang = result["items"][0]
    assert huang["role"] == "chief executive officer"
    assert huang["company"] == "Nvidia"
    assert huang["company_source"] == "wikidata:P108"
    assert huang["nationality"] == "Taiwan / United States"
    assert huang["wikidata_id"] == "Q305177"
    assert huang["profile_url"] == "https://en.wikipedia.org/wiki/Jensen_Huang"
    assert huang["source"] == "wikipedia"
    assert huang["source_url"] == huang["profile_url"]
    assert huang["contact_status"] == "public_profile_only"
    assert "CEO of Nvidia" in huang["description"]
    assert "founder, president, and CEO of Nvidia" in huang["bio"]
    assert huang["source_date"] == "2026-09-11T16:51:37Z"

    # The candidate search itself was bounded (candidate cap).
    assert fake.search_query["srsearch"] == ["jensen"]
    assert int(fake.search_query["srlimit"][0]) <= ps.MAX_CANDIDATES
    # Bounded candidate fan-out — every hit got its summary attempt.
    assert len(fake.summary_titles) == 5


def test_description_heuristic_keeps_pages_without_wikidata_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hits = [
        {"title": "Jane Actor", "wordcount": 2000},
        {"title": "Grand Tourer", "wordcount": 1800},
    ]
    summaries = {
        "Jane Actor": _summary(
            "Jane Actor",
            qid=None,
            description="American actress and director",
            extract="Jane Actor is an American actress and director.",
        ),
        "Grand Tourer": _summary(
            "Grand Tourer",
            qid=None,
            description="British grand touring car made 1966-1976",
            extract="The Grand Tourer is a grand touring car.",
        ),
    }
    fake = FakeWiki(search_hits=hits, summaries=summaries, entities={})
    _install(monkeypatch, fake)
    result = ps.search_people("jane", limit=5)

    assert result["ok"] is True
    assert [row["full_name"] for row in result["items"]] == ["Jane Actor"]
    assert result["sources"] == ["wikipedia"]


def test_company_falls_back_to_tagged_summary_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hits = [{"title": "Pat Founder", "wordcount": 900}]
    summaries = {
        "Pat Founder": _summary(
            "Pat Founder",
            qid="Q1",
            description="American business executive; founder and CEO of Acme Corp",
            extract="Pat Founder is the founder and CEO of Acme Corp.",
        )
    }
    entities = {
        "Q1": {
            "claims": {"P31": [_claim("Q5")], "P106": [_claim("Q2")]},
            "labels": {"en": {"value": "Pat Founder"}},
        }
    }
    fake = FakeWiki(
        search_hits=hits,
        summaries=summaries,
        entities=entities,
        labels={"Q2": "business executive"},
    )
    _install(monkeypatch, fake)
    result = ps.search_people("pat", limit=5)

    row = result["items"][0]
    assert row["role"] == "business executive"
    assert row["company"] == "Acme Corp"
    assert row["company_source"] == "summary_pattern"


# ---------------------------------------------------------------------------
# Honesty: provider failure + cache
# ---------------------------------------------------------------------------


def test_provider_failure_returns_ok_false_with_reason_never_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install(monkeypatch, FakeWiki(search_hits=[], summaries={}, fail_search=True))
    result = ps.search_people("jensen", limit=25)

    assert result["ok"] is False
    assert result["items"] == []
    assert "wikipedia" in result["reason"]
    assert "503" in result["reason"]
    assert fake is not None


def test_cache_absorbs_repeat_searches(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, _jensen_corpus())
    first = ps.search_people("jensen", limit=25)
    calls_after_first = list(fake.calls)
    second = ps.search_people("jensen", limit=25)

    assert first["items"] == second["items"]
    assert fake.calls == calls_after_first, "cache hit must not re-hit HTTP"


def test_failure_cache_short_circuits_repeat_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install(monkeypatch, FakeWiki(search_hits=[], summaries={}, fail_search=True))
    ps.search_people("jensen", limit=25)
    calls_after_first = list(fake.calls)
    result = ps.search_people("jensen", limit=25)
    assert result["ok"] is False
    assert fake.calls == calls_after_first


def test_politeness_and_cap_constants() -> None:
    assert ps.MIN_REQUEST_INTERVAL_SECONDS == 1.0
    assert 4 <= ps.MAX_CANDIDATES <= 20
    assert ps.DEFAULT_CACHE_TTL_SECONDS >= 60


def test_short_query_never_hits_the_wire(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, _jensen_corpus())
    assert ps.search_people("x", limit=25)["items"] == []
    assert ps.search_people("", limit=25)["items"] == []
    assert fake.calls == []


# ---------------------------------------------------------------------------
# PEOP function wiring
# ---------------------------------------------------------------------------


def test_function_routes_live_rows_with_wikipedia_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, _jensen_corpus())
    monkeypatch.setattr(pd, "search", lambda query, limit=25: [])
    fn = peop_mod.PEOPFunction()
    result = _run(fn.execute(None, action="search", query="jensen", limit=25))

    assert result.data["source_mode"] == "wikipedia_live"
    assert result.data["status"] == "ok"
    assert result.data["provider_error"] is None
    assert result.sources == ["wikipedia", "wikidata"]
    assert result.data["items"][0]["full_name"] == "Jensen Huang"
    assert result.data["items"][0]["company"] == "Nvidia"


def test_function_reports_provider_unavailable_when_live_fails_without_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, FakeWiki(search_hits=[], summaries={}, fail_search=True))
    monkeypatch.setattr(pd, "search", lambda query, limit=25: [])
    fn = peop_mod.PEOPFunction()
    result = _run(fn.execute(None, action="search", query="jensen", limit=25))

    assert result.data["status"] == "provider_unavailable"
    assert result.data["source_mode"] == "provider_unavailable"
    assert result.data["items"] == []
    assert "wikipedia" in result.data["provider_error"]
    # ``reason`` is what the shared envelope surfaces to the UI.
    assert "wikipedia" in result.data["reason"]
    assert result.sources == []


def test_function_keeps_labelled_reference_fallback_when_live_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, FakeWiki(search_hits=[], summaries={}, fail_search=True))
    monkeypatch.setattr(pd, "search", lambda query, limit=25: [])
    fn = peop_mod.PEOPFunction()
    result = _run(fn.execute(None, action="search", query="tim cook apple", limit=25))

    assert result.data["status"] == "ok"
    assert result.data["source_mode"] == "public_reference"
    assert result.sources == ["people_public_reference"]
    assert all(
        row["contact_status"] == "public_profile_only"
        for row in result.data["items"]
    )
    # The provider failure is still disclosed (warning), never hidden.
    assert result.warnings and "wikipedia" in result.warnings[0]


def test_function_empty_query_still_returns_needs_data_not_fabricated_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pd, "search", lambda query, limit=25: [])
    fake = _install(monkeypatch, _jensen_corpus())
    fn = peop_mod.PEOPFunction()
    result = _run(fn.execute(None, action="search", query="", limit=25))

    assert result.data["status"] == "needs_data"
    assert result.data["items"] == []
    assert fake.calls == []


def test_wikipedia_sources_classify_live_in_the_sanitizer() -> None:
    from showme.server import _classify_source_state

    assert _classify_source_state("wikipedia") == "live"
    assert _classify_source_state("wikidata") == "live"
