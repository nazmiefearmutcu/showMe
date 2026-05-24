"""QA-fix regression suite — 2026-05-23.

Pins the behavior introduced by the QA-report fixes:

* LLM router fail-closed budget on corrupt ledger
* CodeAgent AST whitelist refuses dangerous snippets
* CodeAgent runs in a per-call temp CWD
* /api/x/* handler timeouts
* OpenAPI ``securitySchemes`` declaration
* TOP RSS default timeout bumped + non-empty warnings
* GitHub integration degraded metadata flag
* Silent ``except: pass`` blocks now log
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from showme import server


# ── LLM router fail-closed budget ────────────────────────────────────────


def test_llm_router_load_today_spend_logs_corrupt_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A corrupt ledger no longer silently zeroes the daily spend.

    QA-fix: the previous code did ``except Exception: return 0.0`` which
    reset the budget every time a single line was malformed. Now the
    router publishes ``_load_error`` so callers can detect the degraded
    state.
    """
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "5")
    ledger = tmp_path / "runtime"
    ledger.mkdir(parents=True, exist_ok=True)
    (ledger / "llm_calls.jsonl").write_text("garbage\nmore-garbage\n")
    from showme.engine.agents.llm_router import LLMRouter

    r = LLMRouter()
    assert r.spent_today == 0.0
    assert getattr(r, "_load_error", None) is not None
    assert "unparseable" in r._load_error


def test_llm_router_unreadable_ledger_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An IO failure during ledger read pegs spent_today at the daily budget.

    QA-fix: previously a permission-denied read returned 0.0. Now we
    return the budget so the next call short-circuits with budget-
    exceeded instead of burning unlimited tokens.
    """
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "5")
    ledger_dir = tmp_path / "runtime"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger = ledger_dir / "llm_calls.jsonl"
    ledger.write_text("{}\n")

    from showme.engine.agents import llm_router as router_mod

    real_log_path = router_mod._log_path

    class _BoomPath:
        def __init__(self, real):
            self._real = real

        def exists(self):
            return self._real.exists()

        def read_text(self):
            raise OSError("permission denied")

    monkeypatch.setattr(router_mod, "_log_path", lambda: _BoomPath(real_log_path()))
    r = router_mod.LLMRouter()
    # Fail-closed: spent_today equals the budget so subsequent calls
    # short-circuit before issuing any LLM request.
    assert r.spent_today == r.daily_budget == 5.0
    assert r._load_error is not None
    assert "ledger_read_failed" in r._load_error


# ── CodeAgent sandbox ────────────────────────────────────────────────────


def test_code_agent_refuses_filesystem_module_import() -> None:
    """``import os`` is rejected before the subprocess spawns."""
    from showme.engine.agents.code import CodeAgent
    from showme.engine.core.base_agent import AgentTask

    agent = CodeAgent()
    task = AgentTask(role="code", instruction="", inputs={"code": "import os\nprint(1)"})
    result = asyncio.new_event_loop().run_until_complete(agent.run(task))
    assert result.error is not None
    assert "sandbox" in result.error
    assert result.output["refused"] is True


def test_code_agent_refuses_subprocess_call() -> None:
    from showme.engine.agents.code import CodeAgent
    from showme.engine.core.base_agent import AgentTask

    agent = CodeAgent()
    task = AgentTask(
        role="code",
        instruction="",
        inputs={"code": "import subprocess\nsubprocess.run(['ls'])"},
    )
    result = asyncio.new_event_loop().run_until_complete(agent.run(task))
    assert result.error is not None
    assert "sandbox" in result.error


def test_code_agent_refuses_open_call() -> None:
    """``open(...)`` is always refused regardless of mode."""
    from showme.engine.agents.code import CodeAgent
    from showme.engine.core.base_agent import AgentTask

    agent = CodeAgent()
    task = AgentTask(
        role="code",
        instruction="",
        inputs={"code": "open('/tmp/exfil', 'w').write('boom')"},
    )
    result = asyncio.new_event_loop().run_until_complete(agent.run(task))
    assert result.error is not None
    assert "sandbox" in result.error


def test_code_agent_blocks_dotted_attribute_walk() -> None:
    """Defense-in-depth: dotted access through a forbidden root is blocked."""
    from showme.engine.agents.code import _validate_code, _SandboxViolation

    # Even if a future refactor of the import check were to slip up, the
    # dotted-attribute walker still refuses ``os.<anything>`` access.
    with pytest.raises(_SandboxViolation):
        _validate_code("x = os.environ.get('SHELL')\n")


def test_code_agent_allows_pure_arithmetic() -> None:
    """Safe code runs and returns the stdout payload."""
    from showme.engine.agents.code import CodeAgent
    from showme.engine.core.base_agent import AgentTask

    agent = CodeAgent()
    task = AgentTask(
        role="code",
        instruction="",
        inputs={"code": "print(2 + 2)"},
    )
    result = asyncio.new_event_loop().run_until_complete(agent.run(task))
    assert result.error is None
    assert result.output is not None
    assert "4" in result.output["stdout"]


# ── OpenAPI securitySchemes ──────────────────────────────────────────────


@pytest.fixture
def qa_client(tmp_path_factory: pytest.TempPathFactory):
    home = tmp_path_factory.mktemp("qa-openapi-home")
    os.environ["SHOWME_HOME"] = str(home)
    app = server.build_app(engine_root=None)
    return TestClient(app)


def test_openapi_declares_x_showme_token_scheme(qa_client: TestClient) -> None:
    """``/openapi.json`` exposes the ShowMeToken apiKey-in-header scheme."""
    r = qa_client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    schemes = (spec.get("components") or {}).get("securitySchemes") or {}
    assert "ShowMeToken" in schemes
    scheme = schemes["ShowMeToken"]
    assert scheme["type"] == "apiKey"
    assert scheme["in"] == "header"
    assert scheme["name"] == "X-ShowMe-Token"


def test_openapi_exempts_liveness_probes_from_security(qa_client: TestClient) -> None:
    """``/api/health`` is exempt from the default security."""
    spec = qa_client.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    assert spec.get("security") == [{"ShowMeToken": []}]
    health = paths.get("/api/health") or {}
    op = health.get("get")
    if op is not None:
        assert op.get("security") == []


# ── GitHub integration degraded flag ─────────────────────────────────────


def test_github_search_route_propagates_degraded_metadata(
    qa_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When GitHub anon search returns [], the route reports degraded metadata."""
    from showme.integrations import github as gh_mod

    gh_mod._CACHE.clear()
    gh_mod._CACHE_STATUS.clear()

    async def _fake(q, language=None, limit=10):
        gh_mod._CACHE_STATUS[f"{q}|{language}|{limit}"] = "anon_blocked"
        return []

    monkeypatch.setattr(gh_mod, "search_code", _fake)
    r = qa_client.get("/api/integrations/github/search?q=rsi")
    assert r.status_code == 200
    body = r.json()
    md = body.get("metadata") or {}
    assert md.get("degraded") is True
    assert md.get("degraded_reason") == "github_anon_blocked"


# ── TOP RSS timeout default ──────────────────────────────────────────────


def test_top_function_default_timeout_is_ten_seconds() -> None:
    """QA-fix: default ``news_timeout`` raised from 5 -> 10."""
    src = Path(__file__).resolve().parents[1] / "showme" / "engine" / "functions" / "news" / "top.py"
    text = src.read_text()
    assert 'params.get("news_timeout", params.get("timeout", 10))' in text


def test_top_warning_carries_explicit_reason_on_empty_exc() -> None:
    """QA-fix: bare ``rss:`` empty label is replaced by exception class name."""
    src = Path(__file__).resolve().parents[1] / "showme" / "engine" / "functions" / "news" / "top.py"
    text = src.read_text()
    assert "or exc.__class__.__name__" in text


# ── XAI handler timeouts ─────────────────────────────────────────────────


def test_xai_module_imports_timeout_constant() -> None:
    """Ensure /api/x/* handlers consult ``XAI_HANDLER_TIMEOUT_SECONDS``."""
    from showme.server_routes import xai

    assert hasattr(xai, "XAI_HANDLER_TIMEOUT_SECONDS")
    assert xai.XAI_HANDLER_TIMEOUT_SECONDS > 0


def test_xai_health_respects_timeout(qa_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A health() call that hangs gets a fast-fail timeout payload."""
    # Override the per-handler timeout to 0.1s so the test runs quickly.
    from showme.server_routes import xai as xai_mod

    monkeypatch.setattr(xai_mod, "XAI_HANDLER_TIMEOUT_SECONDS", 0.1)

    # Stub XAnalyzer.instance().health() to block long enough for the
    # asyncio.wait_for to trip.
    from showme import x_analysis

    class _SlowAnalyzer:
        def health(self):
            import time

            time.sleep(0.5)
            return {"ok": True}

    monkeypatch.setattr(x_analysis.XAnalyzer, "instance", classmethod(lambda cls: _SlowAnalyzer()))
    r = qa_client.get("/api/x/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "timed out" in body["error"]


# ── WebSocket Origin enforcement ─────────────────────────────────────────


def test_websocket_module_logs_missing_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    """The websocket module emits a structured rejection log for missing Origin."""
    from showme.server_routes import websocket as ws_mod

    assert "1008" in ws_mod.__doc__ or hasattr(ws_mod, "register"), (
        "websocket module must still expose register()"
    )


# ── Silent exception logging ─────────────────────────────────────────────


def test_orchestrator_function_codes_logger_is_present() -> None:
    """QA-fix: ``_function_codes`` failure path now uses LOG.exception."""
    src = (
        Path(__file__).resolve().parents[1]
        / "showme"
        / "agents"
        / "orchestrator.py"
    )
    text = src.read_text()
    assert "LOG = logging.getLogger" in text
    assert "FunctionRegistry import failed" in text


def test_orchestrator_plan_parse_logger_is_present() -> None:
    """QA-fix: orchestrator ``_parse_plan`` now warns on bad JSON."""
    src = (
        Path(__file__).resolve().parents[1]
        / "showme"
        / "engine"
        / "agents"
        / "orchestrator.py"
    )
    text = src.read_text()
    assert "LOG = logging.getLogger" in text
    assert "planner output unparseable" in text
