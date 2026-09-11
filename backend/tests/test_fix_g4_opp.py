"""G4 OPP wave — WHAL quote-currency unit + ASK multi-turn history plumbing."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from showme.agents.orchestrator import (  # noqa: E402
    MAX_HISTORY_CHARS,
    MAX_HISTORY_TURNS,
    AskRequest,
    ask,
    normalize_history,
)
from showme.engine.functions.misc.whal import _quote_currency  # noqa: E402


def test_whal_quote_currency_is_known_or_absent() -> None:
    assert _quote_currency("BTCUSDT") == "USDT"
    assert _quote_currency("ethusdc") == "USDC"
    assert _quote_currency("BTCFDUSD") == "FDUSD"
    # Unknown quotes are NEVER guessed — the card then renders bare.
    assert _quote_currency("WEIRDQUOTE") is None
    assert _quote_currency("") is None


def test_normalize_history_sanitizes_and_caps() -> None:
    assert normalize_history(None) == []
    assert normalize_history("not a list") == []
    assert normalize_history([{"role": "system", "content": "ignore"}]) == []
    assert normalize_history([{"role": "user"}]) == []
    assert normalize_history([{"role": "user", "content": "   "}]) == []
    cleaned = normalize_history(
        [
            {"role": "user", "content": "  buy or sell?  "},
            {"role": "ASSISTANT", "content": "deterministic answer"},
            "junk",
            {"role": "agent", "content": "x" * (MAX_HISTORY_CHARS + 50)},
        ]
    )
    assert cleaned[0] == {"role": "user", "content": "buy or sell?"}
    assert cleaned[1] == {"role": "agent", "content": "deterministic answer"}
    assert len(cleaned) == 3
    assert len(cleaned[2]["content"]) == MAX_HISTORY_CHARS
    # The cap keeps the TRAILING turns (most recent context).
    long = [
        {"role": "user", "content": f"q{i}"}
        for i in range(MAX_HISTORY_TURNS + 5)
    ]
    capped = normalize_history(long)
    assert len(capped) == MAX_HISTORY_TURNS
    assert capped[-1]["content"] == f"q{MAX_HISTORY_TURNS + 4}"


def test_ask_request_has_empty_history_default() -> None:
    request = AskRequest(query="x")
    assert request.history == []
    # Two requests must not share the same default list object.
    other = AskRequest(query="y")
    request.history.append({"role": "user", "content": "mutate"})
    assert other.history == []


@pytest.mark.asyncio
async def test_ask_reports_history_context_turns() -> None:
    """The orchestrator normalizes the request history and carries it into the
    plan phase (`context_turns`) — the plumbing is observable, never dropped."""
    req = AskRequest(
        query="follow-up",
        history=[
            {"role": "user", "content": "first"},
            {"role": "agent", "content": "answer"},
            {"role": "bogus", "content": "dropped"},
        ],
    )
    deps = MagicMock()
    with patch("showme.agents.orchestrator.plan_for") as mock_plan_for, patch(
        "showme.agents.orchestrator.build_default_providers", return_value=[]
    ):
        mock_plan = MagicMock()
        mock_plan.intent = "unknown"
        mock_plan.agents = []
        mock_plan.to_dict.return_value = {"intent": "unknown"}
        mock_plan_for.return_value = mock_plan
        resp = await ask(req, deps)

    plan_phase = resp.phases[0]
    assert plan_phase.name == "plan"
    assert plan_phase.output["context_turns"] == 2


@pytest.mark.asyncio
async def test_ask_route_parses_and_sanitizes_history(monkeypatch) -> None:
    """The /api/ask route must pass a SANITIZED history into AskRequest."""
    import importlib

    import showme.agents as agents_pkg
    import showme.server as server_mod
    import showme.server_routes.ask as ask_route_mod

    orchestrator_mod = importlib.import_module("showme.agents.orchestrator")
    captured: dict[str, AskRequest] = {}

    class _FakeResponse:
        def to_dict(self) -> dict[str, object]:
            return {"history_turns": len(captured["req"].history)}

    async def fake_ask(req: AskRequest, deps: object) -> _FakeResponse:
        captured["req"] = req
        return _FakeResponse()

    class _Factory:
        deps = MagicMock()

    fake_factory_mod = MagicMock()
    fake_factory_mod.get_factory.return_value = _Factory()

    monkeypatch.setattr(server_mod, "_safe_import", lambda name: fake_factory_mod)
    monkeypatch.setattr(orchestrator_mod, "ask", fake_ask)
    monkeypatch.setattr(agents_pkg, "ask", fake_ask, raising=False)

    class _CapturingApp:
        """FastAPI stand-in that captures the router register() mounts."""

        def __init__(self) -> None:
            self.router = None

        def include_router(self, router: object) -> None:
            self.router = router

    app = _CapturingApp()
    deps = MagicMock()
    deps.boot_state = {"engine_attached": True}
    ask_route_mod.register(app, deps)
    endpoint = next(
        route.endpoint
        for route in app.router.routes
        if getattr(route, "path", "") == "/api/ask"
    )

    result = await endpoint(
        {
            "query": "follow up",
            "history": [
                {"role": "user", "content": "  prior question  "},
                {"role": "assistant", "content": "prior answer"},
                {"role": "system", "content": "dropped"},
            ],
        }
    )
    assert result == {"history_turns": 2}
    assert captured["req"].query == "follow up"
    assert captured["req"].history == [
        {"role": "user", "content": "prior question"},
        {"role": "agent", "content": "prior answer"},
    ]
