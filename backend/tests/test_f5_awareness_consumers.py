"""F5: the functions that CONSUME Awareness-backed TOP/CN payloads read the new shapes.

No network: every Awareness call goes through ``AwarenessClient`` with an
``httpx.MockTransport``. Covered:

* BRIEF — the watchlist leg is CN per symbol (BTCUSDT -> BTC), the macro leg is
  TOP, Awareness evidence survives on each article, sentiment is never re-scored,
  and the honest state (cached_snapshot, provider_unavailable, partial outage).
* TLDR — reads TOP ``data["rows"]`` and ECO ``data["rows"]``; an unavailable source
  is reported as unavailable, never as a zero count.
* NewsAgent — reads TOP ``data["rows"]`` and passes ``q`` instead of ``query``.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

import httpx

from showme.engine.core.base_agent import AgentTask
from showme.engine.core.base_function import FunctionDeps, FunctionResult
from showme.engine.data_sources.awareness import AwarenessClient
from showme.engine.functions.macro.eco import ECOFunction
from showme.engine.functions.news import awareness_news
from showme.engine.functions.news.brief import BRIEFFunction
from showme.engine.functions.news.top import TOPFunction
from showme.engine.functions.news.tldr import TLDRFunction

Respond = Callable[[str, dict[str, str]], tuple[int, Any]]

OK = [{"provider": "news.gnews", "status": "ok", "last_ok_at": None, "last_error": None, "items_last_ok": 5}]
DOWN = [
    {"provider": "news.feeds", "status": "down", "last_ok_at": None, "last_error": "TimeoutError: ", "items_last_ok": 0},
    {"provider": "news.gnews", "status": "ok", "last_ok_at": None, "last_error": None, "items_last_ok": 5},
]


def _raw(item_id: str, *, symbols: list[str], sentiment: dict[str, Any] | None = None) -> dict[str, Any]:
    """An awareness ``/news`` item, the input of ``mapping.news_row``."""
    row: dict[str, Any] = {
        "id": item_id,
        "title": f"Headline {item_id}",
        "url": f"https://www.cnbc.com/{item_id}",
        "publisher_id": "cnbc",
        "publisher_name": "CNBC",
        "publisher_domain": "cnbc.com",
        "publisher_tier": 2,
        "published_at": "2026-11-08T11:00:00Z",
        "summary": "Summary <b>bold</b>.",
        "symbols": symbols,
        "topics": ["earnings"],
        "importance": 61.0,
        "quality_label": "premium",
        "quality_score": 68.0,
        "quality_reasons": ["tier2:+38"],
        "story_id": f"story-{item_id}",
        "story_size": 2,
        "entities": [],
    }
    if sentiment is not None:
        row["sentiment"] = sentiment
    return row


def _envelope(rows: list[dict[str, Any]], providers: list[dict[str, Any]] | None = None) -> tuple[int, dict[str, Any]]:
    return 200, {
        "data": rows,
        "meta": {
            "generated_at": "2026-11-08T12:00:00Z",
            "count": len(rows),
            "providers": providers if providers is not None else OK,
            "filters": {},
            "notes": [],
            "feed_health": {"ok": 3, "degraded": 0, "down": 0, "never": 0},
        },
    }


def _client(respond: Respond) -> tuple[AwarenessClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        status, body = respond(request.url.path, dict(request.url.params))
        return httpx.Response(status, json=body)

    client = AwarenessClient("http://aw.test", transport=httpx.MockTransport(handler), autostart=False)
    return client, seen


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _route(by_symbol: dict[str, list[dict[str, Any]]], macro: list[dict[str, Any]], providers=None) -> Respond:
    """``symbols=X`` answers ``by_symbol[X]``; the TOP call (no symbols param) answers ``macro``."""

    def respond(path: str, params: dict[str, str]) -> tuple[int, Any]:
        assert path == "/v1/markets/news", path
        symbols = params.get("symbols")
        rows = by_symbol.get(symbols, []) if symbols else macro
        return _envelope(rows, providers=providers)

    return respond


def _unreachable(path: str, params: dict[str, str]) -> tuple[int, Any]:
    raise httpx.ConnectError("connection refused")


def _brief(client: AwarenessClient) -> BRIEFFunction:
    fn = BRIEFFunction(FunctionDeps())
    fn._awareness = client  # test seam, handed to the TOP and CN legs
    return fn


# ── BRIEF ────────────────────────────────────────────────────────────────


def test_brief_watchlist_leg_is_cn_symbols_and_btcusdt_maps_to_btc() -> None:
    client, seen = _client(
        _route(
            {"AAPL": [_raw("a1", symbols=["AAPL"], sentiment={"label": "positive", "score": 0.6, "model": "finbert:ProsusAI/finbert"})],
             "BTC": [_raw("b1", symbols=["BTC"])]},
            macro=[_raw("m1", symbols=[])],
        )
    )
    result = _run(_brief(client).execute(watchlist=["AAPL", "BTCUSDT"]))
    data = result.data

    assert data["status"] == "ok"
    sent = [dict(req.url.params) for req in seen]
    symbol_calls = [p["symbols"] for p in sent if "symbols" in p]
    assert sorted(symbol_calls) == ["AAPL", "BTC"], "watchlist leg must be CN with the Awareness symbols filter"
    assert all("q" not in p for p in sent), "no full-text TOP(symbol=, query=) leg any more"
    macro_calls = [p for p in sent if "symbols" not in p]
    assert len(macro_calls) == 1 and macro_calls[0]["story"] == "true", "one TOP macro call"

    tags = {a["id"]: a["matched_symbol"] for a in data["articles"]}
    assert tags == {"a1": "AAPL", "b1": "BTC", "m1": "MACRO"}
    sections = {a["id"]: a["section"] for a in data["articles"]}
    assert sections == {"a1": "watchlist", "b1": "watchlist", "m1": "top_stories"}
    assert [a["section"] for a in data["articles"]][:2] == ["watchlist", "watchlist"], "watchlist rows first"
    assert "(BTC)" in data["markdown"] and "(AAPL)" in data["markdown"]
    assert [leg["leg"] for leg in data["legs"]] == ["MACRO", "AAPL", "BTC"]


def test_brief_keeps_awareness_evidence_and_never_rescores(monkeypatch) -> None:
    import showme.finbert_analyzer as finbert

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("BRIEF must not re-score sentiment with stamp_items")

    monkeypatch.setattr(finbert, "stamp_items", boom, raising=False)
    client, _ = _client(
        _route(
            {"AAPL": [_raw("a1", symbols=["AAPL"], sentiment={"label": "negative", "score": -0.7, "model": "finbert:ProsusAI/finbert"})]},
            macro=[_raw("m1", symbols=[])],  # no sentiment at all
        )
    )
    result = _run(_brief(client).execute(watchlist=["AAPL"]))
    by_id = {a["id"]: a for a in result.data["articles"]}

    evidence = by_id["a1"]
    assert evidence["url"] == "https://www.cnbc.com/a1"
    assert evidence["publisher"] == "CNBC" and evidence["publisher_tier"] == 2
    assert evidence["quality_label"] == "premium"
    assert evidence["sentiment"] == "negative"
    assert evidence["sentiment_model"] == "finbert:ProsusAI/finbert"
    assert evidence["story_id"] == "story-a1"
    assert "CNBC" in result.data["markdown"] and "(https://www.cnbc.com/a1)" in result.data["markdown"]

    no_sentiment = by_id["m1"]
    assert no_sentiment["sentiment"] is None, "a row without an Awareness sentiment keeps none"
    assert no_sentiment["sentiment_score"] is None


def test_brief_stale_leg_reports_cached_snapshot_and_not_live() -> None:
    client, _ = _client(
        _route(
            {"AAPL": [_raw("a1", symbols=["AAPL"])]},
            macro=[_raw("m1", symbols=[])],
            providers=DOWN,
        )
    )
    result = _run(_brief(client).execute(watchlist=["AAPL"]))
    assert result.data["status"] == "ok"
    assert result.data["meta"]["providers"] == DOWN
    assert result.metadata["data_mode"] == "cached_snapshot"
    assert result.metadata["live"] is False
    assert any(leg["stale"] for leg in result.data["legs"])
    assert "Cached snapshot" in result.data["markdown"]


def test_brief_all_legs_down_is_provider_unavailable_with_reason() -> None:
    client, _ = _client(_unreachable)
    result = _run(_brief(client).execute(watchlist=["AAPL", "BTCUSDT"]))
    data = result.data

    assert data["status"] == "provider_unavailable"
    assert "awareness service is not running" in data["reason"]
    assert data["articles"] == [] and data["article_count"] == 0
    assert data["next_actions"] == awareness_news.UNAVAILABLE_ACTIONS
    assert result.sources == ["no_live_source"]
    assert result.metadata["data_mode"] == "provider_unavailable"
    assert result.metadata["live"] is False
    assert "Awareness news service unavailable" in data["markdown"]
    assert "](http" not in data["markdown"], "an unavailable brief cites no headline"


def test_brief_partial_outage_keeps_answered_legs_and_names_the_gap() -> None:
    def respond(path: str, params: dict[str, str]) -> tuple[int, Any]:
        if params.get("symbols") == "AAPL":
            raise httpx.ConnectError("connection refused")
        return _envelope([_raw("m1", symbols=[])] if "symbols" not in params else [])

    client, _ = _client(respond)
    result = _run(_brief(client).execute(watchlist=["AAPL"]))
    data = result.data

    assert data["status"] == "ok"
    assert [a["id"] for a in data["articles"]] == ["m1"]
    gap = next(leg for leg in data["legs"] if leg["leg"] == "AAPL")
    assert gap["status"] == "provider_unavailable" and gap["reason"]
    assert "Coverage gaps" in data["markdown"] and "AAPL (unavailable)" in data["markdown"]


def test_brief_answered_but_no_rows_is_empty_not_unavailable() -> None:
    client, _ = _client(_route({}, macro=[]))
    result = _run(_brief(client).execute(watchlist=["AAPL"]))
    assert result.data["status"] == "empty"
    assert result.data["articles"] == []
    assert result.metadata["data_mode"] == "live_official"
    assert result.data["next_actions"]


def test_brief_methodology_describes_awareness_not_rss() -> None:
    client, _ = _client(_route({}, macro=[]))
    data = _run(_brief(client).execute(watchlist=["AAPL"])).data
    blob = " ".join(
        [data["methodology"], *data["field_dictionary"].values(), *data["next_actions"]]
    ).lower()
    for legacy in ("rss", "gdelt", "yfinance", "finbert analyzer"):
        assert legacy not in blob, legacy
    assert "awareness" in data["methodology"].lower()
    assert "does not call an llm" in data["methodology"].lower()


# ── TLDR ─────────────────────────────────────────────────────────────────


def _patch_tldr_sources(monkeypatch, *, top: dict[str, Any], eco: dict[str, Any]) -> None:
    import showme.quotes as quotes

    async def fake_snapshot(symbol: str) -> dict[str, Any]:
        return {"symbol": symbol, "last": 100.0, "previous_close": 100.0, "change_pct": 0.0, "source": "test"}

    async def fake_top(self: Any, instrument: Any = None, **params: Any) -> FunctionResult:
        return FunctionResult(code="TOP", instrument=None, data=top, sources=["awareness:news"], metadata={})

    async def fake_eco(self: Any, instrument: Any = None, **params: Any) -> FunctionResult:
        return FunctionResult(code="ECO", instrument=None, data=eco, sources=["awareness:econ"], metadata={})

    monkeypatch.setattr(quotes, "fetch_quote_snapshot", fake_snapshot)
    monkeypatch.setattr(TOPFunction, "execute", fake_top)
    monkeypatch.setattr(ECOFunction, "execute", fake_eco)


def _tldr(**overrides: Any) -> dict[str, Any]:
    params = {
        "symbols": ["MSFT"],
        "quote_timeout": 2.0,
        "news_timeout": 2.0,
        "eco_timeout": 2.0,
        "llm_timeout": 0.1,
        "timeout": 3.0,
    }
    params.update(overrides)
    return params


def test_tldr_reads_top_rows_and_eco_rows(monkeypatch) -> None:
    _patch_tldr_sources(
        monkeypatch,
        top={"status": "ok", "rows": [{"title": "Chip export rules tighten"}, {"title": "Fed holds rates"}]},
        eco={"status": "ok", "rows": [{"country": "US", "event": "CPI y/y", "importance": 3}]},
    )
    result = _run(TLDRFunction(deps=FunctionDeps()).execute(**_tldr()))
    assert result.data["news"] == ["Chip export rules tighten", "Fed holds rates"]
    assert result.data["events"] == [{"country": "US", "event": "CPI y/y", "importance": 3}]
    assert not any(w.startswith(("top:", "eco:")) for w in result.metadata["provider_errors"])
    if result.data.get("summary_model", "local").startswith("local"):
        assert "Chip export rules tighten" in result.data["markdown"]
        assert "**Calendar items:** 1 scheduled" in result.data["markdown"]


def test_tldr_unavailable_sources_are_reported_not_counted_as_zero(monkeypatch) -> None:
    _patch_tldr_sources(
        monkeypatch,
        top={"status": "provider_unavailable", "reason": "awareness service is not running", "rows": []},
        eco={"status": "provider_unavailable", "reason": "awareness service is not running", "rows": []},
    )
    result = _run(TLDRFunction(deps=FunctionDeps()).execute(**_tldr()))
    assert result.data["news"] == [] and result.data["events"] == []
    assert any("awareness service is not running" in w for w in result.metadata["provider_errors"])
    if result.data.get("summary_model", "local").startswith("local"):
        assert "**News themes:** unavailable (awareness service is not running)" in result.data["markdown"]
        assert "**Calendar items:** unavailable (awareness service is not running)" in result.data["markdown"]
        assert "0 scheduled" not in result.data["markdown"]


# ── NewsAgent ────────────────────────────────────────────────────────────


def test_news_agent_reads_rows_and_passes_q(monkeypatch) -> None:
    from showme.engine.agents import news as news_agent

    seen_params: dict[str, Any] = {}

    async def fake_top(self: Any, instrument: Any = None, **params: Any) -> FunctionResult:
        seen_params.update(params)
        rows = [{"title": f"story {i}"} for i in range(12)]
        return FunctionResult(code="TOP", instrument=None, data={"status": "ok", "rows": rows}, sources=[])

    captured: dict[str, Any] = {}

    class FakeSummarizer:
        def __init__(self, deps: Any = None) -> None:
            pass

        async def run(self, task: AgentTask) -> Any:
            captured["articles"] = task.inputs["articles"]

            class _Out:
                output = "ok"
                cost_usd = 0.0
                model = "fake"

            return _Out()

    monkeypatch.setattr(TOPFunction, "execute", fake_top)
    monkeypatch.setattr(news_agent, "SummarizerAgent", FakeSummarizer)

    result = _run(news_agent.NewsAgent(FunctionDeps()).run(AgentTask(role="news", instruction="nvidia export")))
    assert seen_params == {"q": "nvidia export"}, "NewsAgent must pass q, not the legacy query"
    assert captured["articles"] == [f"story {i}" for i in range(10)]
    assert len(result.output["articles"]) == 10


def test_news_agent_unavailable_top_yields_no_articles(monkeypatch) -> None:
    from showme.engine.agents import news as news_agent

    async def fake_top(self: Any, instrument: Any = None, **params: Any) -> FunctionResult:
        return FunctionResult(
            code="TOP",
            instrument=None,
            data={"status": "provider_unavailable", "reason": "down", "rows": []},
            sources=["no_live_source"],
        )

    captured: dict[str, Any] = {}

    class FakeSummarizer:
        def __init__(self, deps: Any = None) -> None:
            pass

        async def run(self, task: AgentTask) -> Any:
            captured["articles"] = task.inputs["articles"]

            class _Out:
                output = ""
                cost_usd = 0.0
                model = "fake"

            return _Out()

    monkeypatch.setattr(TOPFunction, "execute", fake_top)
    monkeypatch.setattr(news_agent, "SummarizerAgent", FakeSummarizer)
    result = _run(news_agent.NewsAgent(FunctionDeps()).run(AgentTask(role="news", instruction="x")))
    assert captured["articles"] == []
    assert result.output["articles"] == []
