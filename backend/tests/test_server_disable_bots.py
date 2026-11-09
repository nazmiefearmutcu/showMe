"""``SHOWME_DISABLE_BOTS=1`` keeps the bot runner from starting.

Audit and smoke sidecars run against a copy of (or an empty) app home; the
lifespan otherwise replays every enabled bot — and seeds the default KAOS
bot on a fresh home — which must never happen for a measurement run.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from showme import server
from showme.bots import lifespan


@pytest.fixture
def startup_calls(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    calls: list[str] = []

    async def fake_startup() -> None:
        calls.append("startup")

    monkeypatch.setattr(lifespan, "startup", fake_startup)
    return calls


@pytest.mark.parametrize("value", ["1", "true", "YES"])
def test_disable_bots_env_skips_bot_startup(monkeypatch, startup_calls, value):
    monkeypatch.setenv("SHOWME_DISABLE_BOTS", value)
    with TestClient(server.build_app(engine_root=None)):
        pass
    assert startup_calls == []


def test_bots_start_by_default(monkeypatch, startup_calls):
    monkeypatch.delenv("SHOWME_DISABLE_BOTS", raising=False)
    with TestClient(server.build_app(engine_root=None)):
        pass
    assert startup_calls == ["startup"]
