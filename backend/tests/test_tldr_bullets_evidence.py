"""TLDR bullets[] must be composed from real evidence rows (TLDR#6).

The manifest promises a 5-bullet array (bullet_text, evidence_links, symbols,
evidence_count) that honours ``bullets`` and ``evidence_per_bullet``, and says no
bullet is ever synthetic. The handler used to return markdown only, ignored both
inputs, and appended a canned "Action items" line that no evidence backs.

Network is patched: quotes, TOP, ECO and the LLM router are replaced with
deterministic answers.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

import showme.engine.agents.llm_router as llm_mod
import showme.engine.functions.macro.eco as eco_mod
import showme.engine.functions.news.top as top_mod
import showme.quotes as quotes_mod
from showme.engine.core.base_function import FunctionDeps, FunctionResult
from showme.engine.functions.news.tldr import TLDRFunction

QUOTES: dict[str, dict[str, Any]] = {
    "NVDA": {"last": 186.64, "change_pct": 2.7753, "source": "yahoo_chart"},
    "MSFT": {"last": 530.61, "change_pct": -0.9927, "source": "yahoo_chart"},
    "AAPL": {"last": 319.97, "change_pct": 0.0840, "source": "yahoo_chart"},
    "TSLA": {"last": None, "change_pct": None, "source": None},
}


def _patch(monkeypatch: pytest.MonkeyPatch, *, top: Any, eco: Any) -> None:
    async def _quote(symbol: str) -> dict[str, Any]:
        row = QUOTES.get(symbol)
        if row is None or row["last"] is None:
            raise RuntimeError(f"no quote for {symbol}")
        return {"symbol": symbol, "last": row["last"], "change_pct": row["change_pct"],
                "previous_close": None, "source": row["source"]}

    def _make(value: Any):
        async def _execute(self, *args: Any, **kwargs: Any) -> Any:
            if isinstance(value, Exception):
                raise value
            return value

        return _execute

    async def _llm_down(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("no llm in test")

    monkeypatch.setattr(quotes_mod, "fetch_quote_snapshot", _quote)
    monkeypatch.setattr(top_mod.TOPFunction, "execute", _make(top))
    monkeypatch.setattr(eco_mod.ECOFunction, "execute", _make(eco))
    monkeypatch.setattr(llm_mod.LLMRouter, "complete", _llm_down)


def _top_with_links() -> FunctionResult:
    items = [
        {"title": "Fed holds rates", "url": "https://example.com/fed"},
        {"title": "Chip rally", "link": "http://example.com/chips"},
        {"title": "Untracked headline without a link"},
    ]
    return FunctionResult(
        code="TOP", instrument=None,
        data={"items": items, "alerts": [], "status": "ok"},
        sources=["rss"],
    )


def _eco_ok() -> FunctionResult:
    events = [{"event": "CPI", "country": "US"}, {"event": "Payrolls", "country": "US"}]
    return FunctionResult(
        code="ECO", instrument=None,
        data={"status": "ok", "events": events, "rows": events},
        sources=["forex_factory"],
    )


def _run(**params: Any) -> FunctionResult:
    base = dict(
        symbols=["NVDA", "MSFT", "AAPL", "TSLA"],
        quote_timeout=2.0, news_timeout=2.0, eco_timeout=2.0, llm_timeout=0.1, timeout=9.0,
    )
    base.update(params)
    return asyncio.run(TLDRFunction(deps=FunctionDeps()).execute(**base))


def test_tldr_returns_bullets_cited_to_real_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, top=_top_with_links(), eco=_eco_ok())
    result = _run()
    data = result.data

    assert data["status"] == "ok"
    assert data["symbols"] == ["NVDA", "MSFT", "AAPL", "TSLA"]
    bullets = data["bullets"]
    assert isinstance(bullets, list) and len(bullets) >= 3, bullets
    for bullet in bullets:
        assert bullet["bullet_text"]
        assert bullet["evidence_count"] >= 1
        assert len(bullet["evidence"]) == bullet["evidence_count"]
        assert all(link.startswith(("http://", "https://")) for link in bullet["evidence_links"])

    texts = [b["bullet_text"] for b in bullets]
    # Movers are signed against the prior-session change the quote carries.
    assert any("NVDA (+2.78%)" in t and "up" in t.lower() for t in texts), texts
    assert any("MSFT (-0.99%)" in t and "down" in t.lower() for t in texts), texts
    # TSLA has no quote: it is reported as missing coverage, never as a 0% mover.
    assert any("TSLA" in t and "no quote" in t for t in texts), texts
    assert not any("TSLA (" in t for t in texts), texts

    news = [b for b in bullets if b["bullet_text"].startswith("News themes")]
    assert news, texts
    assert "https://example.com/fed" in news[0]["evidence_links"]
    assert "http://example.com/chips" in news[0]["evidence_links"]

    calendar = [b for b in bullets if b["bullet_text"].startswith("Calendar items")]
    assert calendar and calendar[0]["evidence_links"] == []
    assert "2 scheduled" in calendar[0]["bullet_text"]


def test_tldr_markdown_drops_boilerplate_action_line(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, top=_top_with_links(), eco=_eco_ok())
    markdown = _run().data["markdown"]
    assert "Action items" not in markdown
    assert "scan ALRT log" not in markdown
    assert "Top movers up:** NVDA (+2.78%)" in markdown


def test_tldr_bullets_input_caps_the_bullet_count(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, top=_top_with_links(), eco=_eco_ok())
    data = _run(bullets=3).data
    assert data["bullet_limit"] == 3
    assert len(data["bullets"]) == 3


def test_tldr_evidence_per_bullet_caps_the_citations(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, top=_top_with_links(), eco=_eco_ok())
    data = _run(evidence_per_bullet=1).data
    assert data["evidence_per_bullet"] == 1
    assert data["bullets"]
    for bullet in data["bullets"]:
        assert bullet["evidence_count"] <= 1
        assert len(bullet["evidence"]) <= 1


def test_tldr_failed_sources_produce_no_bullet_without_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    down_top = FunctionResult(
        code="TOP", instrument=None,
        data={"items": [], "alerts": [], "status": "provider_unavailable", "reason": "rss down"},
        sources=[],
    )
    _patch(monkeypatch, top=down_top, eco=RuntimeError("eco timeout"))
    data = _run(symbols=["NVDA"]).data
    texts = [b["bullet_text"] for b in data["bullets"]]
    assert not any(t.startswith("News themes") for t in texts), texts
    assert not any(t.startswith("Calendar items") for t in texts), texts
    assert any(t.startswith("Top movers up") for t in texts), texts


@pytest.mark.parametrize("raw", [float("inf"), float("-inf"), "inf", "-inf", float("nan"), "nan"])
def test_tldr_non_finite_bullet_inputs_fall_back_to_defaults(
    monkeypatch: pytest.MonkeyPatch, raw: Any
) -> None:
    """Non-finite numbers must fall back to the default instead of raising OverflowError."""
    from showme.engine.functions.news.tldr import _clamp_int

    assert _clamp_int(raw, default=5, low=3, high=8) == 5
    assert _clamp_int(raw, default=2, low=1, high=5) == 2

    _patch(monkeypatch, top=_top_with_links(), eco=_eco_ok())
    data = _run(bullets=raw, evidence_per_bullet=raw).data
    assert data["bullet_limit"] == 5
    assert data["evidence_per_bullet"] == 2
    assert data["bullets"]


def test_tldr_sources_name_only_the_quote_sources_that_answered(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provenance (TLDR#4): sources come from quote_source, never a fixed 'yfinance' label."""
    _patch(monkeypatch, top=_top_with_links(), eco=_eco_ok())
    result = _run()
    assert "yahoo_chart" in result.sources, result.sources
    assert "yfinance" not in result.sources, result.sources


def test_tldr_portfolio_failure_never_substitutes_a_sample_watchlist(monkeypatch: pytest.MonkeyPatch) -> None:
    """TLDR#5: a failing portfolio read yields no symbols, never a fixed sample list."""
    import showme.engine.portfolio.state as state_mod

    class _BrokenPortfolio:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("portfolio down")

    monkeypatch.setattr(state_mod, "PortfolioState", _BrokenPortfolio)
    _patch(monkeypatch, top=_top_with_links(), eco=_eco_ok())
    result = asyncio.run(TLDRFunction(deps=FunctionDeps()).execute(
        quote_timeout=2.0, news_timeout=2.0, eco_timeout=2.0, llm_timeout=0.1, timeout=9.0,
    ))
    assert result.data["symbols"] == []
    assert result.data["watchlist"] == []
    assert result.data["watchlist_source"] == "portfolio_unavailable"
    assert not {"AAPL", "MSFT", "TSLA", "BTCUSDT", "EURUSD", "DGS10"} & set(result.data["symbols"])
    assert any(str(w).startswith("portfolio:") for w in result.metadata.get("provider_errors", []))


def test_tldr_seed_symbols_description_does_not_advertise_a_default_set() -> None:
    """TLDR#5 follow-up: the manifest must not promise a fallback default symbol set.

    The handler returns no symbols (with a portfolio_empty / portfolio_unavailable
    watchlist_source) when there are no holdings, so the seed text must say so.
    """
    from showme.manifest.seeds.tldr_seed import tldr

    spec = tldr  # @manifest() already yields the FunctionManifest object
    symbols_input = next(i for i in spec.inputs if i.name == "symbols")
    text = symbols_input.description.lower()
    assert "fallback" not in text and "default set" not in text, symbols_input.description
    assert "portfolio_empty" in text or "portfolio_unavailable" in text, symbols_input.description
