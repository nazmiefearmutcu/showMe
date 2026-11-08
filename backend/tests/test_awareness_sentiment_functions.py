"""S3a — sentiment functions on Awareness: SOSC (entity sentiment), MSENT (market
sentiment dashboard) and the Welcome gauge route. All tests run offline through
``httpx.MockTransport``; nothing touches the live awareness-markets service."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.data_sources.awareness import AwarenessClient
from showme.engine.functions.news.msent import MSENTFunction
from showme.engine.functions.news.sosc import SOSCFunction, _base_symbol
from showme.server_routes import AppDeps
from showme.server_routes import market_gauge as market_gauge_route

PREFIX = "/v1/markets"


def _now_iso(days_ago: float = 0.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _envelope(data: Any, providers: list[dict[str, Any]] | None = None, notes: list[str] | None = None) -> dict[str, Any]:
    return {
        "data": data,
        "meta": {
            "generated_at": _now_iso(),
            "count": None,
            "providers": providers if providers is not None else [
                {"provider": "news.gnews", "status": "ok", "last_ok_at": _now_iso(), "last_error": None, "items_last_ok": 60},
            ],
            "filters": {},
            "notes": notes or [],
        },
    }


def _client(routes: dict[str, Callable[[httpx.Request], httpx.Response] | dict[str, Any]],
            seen: list[httpx.Request] | None = None) -> AwarenessClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        path = request.url.path
        if path not in routes:
            return httpx.Response(404, json={"detail": f"no route {path}"})
        target = routes[path]
        if callable(target):
            return target(request)
        return httpx.Response(200, json=target)

    return AwarenessClient("http://aw.test", transport=httpx.MockTransport(handler), autostart=False)


def _down_client() -> AwarenessClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    return AwarenessClient("http://aw.test", transport=httpx.MockTransport(handler), autostart=False)


def _entity_payload(count: int = 3, *, providers: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    headlines = [
        {
            "id": f"h{i}",
            "title": f"Headline {i}",
            "publisher_name": "Reuters",
            "url": f"https://example.test/{i}",
            "published_at": _now_iso(0.1),
            "sentiment": {"label": "positive", "score": 0.6, "confidence": 0.9, "model": "finbert:ProsusAI/finbert"},
            "quality_label": "standard",
        }
        for i in range(min(count, 2))
    ]
    series = [{"ts": _now_iso(0.1), "mean": 0.3, "weighted_mean": 0.31, "count": count, "positive": 2,
               "negative": 0, "neutral": 1}]
    body = {
        "entity_id": "AAPL",
        "count": count,
        "mean": 0.3 if count else None,
        "weighted_mean": 0.31 if count else None,
        "positive_share": 0.66 if count else None,
        "negative_share": 0.0 if count else None,
        "momentum_z": None,
        "dispersion": None,
        "latest_at": _now_iso(0.1) if count else None,
        "publishers": 2 if count else 0,
        "series": series if count else [],
        "headlines": headlines if count else [],
        "gdelt_tone": [{"ts": _now_iso(0.2), "value": -3.9}, {"ts": _now_iso(0.1), "value": -0.5}] if count else [],
    }
    return _envelope(body, providers=providers)


def _social_payload() -> dict[str, Any]:
    row = {"ticker": "AAPL", "name": "Apple", "rank": 4, "mentions": 40, "upvotes": 100,
           "mentions_24h_ago": 50, "mention_change_pct": -20.0, "rank_change": 2, "as_of": _now_iso(0.05)}
    return _envelope({"stocks": [row], "crypto": [{**row, "ticker": "BTC", "rank": 1}]})


def _sosc(client: AwarenessClient | None, *, symbol: str = "AAPL", asset: AssetClass = AssetClass.EQUITY,
          **params: Any) -> Any:
    fn = SOSCFunction(FunctionDeps())
    if client is not None:
        fn._awareness = client
    instrument = Instrument(symbol=symbol, asset_class=asset) if symbol else None
    return asyncio.run(fn.execute(instrument=instrument, **params))


def _standard_routes(entity: dict[str, Any] | None = None, social: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        f"{PREFIX}/sentiment/entity/AAPL": entity or _entity_payload(3),
        f"{PREFIX}/sentiment/social": social or _social_payload(),
    }


# ───────────────────────────── SOSC ─────────────────────────────


def test_sosc_ok_reads_entity_sentiment_and_social_from_awareness() -> None:
    seen: list[httpx.Request] = []
    out = _sosc(_client(_standard_routes(), seen))

    assert out.data["status"] == "ok"
    assert out.sources == ["awareness:sentiment"]
    assert out.metadata["live"] is True
    assert out.metadata["data_mode"] == "live_official"
    assert out.metadata["provider"] == "awareness"
    assert out.data["news"]["count"] == 3
    assert out.data["news"]["mean"] == pytest.approx(0.3)
    assert out.data["social"]["rank"] == 4
    assert [h["id"] for h in out.data["headlines"]] == ["h0", "h1"]
    assert out.data["headlines"][0]["sentiment"] == "positive"
    platforms = [r["platform"] for r in out.data["rows"]]
    assert platforms == ["News (FinBERT)", "Reddit (ApeWisdom)", "GDELT tone"]
    # GDELT tone is passed through in its native scale, not rescaled.
    assert out.data["gdelt_tone"][-1]["value"] == pytest.approx(-0.5)
    assert "finbert:ProsusAI/finbert" in out.data["methodology"]
    assert "not rescaled" in out.data["methodology"]
    assert out.data["meta"]["providers"]


def test_sosc_sends_window_and_bucket_to_the_entity_endpoint() -> None:
    seen: list[httpx.Request] = []
    _sosc(_client(_standard_routes(), seen), window="30d")
    entity_calls = [r for r in seen if "/sentiment/entity/" in r.url.path]
    assert entity_calls, "entity endpoint was not called"
    assert entity_calls[0].url.params["window"] == "30d"
    assert entity_calls[0].url.params["bucket"] == "1d"


def test_sosc_empty_window_is_empty_with_no_score() -> None:
    routes = _standard_routes(entity=_entity_payload(0), social=_envelope({"stocks": [], "crypto": []}))
    out = _sosc(_client(routes))

    assert out.data["status"] == "empty"
    assert out.data["news"]["count"] == 0
    assert out.data["news"]["mean"] is None
    assert out.data["headlines"] == []
    assert out.data["rows"] == []
    assert out.sources == ["awareness:sentiment"]


def test_sosc_awareness_down_is_provider_unavailable_not_a_score() -> None:
    out = _sosc(_down_client())

    assert out.data["status"] == "provider_unavailable"
    assert "not running" in out.data["reason"]
    assert out.data["rows"] == []
    assert out.data["headlines"] == []
    assert out.data["social"] is None
    assert out.data["next_actions"]
    assert out.sources == ["no_live_source"]
    assert out.metadata["fallback"] is True
    assert out.metadata["live"] is False
    assert out.metadata["data_mode"] == "provider_unavailable"
    assert "news" not in out.data


def test_sosc_stale_provider_is_cached_snapshot_and_surfaced() -> None:
    providers = [
        {"provider": "news.feeds", "status": "down", "last_ok_at": None, "last_error": "TimeoutError", "items_last_ok": 0},
        {"provider": "sent.gdelt_tone", "status": "ok", "last_ok_at": _now_iso(), "last_error": None, "items_last_ok": 9},
    ]
    out = _sosc(_client(_standard_routes(entity=_entity_payload(3, providers=providers))))

    assert out.data["status"] == "ok"
    assert out.metadata["data_mode"] == "cached_snapshot"
    assert out.metadata["live"] is False
    assert any("news.feeds" in e for e in out.metadata["provider_errors"])
    assert any("news.feeds" in w for w in out.warnings)


def test_sosc_social_failure_keeps_news_and_warns() -> None:
    routes = {
        f"{PREFIX}/sentiment/entity/AAPL": _entity_payload(3),
        f"{PREFIX}/sentiment/social": lambda request: httpx.Response(500, json={"detail": "boom"}),
    }
    out = _sosc(_client(routes))

    assert out.data["status"] == "ok"
    assert out.data["social"] is None
    assert [r["platform"] for r in out.data["rows"]] == ["News (FinBERT)", "GDELT tone"]
    assert any("social buzz unavailable" in w for w in out.warnings)


def test_sosc_rejects_an_invalid_window_as_input_error() -> None:
    out = _sosc(_client(_standard_routes()), window="2h")
    assert out.data["status"] == "input_error"
    assert out.data["rows"] == []


def test_sosc_legacy_days_param_maps_onto_window() -> None:
    seen: list[httpx.Request] = []
    out = _sosc(_client(_standard_routes(), seen), days=1)
    assert out.data["window"] == "1d"
    assert [r for r in seen if "/entity/" in r.url.path][0].url.params["window"] == "1d"

    seen.clear()
    out = _sosc(_client(_standard_routes(), seen), days="30")
    assert out.data["window"] == "30d"
    assert [r for r in seen if "/entity/" in r.url.path][0].url.params["window"] == "30d"


def test_sosc_default_window_is_seven_days() -> None:
    out = _sosc(_client(_standard_routes()))
    assert out.data["window"] == "7d"
    assert out.metadata["bucket"] == "1h"


def test_sosc_requires_a_symbol() -> None:
    fn = SOSCFunction(FunctionDeps())
    fn._awareness = _client(_standard_routes())
    out = asyncio.run(fn.execute(instrument=None))
    assert out.data["status"] == "input_required"
    assert out.sources == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("BTCUSDT", "BTC"),
        ("BTC-USD", "BTC"),
        ("USDJPY", "USDJPY"),
        ("BRK.B", "BRK-B"),
        ("THYAO.IS", "THYAO.IS"),
        ("aapl", "AAPL"),
    ],
)
def test_sosc_symbol_normalisation(raw: str, expected: str) -> None:
    assert _base_symbol(raw) == expected


def test_sosc_requests_the_normalised_entity_path() -> None:
    seen: list[httpx.Request] = []
    routes = {
        f"{PREFIX}/sentiment/entity/BTC": _entity_payload(2),
        f"{PREFIX}/sentiment/social": _social_payload(),
    }
    _sosc(_client(routes, seen), symbol="BTCUSDT", asset=AssetClass.CRYPTO)
    assert any(r.url.path == f"{PREFIX}/sentiment/entity/BTC" for r in seen)


def test_sosc_rows_never_contain_market_or_price_rows() -> None:
    out = _sosc(_client(_standard_routes()))
    allowed = {"News (FinBERT)", "Reddit (ApeWisdom)", "GDELT tone"}
    assert {r["platform"] for r in out.data["rows"]} <= allowed
    assert "price" not in str(out.data).lower()
    assert "binance" not in str(out.data).lower()
    assert "coingecko" not in str(out.data).lower()


def test_sosc_unexpected_exception_is_not_swallowed_into_a_score() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("programming error")

    client = AwarenessClient("http://aw.test", transport=httpx.MockTransport(boom), autostart=False)
    with pytest.raises(RuntimeError):
        _sosc(client)


# ───────────────────────────── MSENT ─────────────────────────────


def _market_payload(**overrides: Any) -> dict[str, Any]:
    cnn_history = [{"ts": _now_iso(d), "value": 40.0 + d} for d in (200, 60, 20, 1)]
    vix_history = [{"ts": _now_iso(d), "vix": 18.0, "vix3m": 19.0} for d in (120, 10)]
    data = {
        "cnn": {
            "score": 22.1, "rating": "extreme fear", "as_of": _now_iso(1), "previous_close": 19.9,
            "previous_1_week": 26.3, "previous_1_month": 47.0, "previous_1_year": 24.3,
            "components": [{"key": "vix", "label": "VIX", "score": 9.1, "rating": "extreme fear", "as_of": _now_iso(1)}],
            "history": cnn_history,
        },
        "crypto": {"score": 28.0, "rating": "Fear", "as_of": _now_iso(0.1),
                   "history": [{"ts": _now_iso(3), "value": 30.0}]},
        "vix": {"vix": 25.6, "vix9d": 27.2, "vix3m": 24.6, "as_of": _now_iso(1), "term_ratio": 1.04,
                "structure": "backwardation", "history": vix_history},
        "social": {"stocks": [{"ticker": "NVDA", "rank": 1, "mentions": 95}],
                   "crypto": [{"ticker": "BTC", "rank": 1, "mentions": 57}]},
        "sources": {"cnn": _now_iso(1), "cboe": _now_iso(1)},
    }
    data.update(overrides)
    return _envelope(data)


def _msent(client: AwarenessClient | None, **params: Any) -> Any:
    fn = MSENTFunction(FunctionDeps())
    if client is not None:
        fn._awareness = client
    return asyncio.run(fn.execute(instrument=None, **params))


def test_msent_ok_passes_awareness_sections_through() -> None:
    out = _msent(_client({f"{PREFIX}/sentiment/market": _market_payload()}))

    assert out.data["status"] == "ok"
    assert out.data["cnn"]["score"] == pytest.approx(22.1)
    assert out.data["crypto"]["rating"] == "Fear"
    assert out.data["vix"]["structure"] == "backwardation"
    assert out.data["social"]["stocks"][0]["ticker"] == "NVDA"
    assert out.data["sources"]["cnn"]
    assert out.sources == ["awareness:sentiment"]
    assert out.metadata["live"] is True
    assert out.metadata["data_mode"] == "live_official"
    assert out.data["meta"]["providers"]


def test_msent_null_sections_stay_null() -> None:
    payload = _market_payload(cnn=None, vix=None)
    out = _msent(_client({f"{PREFIX}/sentiment/market": payload}))

    assert out.data["status"] == "ok"
    assert out.data["cnn"] is None
    assert out.data["vix"] is None
    assert out.data["crypto"]["score"] == pytest.approx(28.0)


def test_msent_all_null_and_no_social_is_empty_not_a_default_gauge() -> None:
    payload = _market_payload(cnn=None, crypto=None, vix=None, social=None)
    out = _msent(_client({f"{PREFIX}/sentiment/market": payload}))

    assert out.data["status"] == "empty"
    assert out.data["cnn"] is None and out.data["crypto"] is None and out.data["vix"] is None
    assert out.data["social"] is None


def test_msent_trims_history_to_history_days() -> None:
    out = _msent(_client({f"{PREFIX}/sentiment/market": _market_payload()}), history_days=30)

    assert out.data["history_days"] == 30
    kept = [point["ts"] for point in out.data["cnn"]["history"]]
    assert len(kept) == 2  # the 200-day-old point is dropped, the 60-day one too
    assert len(out.data["vix"]["history"]) == 1  # 120-day-old VIX point dropped
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    assert all(datetime.fromisoformat(ts) >= cutoff for ts in kept)


def test_msent_history_days_defaults_and_clamps() -> None:
    assert _msent(_client({f"{PREFIX}/sentiment/market": _market_payload()})).data["history_days"] == 90
    assert _msent(_client({f"{PREFIX}/sentiment/market": _market_payload()}), history_days=9999).data["history_days"] == 365
    assert _msent(_client({f"{PREFIX}/sentiment/market": _market_payload()}), history_days=0).data["history_days"] == 1


def test_msent_invalid_history_days_is_input_error() -> None:
    out = _msent(_client({f"{PREFIX}/sentiment/market": _market_payload()}), history_days="many")
    assert out.data["status"] == "input_error"
    assert out.sources == []


def test_msent_awareness_down_is_provider_unavailable() -> None:
    out = _msent(_down_client())

    assert out.data["status"] == "provider_unavailable"
    assert out.data["cnn"] is None and out.data["vix"] is None and out.data["social"] is None
    assert out.data["next_actions"]
    assert out.sources == ["no_live_source"]
    assert out.metadata["fallback"] is True
    assert out.metadata["live"] is False
    assert out.metadata["data_mode"] == "provider_unavailable"


def test_msent_stale_provider_is_cached_snapshot() -> None:
    providers = [{"provider": "sent.cboe_vix", "status": "degraded", "last_ok_at": None,
                  "last_error": "stale", "items_last_ok": 0}]
    payload = _envelope(_market_payload()["data"], providers=providers)
    out = _msent(_client({f"{PREFIX}/sentiment/market": payload}))

    assert out.data["status"] == "ok"
    assert out.metadata["data_mode"] == "cached_snapshot"
    assert out.metadata["live"] is False


# ───────────────────────────── registration + usage ─────────────────────────────


def test_msent_is_registered_global_and_described() -> None:
    from showme.engine.core.base_function import FunctionRegistry

    assert FunctionRegistry.get("MSENT") is MSENTFunction
    assert MSENTFunction.code == "MSENT"
    assert MSENTFunction.asset_classes == ()
    assert MSENTFunction.description.strip()
    assert MSENTFunction.name != "MSENT function."


def test_msent_manifest_seed_and_usage_branch() -> None:
    from showme.manifest import REGISTRY, load_seeds
    from showme.server_routes._agent_runtime import _function_usage

    load_seeds()
    assert "MSENT" in REGISTRY
    seed = REGISTRY.get("MSENT")
    assert seed.provider_chain.primary == "awareness"
    assert [i.name for i in seed.inputs] == ["history_days"]

    usage = _function_usage("MSENT", "Market Sentiment", "news_intel", "", [])
    assert usage["inputs"] == ["history_days"]
    assert usage["purpose"] != "MSENT function."


def test_sosc_manifest_inputs_match_what_the_handler_reads() -> None:
    from showme.manifest import REGISTRY, load_seeds

    load_seeds()
    assert "SOSC" in REGISTRY
    seed = REGISTRY.get("SOSC")
    assert seed.provider_chain.primary == "awareness"
    assert [i.name for i in seed.inputs] == ["symbol", "window"]
    assert any("composite_sources_listed_in_payload" in t.name for t in seed.semantic_tests)


# ───────────────────────────── Welcome gauge route ─────────────────────────────


def _gauge_app(client: AwarenessClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(market_gauge_route, "get_awareness_client", lambda: client)
    app = FastAPI()
    market_gauge_route.register(app, AppDeps())
    return TestClient(app)


def test_market_gauge_returns_cnn_fear_and_greed(monkeypatch: pytest.MonkeyPatch) -> None:
    tc = _gauge_app(_client({f"{PREFIX}/sentiment/market": _market_payload()}), monkeypatch)
    body = tc.get("/api/sentiment/market-gauge").json()

    assert body["ok"] is True
    assert body["score"] == pytest.approx(22.1)
    assert body["rating"] == "extreme fear"
    assert body["previous_close"] == pytest.approx(19.9)
    assert body["source"] == "CNN Fear & Greed via Awareness"
    assert body["as_of"]


def test_market_gauge_without_cnn_value_reports_not_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    tc = _gauge_app(_client({f"{PREFIX}/sentiment/market": _market_payload(cnn=None)}), monkeypatch)
    body = tc.get("/api/sentiment/market-gauge").json()
    assert body["ok"] is False
    assert "score" not in body
    assert body["reason"]


def test_market_gauge_awareness_down_reports_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    tc = _gauge_app(_down_client(), monkeypatch)
    body = tc.get("/api/sentiment/market-gauge").json()
    assert body["ok"] is False
    assert "not running" in body["reason"]
    assert "score" not in body
