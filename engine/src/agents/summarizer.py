"""Summarizer Agent — turns raw data into prose."""

from __future__ import annotations

from typing import Any

from src.agents.llm_router import LLMRequest, LLMRouter
from src.core.base_agent import AgentResult, AgentTask, BaseAgent


class SummarizerAgent(BaseAgent):
    name = "summarizer"

    def __init__(self, deps: Any | None = None, router: LLMRouter | None = None) -> None:
        super().__init__(deps)
        self.router = router or LLMRouter()

    async def run(self, task: AgentTask) -> AgentResult:
        req = LLMRequest(
            role="summarize",
            system="You are a concise financial summarizer. Output Markdown.",
            user=task.instruction + "\n\nINPUTS:\n" + str(task.inputs)[:8000],
            max_tokens=800, temperature=0.2,
        )
        r = await self.router.complete(req)
        return AgentResult(
            agent=self.name, task=task, output=r.text,
            cost_usd=r.cost_usd, tokens_in=r.tokens_in, tokens_out=r.tokens_out,
            model=r.model, error=r.error,
        )
