"""Home-dashboard liveness fixes (2026-09-15).

Covers three regressions reported from the Welcome home page:

* **newsflow / BRIEF emptied by the routed timeout default** — every routed
  news-category call was clamped to a 3s budget while the RSS fan-out
  routinely needs 6-9s, so TOP/BRIEF returned "rss: timed out after 3.0s"
  with zero rows. News category now defaults to a 10s budget.
* **sentiment gauge inert** — the X chain (search-engine scrape + bundled
  RoBERTa model) is unavailable on this host (engines blocked, model bundle
  missing). ``symbol_chip`` now falls back to live author-labelled Stocktwits
  tags behind an X-chain circuit breaker.
* portfolio add-position route coverage lives in ``test_portfolio_route.py``.
"""
from __future__ import annotations

import pytest

from showme import server


# ---- news routing timeouts -------------------------------------------------


def test_news_category_defaults_get_ten_second_budget() -> None:
    params = server._route_function_params("TOP", {})
    assert params["timeout"] == 10
    assert params["news_timeout"] == 10


def test_brief_category_default_is_ten_seconds() -> None:
    params = server._route_function_params("BRIEF", {})
    assert params["news_timeout"] == 10


def test_non_news_category_keeps_tight_three_second_budget() -> None:
    params = server._route_function_params("GP", {})
    assert params["timeout"] == 3
    assert params["news_timeout"] == 3


def test_explicit_caller_timeout_wins_over_news_default() -> None:
    params = server._route_function_params("TOP", {"news_timeout": 4, "timeout": 4})
    assert params["news_timeout"] == 4
    assert params["timeout"] == 4


# ---- Stocktwits fallback service ------------------------------------------


def _labels(counts: dict[str, int]) -> list[dict]:
    """Build Stocktwits-shaped messages with the requested label counts."""
    messages: list[dict] = []
    idx = 0
    for label, count in counts.items():
        for _ in range(count):
            idx += 1
            messages.append(
                {
                    "id": idx,
                    "body": f"message {idx}",
                    "created_at": "2026-09-15T10:00:00Z",
                    "likes": {"total": idx},
                    "user": {"username": f"user{idx}"},
                    "entities": {"sentiment": {"basic": label}},
                }
            )
    return messages


def test_stocktwits_symbol_mapping() -> None:
    from showme.engine.services.stocktwits_sentiment import to_stocktwits_symbol

    assert to_stocktwits_symbol("AAPL") == "AAPL"
    assert to_stocktwits_symbol("aapl") == "AAPL"
    assert to_stocktwits_symbol("BTCUSDT") == "BTC.X"
    assert to_stocktwits_symbol("BTC/USDT") == "BTC.X"
    assert to_stocktwits_symbol("ETH-USD") == "ETH.X"
    assert to_stocktwits_symbol("SOLUSDT") == "SOL.X"
    # Unknown multi-letter suffix stays untouched (equity-style pass-through).
    assert to_stocktwits_symbol("BRK.B") == "BRK.B"
    assert to_stocktwits_symbol("") is None


def test_stocktwits_scores_only_labelled_messages() -> None:
    from showme.engine.services.stocktwits_sentiment import _aggregate

    messages = _labels({"Bullish": 5, "Bearish": 2}) + [
        {"id": 99, "body": "no label", "entities": {}},
        {"id": 100, "body": "also none"},
    ]
    chip = _aggregate("AAPL", messages, st_symbol="AAPL")
    assert chip is not None
    assert chip["ok"] is True
    assert chip["source"] == "stocktwits"
    assert chip["post_count"] == 7
    assert chip["messages_scanned"] == 9
    assert chip["bullish_score"] == round(3 / 7, 3)
    assert chip["mood"] == "bullish"


def test_stocktwits_refuses_verdict_below_minimum() -> None:
    from showme.engine.services.stocktwits_sentiment import _aggregate

    assert _aggregate("AAPL", _labels({"Bullish": 4}), st_symbol="AAPL") is None


def test_stocktwits_cache_serves_second_call(monkeypatch: pytest.MonkeyPatch) -> None:
    from showme.engine.services import stocktwits_sentiment as st

    st.clear_cache()
    monkeypatch.setattr(st, "MIN_REQUEST_INTERVAL_SECONDS", 0.0)
    calls = {"n": 0}

    def fake_get(url: str, timeout: float) -> dict:
        calls["n"] += 1
        return {"messages": _labels({"Bullish": 6, "Bearish": 1})}

    monkeypatch.setattr(st, "_http_get_json", fake_get)
    first = st.fetch_symbol_chip("AAPL")
    second = st.fetch_symbol_chip("AAPL")
    assert first is not None and second is not None
    assert first["bullish_score"] == second["bullish_score"]
    assert calls["n"] == 1, "cache miss should hit the network exactly once"
    st.clear_cache()


def test_stocktwits_failure_is_cached_and_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from showme.engine.services import stocktwits_sentiment as st

    st.clear_cache()
    monkeypatch.setattr(st, "MIN_REQUEST_INTERVAL_SECONDS", 0.0)
    calls = {"n": 0}

    def boom(url: str, timeout: float) -> dict:
        calls["n"] += 1
        raise RuntimeError("stocktwits http 403")

    monkeypatch.setattr(st, "_http_get_json", boom)
    assert st.fetch_symbol_chip("AAPL") is None
    assert st.fetch_symbol_chip("AAPL") is None
    assert calls["n"] == 1, "failure should be cached so polls cannot retry-storm"
    st.clear_cache()


# ---- X-chain circuit breaker + symbol_chip fallback ------------------------


@pytest.fixture(autouse=True)
def _reset_x_breaker():
    from showme import x_analysis

    x_analysis._reset_x_chain_breaker()
    yield
    x_analysis._reset_x_chain_breaker()


def _stub_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from showme import x_analysis

    def fake_fallback(symbol: str) -> dict:
        return {
            "symbol": symbol,
            "ok": True,
            "source": "stocktwits",
            "post_count": 12,
            "mood": "bullish",
            "bullish_score": 0.5,
            "confidence": 0.6,
            "summary": "stub",
            "summary_tr": "stub",
        }

    monkeypatch.setattr(x_analysis, "_stocktwits_fetch_chip", fake_fallback)


def test_symbol_chip_falls_back_when_x_returns_no_posts(monkeypatch: pytest.MonkeyPatch) -> None:
    from showme import x_analysis

    analyzer = x_analysis.XAnalyzer.instance()
    monkeypatch.setattr(
        analyzer,
        "analyze_topic",
        lambda **_: {
            "post_count": 0,
            "warning": "no posts returned by any scraper backend",
        },
    )
    _stub_fallback(monkeypatch)
    chip = analyzer.symbol_chip("AAPL")
    assert chip["ok"] is True
    assert chip["source"] == "stocktwits"
    assert chip["warning"] == "no posts returned by any scraper backend"
    # The dead chain must be cooled down so the next refresh skips it.
    assert x_analysis._x_chain_available() is False


def test_symbol_chip_falls_back_when_model_bundle_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from showme import x_analysis

    analyzer = x_analysis.XAnalyzer.instance()

    def raise_missing(**_: object) -> dict:
        raise FileNotFoundError("X sentiment model not found")

    monkeypatch.setattr(analyzer, "analyze_topic", raise_missing)
    _stub_fallback(monkeypatch)
    chip = analyzer.symbol_chip("MSFT")
    assert chip["ok"] is True and chip["source"] == "stocktwits"
    assert x_analysis._x_chain_available() is False


def test_symbol_chip_prefers_x_result_when_chain_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    from showme import x_analysis

    analyzer = x_analysis.XAnalyzer.instance()
    monkeypatch.setattr(
        analyzer,
        "analyze_topic",
        lambda **_: {
            "post_count": 25,
            "mood": "bearish",
            "summary": "x summary",
            "summary_tr": "x summary",
            "scores": {
                "bullish_score_engagement_weighted": -0.4,
                "confidence": 0.7,
            },
            "dominant": {"sentiment": "bearish", "emotion": "fear", "topic": "macro"},
            "distributions": {"sentiment_pct": {}, "emotion_pct": {}, "topic_pct": {}},
            "examples": {},
        },
    )
    monkeypatch.setattr(
        x_analysis,
        "_stocktwits_fetch_chip",
        lambda symbol: pytest.fail("fallback must not run on a healthy X chain"),
    )
    chip = analyzer.symbol_chip("AAPL")
    assert chip["ok"] is True
    assert chip["post_count"] == 25
    assert "source" not in chip


def test_symbol_chip_reports_both_chains_down(monkeypatch: pytest.MonkeyPatch) -> None:
    from showme import x_analysis

    analyzer = x_analysis.XAnalyzer.instance()
    monkeypatch.setattr(analyzer, "analyze_topic", lambda **_: {"post_count": 0})
    monkeypatch.setattr(x_analysis, "_stocktwits_fetch_chip", lambda symbol: None)
    chip = analyzer.symbol_chip("AAPL")
    assert chip["ok"] is False
    assert "stocktwits" in chip["error"]
