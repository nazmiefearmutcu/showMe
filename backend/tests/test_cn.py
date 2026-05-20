"""Regression tests for the CN (Company News) function.

The most important test here is `_prefer_direct_symbol_matches`: it used to
have a `return direct if ... else direct` bug that silently dropped
non-direct-match items whenever the direct-match count was below `min_rows`,
producing the user-visible "news unavailable" placeholder in CN even though
RSS had returned plenty of broad-market headlines.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.functions.news.cn import (  # noqa: E402
    _format_unavailable_reason,
    _prefer_direct_symbol_matches,
)


def test_prefer_direct_symbol_matches_returns_direct_when_enough() -> None:
    items = [
        {"title": "Tesla earnings beat", "relevance_score": 22, "matched_terms": ["TSLA"]},
        {"title": "TSLA recalls 50k vehicles", "relevance_score": 22, "matched_terms": ["TSLA"]},
        {"title": "Tesla CEO speech", "relevance_score": 22, "matched_terms": ["Tesla"]},
        {"title": "Market roundup", "relevance_score": 0, "matched_terms": []},
    ]
    result = _prefer_direct_symbol_matches(items, min_rows=3)
    assert len(result) == 3
    assert all(item.get("matched_terms") for item in result)


def test_prefer_direct_symbol_matches_falls_back_when_too_few_direct() -> None:
    """The regression: when direct matches < min_rows, we must keep broad
    items rather than silently dropping them.
    """
    direct_hit = {"title": "TSLA earnings", "relevance_score": 22, "matched_terms": ["TSLA"]}
    broad_a = {"title": "EV market update", "relevance_score": 0, "matched_terms": []}
    broad_b = {"title": "Auto sector roundup", "relevance_score": 0, "matched_terms": []}
    items = [direct_hit, broad_a, broad_b]

    result = _prefer_direct_symbol_matches(items, min_rows=3)

    assert len(result) == 3
    assert result[0] is direct_hit  # direct match still surfaces first
    assert broad_a in result and broad_b in result


def test_prefer_direct_symbol_matches_excludes_stale_for_alert() -> None:
    stale = {
        "title": "TSLA news",
        "relevance_score": 22,
        "matched_terms": ["TSLA"],
        "stale_for_alert": True,
    }
    fresh = {"title": "TSLA news", "relevance_score": 22, "matched_terms": ["TSLA"]}
    extra = {"title": "Broad market", "relevance_score": 0, "matched_terms": []}

    result = _prefer_direct_symbol_matches([stale, fresh, extra], min_rows=3)

    assert fresh in result
    # Stale rows are not direct matches but must still be reachable via the
    # fallback top-up so we never lose data.
    assert stale in result
    assert extra in result


def test_prefer_direct_symbol_matches_empty_input() -> None:
    assert _prefer_direct_symbol_matches([], min_rows=3) == []


def test_format_unavailable_reason_includes_sources_and_warnings() -> None:
    reason = _format_unavailable_reason(
        base="No headlines.",
        sources=["rss", "finnhub_news"],
        warnings=["finnhub_news: 429 Too Many Requests"],
    )
    assert "rss" in reason
    assert "finnhub_news" in reason
    assert "429" in reason
    assert reason.startswith("No headlines.")


def test_format_unavailable_reason_truncates_long_warning_list() -> None:
    warnings = [f"src{i}: boom" for i in range(6)]
    reason = _format_unavailable_reason(base="x", sources=[], warnings=warnings)
    assert "…" in reason
    assert reason.count("boom") == 3
