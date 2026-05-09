"""Optional showMe bridge for the local ``instant`` news/squawk data line.

The bridge is intentionally secondary: if ``instant`` is not running, showMe
still boots and the UI shows a degraded auxiliary-line state instead of taking
over the normal news functions.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

import httpx


DEFAULT_INSTANT_URL = "http://127.0.0.1:8787"
REQUEST_TIMEOUT = 2.5


def instant_base_url() -> str:
    return os.environ.get("SHOWME_INSTANT_URL", DEFAULT_INSTANT_URL).rstrip("/")


def _candidate_instant_roots() -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path | None) -> None:
        if path is None:
            return
        try:
            resolved = path.expanduser().resolve()
        except Exception:
            return
        if resolved in seen:
            return
        seen.add(resolved)
        candidates.append(resolved)

    override = os.environ.get("SHOWME_INSTANT_ROOT")
    if override:
        add(Path(override))

    home = Path.home()
    add(home / "Library" / "Application Support" / "showMe" / "instant")
    add(home / "Desktop" / "Projeler" / "proje" / "instant")
    add(home / "Desktop" / "Projeler" / "instant")
    add(home / "Projeler" / "proje" / "instant")
    add(home / "instant")

    try:
        source_root = Path(__file__).resolve().parents[3] / "instant"
        add(source_root)
    except Exception:
        pass

    return candidates


def instant_root() -> Path:
    for candidate in _candidate_instant_roots():
        if (candidate / "data" / "instant.db").exists():
            return candidate
    candidates = _candidate_instant_roots()
    return candidates[0] if candidates else Path.home() / "instant"


def instant_db_path() -> Path:
    override = os.environ.get("SHOWME_INSTANT_DB")
    if override:
        return Path(override).expanduser().resolve()
    for candidate in _candidate_instant_roots():
        db = candidate / "data" / "instant.db"
        if db.exists():
            return db
    return instant_root() / "data" / "instant.db"


async def instant_status() -> dict[str, Any]:
    base_url = instant_base_url()
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            health = await _get_json(client, f"{base_url}/api/health")
            performance = await _get_json(client, f"{base_url}/api/performance")
        return {
            "ok": True,
            "mode": "secondary",
            "primary": False,
            "transport": "http",
            "base_url": base_url,
            "health": health,
            "performance": performance,
            "warning": None,
        }
    except Exception as exc:  # noqa: BLE001 - optional line must degrade cleanly.
        db = instant_db_path()
        fallback = await _sqlite_snapshot(db)
        return {
            "ok": bool(fallback["events"]),
            "mode": "secondary",
            "primary": False,
            "transport": "sqlite-fallback" if fallback["events"] else "unavailable",
            "base_url": base_url,
            "db_path": str(db),
            "health": fallback["health"],
            "performance": fallback["performance"],
            "warning": f"instant HTTP unavailable: {exc}",
        }


async def instant_events(limit: int = 100) -> dict[str, Any]:
    limit = max(1, min(int(limit), 500))
    base_url = instant_base_url()
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            payload = await _get_json(client, f"{base_url}/api/events?limit={limit}")
        return {"ok": True, "mode": "secondary", "transport": "http", **payload}
    except Exception as exc:  # noqa: BLE001
        fallback = await _sqlite_snapshot(instant_db_path(), limit=limit)
        return {
            "ok": bool(fallback["events"]),
            "mode": "secondary",
            "transport": "sqlite-fallback" if fallback["events"] else "unavailable",
            "events": fallback["events"],
            "warning": f"instant HTTP unavailable: {exc}",
        }


async def instant_health() -> dict[str, Any]:
    status = await instant_status()
    return {
        "ok": status["ok"],
        "mode": "secondary",
        "primary": False,
        "transport": status["transport"],
        "health": status.get("health"),
        "warning": status.get("warning"),
    }


async def instant_performance() -> dict[str, Any]:
    status = await instant_status()
    return {
        "ok": status["ok"],
        "mode": "secondary",
        "primary": False,
        "transport": status["transport"],
        "performance": status.get("performance"),
        "warning": status.get("warning"),
    }


async def instant_backfill(limit: int = 15) -> dict[str, Any]:
    limit = max(1, min(int(limit), 50))
    base_url = instant_base_url()
    try:
        async with httpx.AsyncClient(timeout=max(REQUEST_TIMEOUT, 20.0)) as client:
            payload = await _post_json(client, f"{base_url}/api/backfill?limit={limit}")
        return {"ok": True, "mode": "secondary", "transport": "http", **payload}
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "mode": "secondary",
            "transport": "unavailable",
            "warning": f"instant backfill unavailable: {exc}",
        }


async def _get_json(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    response = await client.get(url)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {"payload": payload}


async def _post_json(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    response = await client.post(url)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {"payload": payload}


async def _sqlite_snapshot(db_path: Path, limit: int = 100) -> dict[str, Any]:
    import asyncio

    return await asyncio.to_thread(_sqlite_snapshot_sync, db_path, limit)


def _sqlite_snapshot_sync(db_path: Path, limit: int) -> dict[str, Any]:
    if not db_path.exists():
        return {"events": [], "health": {"sources": [], "metrics": {}}, "performance": {"speedups": []}}
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        events = [
            _event_row(row)
            for row in conn.execute(
                "SELECT * FROM events ORDER BY fetched_at DESC, priority_score DESC LIMIT ?",
                (limit,),
            ).fetchall()
        ]
        sources = [dict(row) for row in conn.execute("SELECT * FROM source_health ORDER BY source_name").fetchall()]
        metrics = dict(
            conn.execute(
                """
                SELECT
                    COUNT(*) AS total_events,
                    SUM(CASE WHEN priority_score >= 75 THEN 1 ELSE 0 END) AS breaking_events,
                    AVG(latency_seconds) AS avg_latency_seconds,
                    MAX(fetched_at) AS newest_fetched_at
                FROM events
                """
            ).fetchone()
        )
        conn.close()
        return {
            "events": events,
            "health": {"status": "sqlite-fallback", "sources": sources, "metrics": metrics},
            "performance": {"metrics": metrics, "speedups": []},
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "events": [],
            "health": {"sources": [], "metrics": {}, "error": str(exc)},
            "performance": {"speedups": [], "error": str(exc)},
        }


def _event_row(row: sqlite3.Row) -> dict[str, Any]:
    import json

    out = dict(row)
    for key in ("matched_keywords", "metadata"):
        try:
            out[key] = json.loads(out.get(key) or "[]")
        except Exception:
            out[key] = []
    return out
