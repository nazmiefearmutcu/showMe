"""Orchestrator — runs a Planner-produced DAG and aggregates results."""

from __future__ import annotations

import json
import logging
from typing import Any

from showme.engine.agents.code import CodeAgent
from showme.engine.agents.execution import ExecutionAgent
from showme.engine.agents.llm_router import LLMRouter
from showme.engine.agents.news import NewsAgent
from showme.engine.agents.planner import PlannerAgent
from showme.engine.agents.risk import RiskAgent
from showme.engine.agents.search import SearchAgent
from showme.engine.agents.summarizer import SummarizerAgent
from showme.engine.agents.viz import VizAgent
from showme.engine.core.base_agent import AgentResult, AgentTask

LOG = logging.getLogger("showme.engine.agents.orchestrator")


class Orchestrator:
    def __init__(self, deps: Any | None = None, router: LLMRouter | None = None) -> None:
        self.deps = deps
        self.router = router or LLMRouter()
        self.planner = PlannerAgent(deps, self.router)
        self.agents: dict[str, Any] = {
            "search":     SearchAgent(deps),
            "code":       CodeAgent(deps),
            "summarize":  SummarizerAgent(deps, self.router),
            "viz":        VizAgent(deps),
            "execution":  ExecutionAgent(deps, self.router),
            "risk":       RiskAgent(deps),
            "news":       NewsAgent(deps),
        }

    async def handle(self, query: str) -> dict[str, Any]:
        plan_task = AgentTask(role="planner", instruction=query)
        plan_res = await self.planner.run(plan_task)
        steps = self._parse_plan(plan_res.output or "")
        if not steps:
            # Fallback: ask summariser directly.
            s = await self.agents["summarize"].run(AgentTask(role="summarize", instruction=query))
            return {"steps": [], "result": s.output, "cost_usd": (plan_res.cost_usd or 0) + (s.cost_usd or 0)}
        results: dict[int, AgentResult] = {}
        cost_total = plan_res.cost_usd or 0
        for idx, step in enumerate(steps):
            agent_name = step.get("agent", "search")
            agent = self.agents.get(agent_name)
            if agent is None:
                continue
            t = AgentTask(role=agent_name, instruction=step.get("instruction", ""),
                           inputs=step.get("inputs", {}))
            r = await agent.run(t)
            results[idx] = r
            cost_total += r.cost_usd or 0
        return {
            "plan": steps,
            "results": [r.output for r in results.values()],
            "cost_usd": cost_total,
        }

    @staticmethod
    def _parse_plan(text: str) -> list[dict[str, Any]]:
        text = text.strip()
        if not text:
            return []
        # Best-effort: extract JSON list
        try:
            start = text.find("[")
            end = text.rfind("]")
            if start >= 0 and end > start:
                return json.loads(text[start : end + 1])
        except Exception:  # noqa: BLE001
            # QA-fix: log parse failures so the orchestrator no longer
            # silently falls through to summariser when the planner returns
            # malformed JSON.
            LOG.warning(
                "planner output unparseable; falling back to summariser-only path",
                exc_info=True,
            )
            return []
        return []
