"""De-garbage regression tests for BRIEF (news daily research briefing).

BRIEF previously returned a hardcoded ``_brief_template`` with invented bullets
("Market monitor is online and returning continuity coverage.") whenever the
``live`` flag was falsy — and ``live`` was opt-in, so the canned template was the
default happy path. That violated the manifest claim ("No synthetic summaries,
no fabricated quotes").

These tests assert:
  * the default path is LIVE composition (no ``live`` kwarg required);
  * the payload carries status / methodology / field_dictionary / articles;
  * the old fabricated constants never appear;
  * live-network assertions degrade gracefully offline (status in the
    provider_unavailable / empty set, never a fabricated summary).
"""

from __future__ import annotations

import asyncio

import pytest

from showme.engine.functions.news.brief import BRIEFFunction

# Strings from the OLD garbage template that must never appear again.
_FORBIDDEN = (
    "Market monitor is online and returning continuity coverage",
    "Rate, inflation, and liquidity calendar checks are ready",
    "Portfolio and cross-asset risk panels are available without live-provider blocking",
    "Secondary symbol included in the daily scan",
)

_OK_SET = {"ok", "empty", "provider_unavailable"}


def _run(coro):
    return asyncio.run(coro)


def _make() -> BRIEFFunction:
    # BaseFunction(deps=None) — handler falls back to keyless adapters / direct
    # HTTP. READFunction(None) is constructed the same way inside BRIEF.
    return BRIEFFunction(None)


def _payload(result):
    assert hasattr(result, "data"), "FunctionResult missing .data"
    data = result.data
    assert isinstance(data, dict), "BRIEF data must be a dict"
    return data


def test_default_path_is_live_and_well_formed():
    """No live kwarg passed: default must still attempt live composition and
    return a contract-complete payload — never the old canned template."""
    res = _run(_make().execute(watchlist=["AAPL", "MSFT"]))
    data = _payload(res)

    # Contract keys present.
    for key in ("status", "markdown", "articles", "watchlist", "article_count",
                "methodology", "field_dictionary"):
        assert key in data, f"BRIEF payload missing '{key}'"

    assert data["status"] in _OK_SET, f"unexpected status {data['status']!r}"
    assert isinstance(data["methodology"], str) and data["methodology"].strip()
    assert isinstance(data["field_dictionary"], dict) and data["field_dictionary"]
    assert isinstance(data["articles"], list)
    assert data["article_count"] == len(data["articles"]), "count must match array length"
    assert "AAPL" in data["watchlist"] and "MSFT" in data["watchlist"]

    # The fabricated template strings must be gone from markdown.
    md = data["markdown"]
    assert isinstance(md, str) and md.strip()
    for bad in _FORBIDDEN:
        assert bad not in md, f"fabricated template string leaked: {bad!r}"

    # metadata reports live mode.
    assert res.metadata.get("live") is True


def test_live_articles_are_real_with_evidence_links():
    """When the network is available, articles must be real rows with evidence
    URLs (not constants). Offline, assert the honest provider_unavailable shape
    instead — never a fabricated summary."""
    res = _run(_make().execute(watchlist=["AAPL"], limit=10))
    data = _payload(res)

    if data["status"] == "ok":
        assert data["articles"], "status=ok but no articles"
        for art in data["articles"]:
            assert isinstance(art, dict)
            # Real headline text.
            assert str(art.get("title", "")).strip(), "article has empty title"
            # An evidence link (url or link) — the manifest's cite requirement.
            assert (art.get("url") or art.get("link")), "article has no evidence URL"
        # Markdown bullets must carry links.
        assert "http" in data["markdown"].lower()
    else:
        # Offline / all adapters down: honest empty result, not a fabrication.
        assert data["status"] in {"provider_unavailable", "empty"}
        assert data["article_count"] == 0
        assert data["next_actions"], "empty brief must explain itself via next_actions"
        assert "No live watchlist headlines were returned" in data["markdown"]
        for bad in _FORBIDDEN:
            assert bad not in data["markdown"]


def test_live_false_optout_is_honest_not_fabricated():
    """Explicit live=false is an opt-out that returns an honest empty body — it
    must NOT resurrect the old fabricated 'Market monitor is online' template."""
    res = _run(_make().execute(watchlist=["BTCUSDT"], live=False))
    data = _payload(res)

    assert data["status"] == "empty"
    assert data["article_count"] == 0
    assert data["articles"] == []
    for bad in _FORBIDDEN:
        assert bad not in data["markdown"], f"opt-out path leaked fabricated text: {bad!r}"
    assert "live=false" in data["markdown"].lower() or "disabled" in data["markdown"].lower()
    assert data["next_actions"], "opt-out must explain how to enable live composition"


def test_methodology_disavows_llm_fabrication():
    res = _run(_make().execute(watchlist=["AAPL"], live=False))
    method = _payload(res)["methodology"].lower()
    assert "does not call an llm" in method or "not call an llm" in method
    assert "fabricate" in method


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
