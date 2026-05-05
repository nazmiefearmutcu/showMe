from __future__ import annotations

import sqlite3

import pytest

from showme.instant_line import instant_events


@pytest.mark.asyncio
async def test_instant_events_falls_back_to_sqlite(monkeypatch, tmp_path):
    db_path = tmp_path / "instant.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            dedupe_key TEXT,
            source_id TEXT,
            source_name TEXT,
            source_category TEXT,
            source_region TEXT,
            official_url TEXT,
            title TEXT,
            link TEXT,
            summary TEXT,
            generated_summary TEXT,
            priority_score INTEGER,
            priority_label TEXT,
            matched_keywords TEXT,
            calendar_window TEXT,
            published_at TEXT,
            fetched_at TEXT,
            latency_seconds REAL,
            metadata TEXT
        );
        CREATE TABLE source_health (
            source_id TEXT,
            source_name TEXT,
            enabled INTEGER,
            ok INTEGER,
            status TEXT,
            last_checked_at TEXT,
            last_success_at TEXT,
            last_error TEXT,
            last_latency_ms REAL,
            last_item_count INTEGER
        );
        INSERT INTO events VALUES (
            1, 'k', 'fed', 'Fed', 'central_bank', 'US', 'https://example.com',
            'Fed update', 'https://example.com/release', '', 'Fed posted an update',
            80, 'breaking', '["fed"]', NULL, NULL, '2026-05-05T16:00:00+00:00',
            1.2, '{}'
        );
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("SHOWME_INSTANT_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("SHOWME_INSTANT_DB", str(db_path))

    payload = await instant_events(limit=5)
    assert payload["transport"] == "sqlite-fallback"
    assert payload["events"][0]["title"] == "Fed update"
    assert payload["events"][0]["matched_keywords"] == ["fed"]
