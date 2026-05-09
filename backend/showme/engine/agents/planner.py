"""Planner Agent — converts a user query into a DAG of agent calls."""

from __future__ import annotations

from typing import Any

from showme.engine.agents.llm_router import LLMRequest, LLMRouter
from showme.engine.core.base_agent import AgentResult, AgentTask, BaseAgent


_PLAN_SYSTEM = """You are a planning agent for a Bloomberg-class trading terminal.
Given a user query, output a JSON list of agent calls:
[{"agent":"search|code|summarize|viz|execution|risk|news",
   "instruction":"…","inputs":{…},"depends_on":[indices…]}, …]
Use the cheapest agent that solves the step. Use the search agent for fetching
ShowMe data via functions. Use the summarizer for natural-language outputs."""


class PlannerAgent(BaseAgent):
    name = "planner"
    description = "Converts user query → DAG of agent calls."

    def __init__(self, deps: Any | None = None, router: LLMRouter | None = None) -> None:
        super().__init__(deps)
        self.router = router or LLMRouter()

    async def run(self, task: AgentTask) -> AgentResult:
        req = LLMRequest(
            role="planner", system=_PLAN_SYSTEM, user=task.instruction,
            max_tokens=600, temperature=0.0,
        )
        r = await self.router.complete(req)
        return AgentResult(
            agent=self.name, task=task, output=r.text,
            cost_usd=r.cost_usd, tokens_in=r.tokens_in, tokens_out=r.tokens_out,
            model=r.model, error=r.error,
        )
