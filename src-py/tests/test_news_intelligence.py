from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from src.services.news_intelligence import enrich_articles, health_summary


def test_enrich_articles_flags_symbol_specific_critical_news() -> None:
    rows = enrich_articles(
        [
            {
                "title": "SEC approves spot Bitcoin ETF after market close",
                "summary": "Bitcoin funds rally as liquidity expectations rise.",
                "source": "SEC",
                "published_at": "2026-05-02T09:00:00+00:00",
                "url": "https://example.test/sec-bitcoin-etf",
            },
            {
                "title": "General crypto market update",
                "summary": "Prices moved sideways.",
                "source": "blog",
                "published_at": "2026-05-02T09:00:00+00:00",
            },
        ],
        symbol="BTCUSDT",
        query="bitcoin",
        asset_class="CRYPTO",
        threshold=70,
    )

    assert rows[0]["alert"] is True
    assert rows[0]["severity"] in {"high", "critical"}
    assert rows[0]["importance_score"] >= 70
    assert "bitcoin" in rows[0]["matched_terms"]
    assert rows[0]["importance_score"] > rows[1]["importance_score"]


def test_enrich_articles_sorts_headlines_newest_first() -> None:
    rows = enrich_articles(
        [
            {
                "title": "SEC approves spot Bitcoin ETF after market close",
                "summary": "Bitcoin funds rally as liquidity expectations rise.",
                "source": "SEC",
                "published_at": "2026-05-01T09:00:00+00:00",
            },
            {
                "title": "Bitcoin liquidity update",
                "summary": "Bitcoin desks report stronger overnight activity.",
                "source": "market wire",
                "published_at": "2026-05-02T09:00:00+00:00",
            },
        ],
        symbol="BTCUSDT",
        query="bitcoin",
        asset_class="CRYPTO",
        threshold=70,
    )

    assert [row["title"] for row in rows] == [
        "Bitcoin liquidity update",
        "SEC approves spot Bitcoin ETF after market close",
    ]
    assert any(row["alert"] for row in rows)


def test_health_summary_counts_failed_and_ok_feeds() -> None:
    summary = health_summary([
        {"ok": True, "latency_ms": 120, "items": 10},
        {"ok": False, "latency_ms": 3000, "items": 0},
    ])
    assert summary["feeds"] == 2
    assert summary["ok"] == 1
    assert summary["failed"] == 1
    assert summary["items"] == 10
