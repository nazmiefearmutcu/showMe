"""TOP, NI, CN, NALRT and NSE on the awareness news service (no network).

Each function is exercised through the real ``AwarenessClient`` and ``mapping.news_row``
with an ``httpx.MockTransport`` router. Covered per function: ok, empty,
provider_unavailable, stale provider (cached_snapshot), GET-string parameter parsing,
and no market rows. Plus CN symbol normalisation, TOP story collapse and story drawer
lookup, NI preset mapping, NALRT severity grading, NSE quality-floor disclosure, and the
TOP cold-call wait in the SWR route.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from showme.engine.core.base_function import FunctionDeps, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.data_sources.awareness import AwarenessClient
from showme.engine.functions.news.awareness_news import NO_LIVE_SOURCE, NEWS_SOURCE
from showme.engine.functions.news.cn import CNFunction, normalise_symbol
from showme.engine.functions.news.nalrt import NewsAlertFunction
from showme.engine.functions.news.nse import NSEFunction
from showme.engine.functions.news.ni import NIFunction
from showme.engine.functions.news.top import TOPFunction

OK_PROVIDERS = [{"provider": "news.gnews", "status": "ok", "last_ok_at": None, "last_error": None, "items_last_ok": 5}]
STALE_PROVIDERS = [
    {"provider": "news.feeds", "status": "down", "last_ok_at": None, "last_error": "TimeoutError: ", "items_last_ok": 0},
    {"provider": "news.gnews", "status": "ok", "last_ok_at": None, "last_error": None, "items_last_ok": 5},
]
STALE_NOTE = "stale or failing providers: news.feeds"

Respond = Callable[[str, dict[str, str], httpx.Request], tuple[int, Any]]


def _item(
    item_id: str = "a1",
    *,
    importance: float = 61.0,
    quality: str = "premium",
    symbols: list[str] | None = None,
    story_id: str = "s1",
    story_size: int = 3,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "title": f"Headline {item_id}",
        "url": f"https://www.cnbc.com/{item_id}",
        "publisher_id": "cnbc",
        "publisher_name": "CNBC",
        "publisher_domain": "cnbc.com",
        "publisher_tier": 2,
        "published_at": "2026-11-08T11:00:00Z",
        "summary": "Summary.",
        "symbols": symbols if symbols is not None else ["NVDA"],
        "topics": ["earnings"],
        "sentiment": {"label": "positive", "score": 0.7, "confidence": 0.9, "model": "finbert:ProsusAI/finbert"},
        "importance": importance,
        "quality_label": quality,
        "quality_score": 68.0,
        "quality_reasons": ["tier2:+38"],
        "story_id": story_id,
        "story_size": story_size,
        "entities": [{"type": "equity", "id": "NVDA", "name": "Nvidia", "confidence": 0.95}],
    }


def _envelope(data: Any, *, providers: list[dict[str, Any]] | None = None, notes: list[str] | None = None) -> tuple[int, dict[str, Any]]:
    return 200, {
        "data": data,
        "meta": {
            "generated_at": "2026-11-08T12:00:00Z",
            "count": len(data) if isinstance(data, list) else 1,
            "providers": providers if providers is not None else OK_PROVIDERS,
            "filters": {},
            "notes": notes or [],
            "feed_health": {"ok": 3, "degraded": 0, "down": 0, "never": 0},
        },
    }


def _client(respond: Respond) -> tuple[AwarenessClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        status, body = respond(request.url.path, dict(request.url.params), request)
        return httpx.Response(status, json=body)

    client = AwarenessClient("http://aw.test", transport=httpx.MockTransport(handler), autostart=False)
    return client, seen


def _fn(cls: type, client: AwarenessClient) -> Any:
    fn = cls(deps=FunctionDeps())
    fn._awareness = client  # test seam
    return fn


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _news_only(rows: list[dict[str, Any]], *, providers: list[dict[str, Any]] | None = None, notes: list[str] | None = None) -> Respond:
    def respond(path: str, params: dict[str, str], request: httpx.Request) -> tuple[int, Any]:
        assert path == "/v1/markets/news", path
        return _envelope(rows, providers=providers, notes=notes)

    return respond


def _unavailable(path: str, params: dict[str, str], request: httpx.Request) -> tuple[int, Any]:
    raise httpx.ConnectError("connection refused", request=request)


# ── TOP ──────────────────────────────────────────────────────────────────


def test_top_ok_maps_story_leads_and_sends_contract_params() -> None:
    client, seen = _client(_news_only([_item("a1"), _item("a2", story_id="s2", story_size=1)]))
    result = _run(_fn(TOPFunction, client).execute(
        hours="6", limit="20", min_quality="premium", topics="earnings, m_and_a",
        asset_classes="equities", countries="us", q="nvidia",
    ))
    query = seen[0].url.params
    assert query["hours"] == "6" and query["limit"] == "20" and query["min_quality"] == "premium"
    assert query["topics"] == "earnings,m_and_a" and query["asset_classes"] == "equities"
    assert query["countries"] == "US" and query["q"] == "nvidia" and query["story"] == "true"
    assert result.data["status"] == "ok"
    assert [row["id"] for row in result.data["rows"]] == ["a1", "a2"]
    row = result.data["rows"][0]
    assert row["publisher"] == "CNBC" and row["publisher_tier"] == 2
    assert row["sentiment"] == "positive" and row["quality_reasons"] == ["tier2:+38"]
    assert result.sources == [NEWS_SOURCE]
    assert result.metadata["data_mode"] == "live_official"
    assert result.metadata["live"] is True
    assert result.data["meta"]["providers"] == OK_PROVIDERS


def test_top_empty_is_status_empty_not_ok() -> None:
    client, _ = _client(_news_only([]))
    result = _run(_fn(TOPFunction, client).execute())
    assert result.data["status"] == "empty"
    assert result.data["rows"] == []
    assert result.data["next_actions"]
    assert result.metadata.get("fallback") is None


def test_top_unavailable_is_provider_unavailable_with_reason() -> None:
    client, _ = _client(_unavailable)
    result = _run(_fn(TOPFunction, client).execute())
    assert result.data["status"] == "provider_unavailable"
    assert "not running" in result.data["reason"]
    assert result.data["rows"] == []
    assert result.sources == [NO_LIVE_SOURCE]
    assert result.metadata["fallback"] is True and result.metadata["live"] is False
    assert result.metadata["data_mode"] == "provider_unavailable"


def test_top_stale_provider_keeps_rows_but_marks_cached_snapshot() -> None:
    client, _ = _client(_news_only([_item("a1")], providers=STALE_PROVIDERS, notes=[STALE_NOTE]))
    result = _run(_fn(TOPFunction, client).execute())
    assert result.data["status"] == "ok" and len(result.data["rows"]) == 1
    assert result.metadata["data_mode"] == "cached_snapshot"
    assert result.metadata["live"] is False
    assert STALE_NOTE in result.warnings
    assert any(err.startswith("news.feeds: down") for err in result.metadata["provider_errors"])


def test_top_parses_get_strings_and_clamps() -> None:
    client, seen = _client(_news_only([]))
    fn = _fn(TOPFunction, client)
    _run(fn.execute(hours="abc", limit="9999", min_quality="bogus"))
    assert seen[-1].url.params["hours"] == "24"
    assert seen[-1].url.params["limit"] == "200"
    assert seen[-1].url.params["min_quality"] == "standard"
    _run(fn.execute(min_quality="low"))  # the pane's "show low-quality" relaxer is honoured
    assert seen[-1].url.params["min_quality"] == "low"
    _run(fn.execute(days="2"))  # legacy Welcome-feed window
    assert seen[-1].url.params["hours"] == "48"
    _run(fn.execute(hours="9999"))
    assert seen[-1].url.params["hours"] == "168"
    _run(fn.execute(max_age_days="2"))
    assert seen[-1].url.params["hours"] == "48"
    _run(fn.execute(hours="6", max_age_days="7"))
    assert seen[-1].url.params["hours"] == "6"


def test_top_maps_legacy_query_to_q_and_route_no_longer_injects_it() -> None:
    # ``query`` is the legacy name of ``q``. The route used to inject a profile query into
    # every news call; that default is now dropped for the Awareness news codes, so an explicit
    # caller ``query`` is a real search again.
    client, seen = _client(_news_only([]))
    _run(_fn(TOPFunction, client).execute(query="nvidia"))
    assert seen[-1].url.params["q"] == "nvidia"
    from showme.server_routes._agent_runtime import _route_function_params

    routed = _route_function_params("TOP", {"limit": 50})
    assert "query" not in routed and routed.get("limit") == 50


def test_top_story_id_resolves_lead_item_to_story_brief() -> None:
    story = {
        "id": "s1", "title": "Headline a1", "corroboration": 2,
        "publishers": [{"id": "cnbc", "name": "CNBC", "tier": 2}],
        "items": [{"id": "a1", "title": "Headline a1", "publisher_name": "CNBC", "publisher_tier": 2,
                   "url": "https://www.cnbc.com/a1", "published_at": "2026-11-08T11:00:00Z", "quality_label": "premium"}],
        "first_seen_at": "2026-11-08T11:00:00Z", "last_updated_at": "2026-11-08T11:05:00Z",
    }

    def respond(path: str, params: dict[str, str], request: httpx.Request) -> tuple[int, Any]:
        if path == "/v1/markets/news/a1":
            return 200, {"data": {**_item("a1"), "story": story}, "meta": {"generated_at": None, "providers": OK_PROVIDERS, "notes": []}}
        return 404, {"detail": "news item not found"}

    client, _ = _client(respond)
    result = _run(_fn(TOPFunction, client).execute(story_id="a1"))
    assert result.data["status"] == "ok"
    assert result.data["story"]["corroboration"] == 2
    assert result.data["story"]["publishers"][0]["name"] == "CNBC"


def test_top_story_hash_resolves_through_stories_to_lead() -> None:
    story = {"id": "s1", "title": "T", "corroboration": 1, "publishers": [], "items": [],
             "first_seen_at": None, "last_updated_at": None}

    def respond(path: str, params: dict[str, str], request: httpx.Request) -> tuple[int, Any]:
        if path == "/v1/markets/news/s1":
            return 404, {"detail": "news item not found"}
        if path == "/v1/markets/stories":
            return _envelope([{"id": "s1", "lead_item_id": "a1", "lead": _item("a1")}])
        if path == "/v1/markets/news/a1":
            return 200, {"data": {**_item("a1"), "story": story}, "meta": {"providers": OK_PROVIDERS, "notes": []}}
        raise AssertionError(path)

    client, _ = _client(respond)
    result = _run(_fn(TOPFunction, client).execute(story_id="s1"))
    assert result.data["status"] == "ok" and result.data["story"]["id"] == "s1"


def test_top_story_not_found_is_empty() -> None:
    def respond(path: str, params: dict[str, str], request: httpx.Request) -> tuple[int, Any]:
        if path.startswith("/v1/markets/news/"):
            return 404, {"detail": "news item not found"}
        return _envelope([])

    client, _ = _client(respond)
    result = _run(_fn(TOPFunction, client).execute(story_id="missing"))
    assert result.data["status"] == "empty"
    assert result.data["story"] is None


# ── NI ───────────────────────────────────────────────────────────────────


def test_ni_fed_preset_maps_to_central_bank_topic() -> None:
    client, seen = _client(_news_only([_item("f1")]))
    result = _run(_fn(NIFunction, client).execute(topic="FED", hours="12", limit="10"))
    assert seen[-1].url.params["topics"] == "central_bank"
    assert "asset_classes" not in seen[-1].url.params
    assert seen[-1].url.params["hours"] == "12" and seen[-1].url.params["limit"] == "10"
    assert result.data["status"] == "ok" and result.data["topic"] == "FED"


def test_ni_m_and_a_preset_uses_awareness_tag_spelling() -> None:
    client, seen = _client(_news_only([]))
    result = _run(_fn(NIFunction, client).execute(topic="M&A"))
    assert seen[-1].url.params["topics"] == "m_and_a"
    assert result.data["status"] == "empty"


def test_ni_banks_preset_restricts_to_equities() -> None:
    client, seen = _client(_news_only([]))
    _run(_fn(NIFunction, client).execute(topic="BANKS"))
    assert seen[-1].url.params["asset_classes"] == "equities"
    assert "funding_liquidity" in seen[-1].url.params["topics"]


def test_ni_unknown_topic_is_disclosed_not_silent() -> None:
    client, seen = _client(_news_only([]))
    result = _run(_fn(NIFunction, client).execute(topic="NOPE"))
    assert result.data["topic"] == "MACRO"
    assert "NOPE" in result.data["hidden_note"]
    assert "inflation" in seen[-1].url.params["topics"]


def test_ni_unavailable_and_stale() -> None:
    client, _ = _client(_unavailable)
    down = _run(_fn(NIFunction, client).execute(topic="EARN"))
    assert down.data["status"] == "provider_unavailable"
    client, _ = _client(_news_only([_item("e1")], providers=STALE_PROVIDERS, notes=[STALE_NOTE]))
    stale = _run(_fn(NIFunction, client).execute(topic="EARN"))
    assert stale.metadata["data_mode"] == "cached_snapshot" and stale.metadata["live"] is False


# ── CN ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("BTCUSDT", "BTC"),
        ("BTC-USD", "BTC"),
        ("ETHUSDT", "ETH"),
        ("BRK.B", "BRK-B"),
        ("BRK-B", "BRK-B"),
        ("THYAO.IS", "THYAO.IS"),
        ("aapl", "AAPL"),
        ("WBTC", "WBTC"),
        ("", ""),
    ],
)
def test_cn_symbol_normalisation(raw: str, expected: str) -> None:
    assert normalise_symbol(raw) == expected


def test_cn_crypto_instrument_queries_entity_BTC_and_returns_news_only() -> None:
    client, seen = _client(_news_only([_item("c1", symbols=["BTC"])]))
    instrument = Instrument(symbol="BTCUSDT", asset_class=AssetClass.CRYPTO)
    result = _run(_fn(CNFunction, client).execute(instrument, hours="72", limit="5"))
    assert seen[-1].url.params["symbols"] == "BTC"
    assert seen[-1].url.params["hours"] == "72" and seen[-1].url.params["limit"] == "5"
    assert result.data["symbol"] == "BTC" and result.data["status"] == "ok"
    assert len(seen) == 1, "CN must make exactly one awareness request (no market/price legs)"
    assert result.sources == [NEWS_SOURCE]


def test_cn_without_symbol_is_input_required_and_makes_no_request() -> None:
    client, seen = _client(_news_only([]))
    result = _run(_fn(CNFunction, client).execute())
    assert result.data["status"] == "input_required"
    assert seen == []


def test_cn_empty_unavailable_and_stale() -> None:
    client, _ = _client(_news_only([]))
    assert _run(_fn(CNFunction, client).execute(symbol="AAPL")).data["status"] == "empty"
    client, _ = _client(_unavailable)
    assert _run(_fn(CNFunction, client).execute(symbol="AAPL")).data["status"] == "provider_unavailable"
    client, _ = _client(_news_only([_item("a1")], providers=STALE_PROVIDERS, notes=[STALE_NOTE]))
    stale = _run(_fn(CNFunction, client).execute(symbol="AAPL"))
    assert stale.metadata["data_mode"] == "cached_snapshot"


# ── NALRT ────────────────────────────────────────────────────────────────


def test_nalrt_grades_critical_and_high_and_drops_below_floor() -> None:
    rows = [_item("h1", importance=75.0), _item("c1", importance=90.0), _item("low", importance=60.0)]
    client, seen = _client(_news_only(rows))
    result = _run(_fn(NewsAlertFunction, client).execute(min_importance="70", hours="6", limit="30"))
    assert float(seen[-1].url.params["min_importance"]) == 70.0
    assert [row["id"] for row in result.data["rows"]] == ["c1", "h1"]
    assert [row["severity"] for row in result.data["rows"]] == ["critical", "high"]
    assert result.data["critical_count"] == 1
    assert result.data["top_importance_score"] == 90.0
    assert result.data["alerts"] == result.data["rows"]
    assert result.data["status"] == "ok"


def test_nalrt_threshold_alias_used_by_alert_engine() -> None:
    client, seen = _client(_news_only([_item("x", importance=60.0)]))
    result = _run(_fn(NewsAlertFunction, client).execute(threshold=60, limit=20, live=True))
    assert float(seen[-1].url.params["min_importance"]) == 60.0
    assert result.data["threshold"] == 60.0 and len(result.data["rows"]) == 1


def test_nalrt_empty_unavailable_stale() -> None:
    client, _ = _client(_news_only([]))
    assert _run(_fn(NewsAlertFunction, client).execute()).data["status"] == "empty"
    client, _ = _client(_unavailable)
    assert _run(_fn(NewsAlertFunction, client).execute()).data["status"] == "provider_unavailable"
    client, _ = _client(_news_only([_item("c", importance=95.0)], providers=STALE_PROVIDERS, notes=[STALE_NOTE]))
    stale = _run(_fn(NewsAlertFunction, client).execute())
    assert stale.metadata["data_mode"] == "cached_snapshot" and stale.metadata["live"] is False


def test_nalrt_never_touches_rss_or_gdelt() -> None:
    class _Boom:
        async def fetch(self, request: Any) -> Any:  # pragma: no cover - must not run
            raise AssertionError("NALRT must read awareness only")

    deps = FunctionDeps(rss=_Boom(), gdelt=_Boom())  # type: ignore[arg-type]
    client, _ = _client(_news_only([_item("c", importance=90.0)]))
    fn = NewsAlertFunction(deps)
    fn._awareness = client  # type: ignore[attr-defined]
    result = _run(fn.execute())
    assert result.data["status"] == "ok"
    assert "rss" not in result.sources and "gdelt" not in result.sources


# ── NSE ──────────────────────────────────────────────────────────────────


def test_nse_company_name_search_uses_full_text_q() -> None:
    client, seen = _client(_news_only([_item("b1")]))
    result = _run(_fn(NSEFunction, client).execute(q="Berkshire", hours="48", limit="10"))
    assert seen[-1].url.params["q"] == "Berkshire"
    assert seen[-1].url.params["hours"] == "48"
    assert result.data["status"] == "ok" and result.data["query"] == "Berkshire"


def test_nse_without_query_or_symbol_is_input_required_no_request() -> None:
    client, seen = _client(_news_only([]))
    result = _run(_fn(NSEFunction, client).execute())
    assert result.data["status"] == "input_required"
    assert result.data["rows"] == []
    assert seen == []


def test_nse_symbol_filters_only_when_no_search_text() -> None:
    client, seen = _client(_news_only([_item("s1")]))
    _run(_fn(NSEFunction, client).execute(symbol="aapl"))
    assert seen[-1].url.params["symbols"] == "AAPL"
    assert "q" not in seen[-1].url.params


def test_nse_quality_floor_is_disclosed_and_never_silently_lowered() -> None:
    def respond(path: str, params: dict[str, str], request: httpx.Request) -> tuple[int, Any]:
        if params.get("min_quality") == "low":
            return _envelope([_item("lo", quality="low")])
        return _envelope([])

    client, _ = _client(respond)
    result = _run(_fn(NSEFunction, client).execute(q="obscure"))
    assert result.data["status"] == "empty" and result.data["rows"] == []
    assert result.data["relax"] == {"min_quality": "low"}
    assert "1 row(s)" in result.data["hidden_note"]
    assert "min_quality=low" in result.data["hidden_note"]


def test_nse_explicit_low_floor_returns_rows_without_relax_hint() -> None:
    client, seen = _client(_news_only([_item("lo", quality="low")]))
    result = _run(_fn(NSEFunction, client).execute(q="obscure", min_quality="low"))
    assert seen[-1].url.params["min_quality"] == "low"
    assert result.data["status"] == "ok" and result.data["relax"] is None
    assert len(seen) == 1


def test_nse_unavailable_and_stale() -> None:
    client, _ = _client(_unavailable)
    assert _run(_fn(NSEFunction, client).execute(q="apple")).data["status"] == "provider_unavailable"
    client, _ = _client(_news_only([_item("a")], providers=STALE_PROVIDERS, notes=[STALE_NOTE]))
    stale = _run(_fn(NSEFunction, client).execute(q="apple"))
    assert stale.metadata["data_mode"] == "cached_snapshot" and stale.metadata["live"] is False


# ── SWR cold call (TOP only) ─────────────────────────────────────────────


def _swr_app(monkeypatch: pytest.MonkeyPatch, delay: float) -> TestClient:
    from showme import server
    from showme.server_routes import AppDeps, function_index

    monkeypatch.setattr(server, "home_swr_enabled", lambda: True)
    monkeypatch.setattr(server, "_route_function_params", lambda code, params: dict(params))

    async def slow_exec(code: str, params: dict[str, Any]) -> FunctionResult:
        await asyncio.sleep(delay)
        return FunctionResult(
            code=code, instrument=None,
            data={"status": "ok", "rows": [{"title": "slow but real"}]},
            sources=[NEWS_SOURCE],
        )

    monkeypatch.setattr(server, "_execute_showme_function", slow_exec)
    app = FastAPI()
    function_index.register(app, AppDeps(boot_state={"engine_attached": True}))
    return TestClient(app)


def test_swr_top_cold_call_is_awaited_past_the_head_start(monkeypatch: pytest.MonkeyPatch) -> None:
    # Head start is 1 s; awareness answers in tens of ms, so a 2.2 s cold call is
    # slow, not down: TOP must return its real rows, not the warming envelope.
    client = _swr_app(monkeypatch, delay=2.2)
    body = client.post("/api/fn/TOP", json={"hours": "13"}).json()
    assert body["data"]["status"] == "ok"
    assert body["data"]["rows"][0]["title"] == "slow but real"
    assert not body.get("metadata", {}).get("fallback")
