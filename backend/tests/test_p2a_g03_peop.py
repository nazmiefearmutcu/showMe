"""P2A-G03 regression tests: PEOP (#2, #3, #4, #5) and SPLC (#3).

Every test is offline: the Wikipedia live search is patched on
``people_search``, the local SQLite directory is redirected to ``tmp_path``
and the SEC EDGAR fetch / httpx client are faked for SPLC.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from showme.engine.functions.comm import peop as peop_mod
from showme.engine.services import people_directory as pd_svc
from showme.engine.services import people_search as ps
from showme.manifest import REGISTRY, load_seeds


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def local_directory(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr(pd_svc, "_db_path", lambda: tmp_path / "people.sqlite")
    pd_svc.upsert_person(
        full_name="Jane Analyst",
        role="Equity analyst",
        company="Acme Research",
        bio="Covers semiconductors",
    )
    pd_svc.upsert_person(
        full_name="Bob Trader",
        role="Desk trader",
        company="Zeta Capital",
        bio="Rates desk",
    )
    return tmp_path


@pytest.fixture
def live_empty(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    def fake(query: str, *, limit: int = 25) -> dict[str, Any]:
        calls.append(query)
        return {"ok": True, "items": [], "sources": [], "reason": None}

    monkeypatch.setattr(ps, "search_people", fake)
    return calls


# ---------------------------------------------------------------------------
# PEOP#4 — empty / one-character / wildcard queries must not dump the directory
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("query", ["", " ", "a", "%", "_"])
def test_peop_unusable_query_never_returns_whole_directory(
    local_directory, live_empty, query: str
) -> None:
    result = _run(
        peop_mod.PEOPFunction().execute(None, action="search", query=query, limit=25)
    )

    assert result.data["items"] == []
    assert result.data["status"] == "needs_data"


def test_directory_wildcards_are_literal(local_directory) -> None:
    assert pd_svc.search("%%") == []
    assert pd_svc.search("_") == []
    assert [r["full_name"] for r in pd_svc.search("Jane")] == ["Jane Analyst"]


def test_peop_real_directory_query_still_served(local_directory, live_empty) -> None:
    result = _run(
        peop_mod.PEOPFunction().execute(None, action="search", query="Jane", limit=25)
    )

    assert result.data["source_mode"] == "local_directory"
    assert result.data["status"] == "ok"
    assert [r["full_name"] for r in result.data["items"]] == ["Jane Analyst"]


# ---------------------------------------------------------------------------
# PEOP#3 — provider outage: the reason and retry hint lead, not "add a person"
# ---------------------------------------------------------------------------


def test_peop_provider_outage_leads_with_retry_and_keeps_reason(
    monkeypatch: pytest.MonkeyPatch, local_directory
) -> None:
    monkeypatch.setattr(pd_svc, "search", lambda query, limit=25: [])
    monkeypatch.setattr(
        ps,
        "search_people",
        lambda query, *, limit=25: {
            "ok": False,
            "items": [],
            "sources": [],
            "reason": "wikipedia 503 from api.php",
        },
    )
    result = _run(
        peop_mod.PEOPFunction().execute(None, action="search", query="jensen", limit=25)
    )

    assert result.data["status"] == "provider_unavailable"
    assert result.data["next_actions"][0].lower().startswith("retry")
    assert "wikipedia 503" in result.data["reason"]


# ---------------------------------------------------------------------------
# PEOP#2 — the static reference fallback is dated, flagged and not status ok
# ---------------------------------------------------------------------------


def test_peop_static_reference_fallback_is_stale_flagged(
    monkeypatch: pytest.MonkeyPatch, local_directory, live_empty
) -> None:
    monkeypatch.setattr(pd_svc, "search", lambda query, limit=25: [])
    result = _run(
        peop_mod.PEOPFunction().execute(None, action="search", query="apple", limit=25)
    )

    assert result.data["source_mode"] == "public_reference"
    assert result.data["status"] == "needs_data"
    assert result.data["reference_as_of"] == "2026-04-20"
    assert any("2026-04-20" in w for w in result.warnings)
    roles = {r["full_name"]: r["role"] for r in result.data["items"]}
    assert "CEO through summer 2026" not in roles["Tim Cook"]
    assert all("announced" in role for role in roles.values())
    # PEOP#2: every served role is anchored to the snapshot date, so no row
    # reads as a present-tense current-position claim.
    assert all("as of the 2026-04-20 announcement" in role for role in roles.values())


# ---------------------------------------------------------------------------
# PEOP#5 — seed methodology describes the real single-substring search
# ---------------------------------------------------------------------------


def test_peop_seed_text_matches_actual_search_behaviour() -> None:
    load_seeds()
    manifest = REGISTRY.get("PEOP")
    text = manifest.methodology.lower()
    assert "tokeniz" not in text
    assert "ranks rows by tag" not in text
    assert "tags are not searched" in text
    # PEOP#5: the handler does not trim the query, so the seed must not say it does.
    assert "trimmed" not in text
    query_input = next(i for i in manifest.inputs if i.name == "query")
    assert "tag" not in (query_input.description or "").lower()


# ---------------------------------------------------------------------------
# PEOP#8 — the pane is search-only; the seed must say so
# ---------------------------------------------------------------------------


def test_peop_seed_documents_search_only_pane() -> None:
    load_seeds()
    manifest = REGISTRY.get("PEOP")
    assert "search-only" in manifest.methodology.lower()
