"""Tests for the ASKB orchestrator (showme/agents/orchestrator.py)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from showme.agents.orchestrator import (  # noqa: E402
    AskRequest,
    ask,
    _function_codes,
    _extract_rows_for_evidence,
    _evidence_row_label,
)


@pytest.mark.asyncio
async def test_ask_basic_flow():
    req = AskRequest(query="test query")
    deps = MagicMock()

    with patch("showme.agents.orchestrator.plan_for") as mock_plan_for, \
         patch("showme.agents.orchestrator.run_search", new_callable=AsyncMock) as mock_run_search, \
         patch("showme.agents.orchestrator.summarize") as mock_summarize, \
         patch("showme.agents.orchestrator.pick_viz") as mock_pick_viz, \
         patch("showme.agents.orchestrator.build_default_providers", return_value=None):

        mock_plan = MagicMock()
        mock_plan.intent = "scan"
        mock_plan.agents = ["search", "summarizer", "viz"]
        mock_plan.to_dict.return_value = {"intent": "scan"}
        mock_plan_for.return_value = mock_plan

        mock_run_search.return_value = {
            "kind": "scan",
            "data": {"rows": [{"symbol": "BTC/USDT"}]},
            "warnings": ["warning search"],
        }
        mock_summarize.return_value = {
            "narrative": "test narrative",
            "highlights": [{"label": "test", "value": 1}],
            "warnings": ["warning summary"],
        }
        mock_pick_viz.return_value = {"kind": "table"}

        resp = await ask(req, deps)

        assert resp.query == "test query"
        assert resp.narrative == "test narrative"
        assert resp.viz == {"kind": "table"}
        assert len(resp.phases) == 4  # plan, search, summarize, viz
        assert "warning search" in resp.warnings
        assert "warning summary" in resp.warnings

        # Check serialization
        d = resp.to_dict()
        assert d["query"] == "test query"
        assert d["plan"] == {"intent": "scan"}
        assert isinstance(d["phases"], list)
        assert d["phases"][0]["name"] == "plan"


@pytest.mark.asyncio
async def test_ask_llm_augmented_planner():
    req = AskRequest(query="smart query")
    deps = MagicMock()

    with patch("showme.agents.orchestrator.plan_for_smart", new_callable=AsyncMock) as mock_plan_for_smart, \
         patch("showme.agents.orchestrator.run_search", new_callable=AsyncMock) as mock_run_search, \
         patch("showme.agents.orchestrator.build_default_providers", return_value=["dummy_provider"]):

        mock_plan = MagicMock()
        mock_plan.intent = "scan"
        mock_plan.agents = ["search"]
        mock_plan.to_dict.return_value = {"intent": "scan"}
        mock_plan_for_smart.return_value = mock_plan

        mock_run_search.return_value = {"kind": "scan"}

        resp = await ask(req, deps)
        assert resp.query == "smart query"
        assert len(resp.phases) == 2  # plan, search
        mock_plan_for_smart.assert_called_once()


@pytest.mark.asyncio
async def test_ask_fanout_flow():
    req = AskRequest(query="briefing query")
    deps = MagicMock()

    with patch("showme.agents.orchestrator.plan_for") as mock_plan_for, \
         patch("showme.agents.orchestrator.run_search", new_callable=AsyncMock) as mock_run_search, \
         patch("showme.agents.orchestrator.build_default_providers", return_value=None):

        mock_plan = MagicMock()
        mock_plan.intent = "briefing"
        mock_plan.agents = ["fanout"]
        mock_plan.to_dict.return_value = {"intent": "briefing"}
        mock_plan_for.return_value = mock_plan

        # run_search will be called three times for the fanout branches (portfolio, scan, news)
        mock_run_search.return_value = {
            "kind": "mock_branch",
            "data": {"rows": [{"symbol": "BTC/USDT"}]},
            "warnings": ["branch warning"],
        }

        resp = await ask(req, deps)
        assert resp.query == "briefing query"
        assert len(resp.phases) == 2  # plan, fanout
        assert resp.search["kind"] == "fanout"
        assert "portfolio" in resp.search["branch_names"]
        assert "scan" in resp.search["branch_names"]
        assert "news" in resp.search["branch_names"]


@pytest.mark.asyncio
async def test_ask_fanout_timeout_and_error():
    req = AskRequest(query="briefing query")
    deps = MagicMock()

    with patch("showme.agents.orchestrator.plan_for") as mock_plan_for, \
         patch("showme.agents.orchestrator.run_search", new_callable=AsyncMock) as mock_run_search, \
         patch("showme.agents.orchestrator.build_default_providers", return_value=None):

        mock_plan = MagicMock()
        mock_plan.intent = "briefing"
        mock_plan.agents = ["fanout"]
        mock_plan.to_dict.return_value = {"intent": "briefing"}
        mock_plan_for.return_value = mock_plan

        # We simulate a failure on the news branch, and timeout/other errors
        async def mock_search_side_effect(plan, deps):
            if "news" in plan.action:
                raise ValueError("news failed")
            elif "scan" in plan.action:
                import asyncio
                await asyncio.sleep(10.0)  # Trigger timeout
            return {"kind": "ok", "data": []}

        mock_run_search.side_effect = mock_search_side_effect

        with patch("asyncio.wait_for", side_effect=[{"kind": "ok"}, TimeoutError(), ValueError("news failed")]):
            resp = await ask(req, deps)
            assert resp.search["kind"] == "fanout"
            assert "scan: timed out after 8.0s" in resp.warnings
            assert "news: news failed" in resp.warnings


def test_function_codes_registry_failure():
    with patch("importlib.import_module", side_effect=ImportError("mock import error")):
        codes = _function_codes()
        assert codes == set()


def test_extract_rows_for_evidence():
    # Empty
    assert _extract_rows_for_evidence(None) == []
    # List of dicts
    data_list = [{"symbol": "BTC/USDT"}, "not a dict"]
    assert _extract_rows_for_evidence(data_list) == [{"symbol": "BTC/USDT"}]
    # Dict with "rows"
    assert _extract_rows_for_evidence({"rows": [{"symbol": "ETH/USDT"}]}) == [{"symbol": "ETH/USDT"}]
    # Dict with "items"
    assert _extract_rows_for_evidence({"items": [{"symbol": "SOL/USDT"}]}) == [{"symbol": "SOL/USDT"}]
    # Dict with nested dict
    assert _extract_rows_for_evidence({"data": {"rows": [{"symbol": "ADA/USDT"}]}}) == [{"symbol": "ADA/USDT"}]


def test_evidence_row_label():
    assert _evidence_row_label({"symbol": "BTC/USDT"}) == "BTC/USDT"
    assert _evidence_row_label({"title": "News Title"}) == "News Title"
    assert _evidence_row_label({"headline": "Headline Text"}) == "Headline Text"
    assert _evidence_row_label({"name": "Asset Name"}) == "Asset Name"
    assert _evidence_row_label({"event": "Signal Event"}) == "Signal Event"
    assert _evidence_row_label({"code": "TEST_CODE"}) == "TEST_CODE"
    assert _evidence_row_label({"k1": "v1", "k2": "v2"}) == "k1=v1, k2=v2"
