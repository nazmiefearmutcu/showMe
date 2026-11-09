"""PEOP live search: candidate cap disclosure and relevance filter (wc1-g30).

Offline: the Wikipedia/Wikidata HTTP helper is faked; no network is used.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from showme.engine.functions.comm import peop as peop_mod
from showme.engine.services import people_directory as pd
from showme.engine.services import people_search as ps
from tests.test_peop_people_search import FakeWiki, _summary


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    ps.clear_cache()


def _person_corpus(names: list[str]) -> FakeWiki:
    hits = [{"title": name, "wordcount": 3000 - i} for i, name in enumerate(names)]
    summaries = {
        name: _summary(
            name,
            qid=None,
            description="American businessman",
            extract=f"{name} is an American businessman.",
        )
        for name in names
    }
    return FakeWiki(search_hits=hits, summaries=summaries, entities={})


def _install(monkeypatch: pytest.MonkeyPatch, fake: FakeWiki) -> None:
    """Honour ``srlimit`` the way Wikipedia does, so the candidate cap is real."""
    from urllib.parse import parse_qs, urlparse

    def _http(url: str, timeout: float) -> dict[str, Any]:
        if "srlimit" in url:
            limit = int(parse_qs(urlparse(url).query)["srlimit"][0])
            return {"query": {"search": fake.search_hits[:limit]}}
        return fake(url, timeout)

    monkeypatch.setattr(ps, "_http_get_json", _http)
    monkeypatch.setattr(pd, "search", lambda query, limit=25: [])


def test_candidate_cap_is_disclosed_in_the_result(monkeypatch: pytest.MonkeyPatch) -> None:
    names = [f"Person Number{i}" for i in range(12)]
    _install(monkeypatch, _person_corpus(names))
    result = ps.search_people("person", limit=25)

    assert result["candidate_cap"] == ps.MAX_CANDIDATES
    assert result["candidates_scanned"] == ps.MAX_CANDIDATES
    assert len(result["items"]) <= ps.MAX_CANDIDATES


def test_function_warns_when_limit_exceeds_candidate_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    names = [f"Person Number{i}" for i in range(12)]
    _install(monkeypatch, _person_corpus(names))
    result = _run(peop_mod.PEOPFunction().execute(None, action="search", query="person", limit=25))

    assert result.data["status"] == "ok"
    assert result.data["candidate_cap"] == ps.MAX_CANDIDATES
    assert result.data["candidates_scanned"] == ps.MAX_CANDIDATES
    assert any(str(ps.MAX_CANDIDATES) in w and "candidate" in w.lower() for w in result.warnings), result.warnings


def test_rows_with_no_query_token_match_are_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    names = ["Tim Cook", "Bernard McGuirk"]
    _install(monkeypatch, _person_corpus(names))
    result = ps.search_people("tim cook", limit=25)

    names_out = [row["full_name"] for row in result["items"]]
    assert "Tim Cook" in names_out
    assert "Bernard McGuirk" not in names_out, names_out
    assert all(row["match_score"] > 0 for row in result["items"])
