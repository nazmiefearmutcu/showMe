"""AwarenessClient + news row mapping (no network: httpx.MockTransport)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from showme.engine.data_sources.awareness import AwarenessClient, AwarenessUnavailable
from showme.engine.data_sources.awareness.mapping import news_row

ITEM = {
    "id": "abc",
    "title": "Nvidia beats estimates",
    "url": "https://www.cnbc.com/x",
    "publisher_id": "cnbc",
    "publisher_name": "CNBC",
    "publisher_domain": "cnbc.com",
    "publisher_tier": 2,
    "published_at": "2026-11-08T11:00:00Z",
    "summary": "Chipmaker tops forecasts.",
    "symbols": ["NVDA"],
    "topics": ["earnings"],
    "sentiment": {"label": "positive", "score": 0.7, "confidence": 0.9, "model": "finbert:ProsusAI/finbert"},
    "importance": 61.0,
    "quality_label": "premium",
    "quality_score": 68.0,
    "quality_reasons": ["tier2:+38"],
    "story_id": "s1",
    "story_size": 3,
    "entities": [{"type": "equity", "id": "NVDA", "name": "Nvidia", "confidence": 0.95}],
}


def _client(handler) -> AwarenessClient:  # type: ignore[no-untyped-def]
    return AwarenessClient("http://aw.test", transport=httpx.MockTransport(handler), autostart=False)


def test_get_decodes_envelope_and_joins_list_params() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={"data": [ITEM], "meta": {"generated_at": "2026-11-08T12:00:00Z", "providers": [
                {"provider": "news.feeds", "status": "ok"}, {"provider": "news.gnews", "status": "down"}],
                "notes": ["stale or failing providers: news.gnews"]}},
        )

    resp = asyncio.run(_client(handler).get("/news", {"symbols": ["NVDA", "AAPL"], "story": True, "q": None}))
    assert resp.data[0]["id"] == "abc"
    assert seen[0].url.path == "/v1/markets/news"
    assert seen[0].url.params["symbols"] == "NVDA,AAPL" and seen[0].url.params["story"] == "true"
    assert "q" not in seen[0].url.params
    assert resp.stale_providers == ["news.gnews"]
    assert resp.provenance()["provider"] == "awareness"


def test_errors_become_awareness_unavailable() -> None:
    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(AwarenessUnavailable) as exc:
        asyncio.run(_client(refused).get("/news"))
    assert "not running" in exc.value.reason

    def server_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "sentiment aggregation unavailable"})

    with pytest.raises(AwarenessUnavailable) as exc2:
        asyncio.run(_client(server_error).get("/sentiment/market"))
    assert exc2.value.status_code == 503 and "unavailable" in exc2.value.reason

    def not_envelope(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[1, 2, 3])

    with pytest.raises(AwarenessUnavailable):
        asyncio.run(_client(not_envelope).get("/news"))


def test_messageless_retry_error_after_autostart_names_the_exception_type() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if len(calls) == 1:
            raise httpx.ConnectError("refused", request=request)
        raise httpx.ReadTimeout("", request=request)  # httpx timeouts can carry no message

    client = _client(handler)

    async def autostarted() -> bool:
        return True

    client._try_autostart = autostarted  # type: ignore[method-assign]
    with pytest.raises(AwarenessUnavailable) as exc:
        asyncio.run(client.get("/news"))
    assert len(calls) == 2
    assert exc.value.reason == "awareness service did not answer after autostart: ReadTimeout"


def test_news_row_keeps_legacy_keys_with_real_attribution() -> None:
    row = news_row(ITEM)
    assert row["source"] == "CNBC" and row["url"] == row["link"] == "https://www.cnbc.com/x"
    assert row["sentiment"] == "positive" and row["sentiment_score"] == 0.7
    assert row["importance_score"] == 61.0 and row["quality_label"] == "premium"
    assert row["story_size"] == 3 and row["entities"][0]["id"] == "NVDA"
    assert news_row({"title": "x"})["story_size"] == 1
