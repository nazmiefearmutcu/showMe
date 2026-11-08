"""News Agent — collects + summarizes."""

from __future__ import annotations


from showme.engine.agents.summarizer import SummarizerAgent
from showme.engine.core.base_agent import AgentResult, AgentTask, BaseAgent


class NewsAgent(BaseAgent):
    name = "news"

    async def run(self, task: AgentTask) -> AgentResult:
        from showme.engine.functions.news.top import TOPFunction
        # TOP answers a {status, rows, ...} dict; an unavailable Awareness answer
        # yields no rows, so the summary never sees invented headlines.
        top = await TOPFunction(self.deps).execute(q=task.instruction)
        top_data = top.data if isinstance(top.data, dict) else {}
        articles = [row for row in (top_data.get("rows") or [])[:10] if isinstance(row, dict)]
        # Summarise via LLM router
        summarizer = SummarizerAgent(self.deps)
        s_task = AgentTask(role="summarize",
                            instruction="Summarise these headlines in 5 bullet points.",
                            inputs={"articles": [a.get("title") for a in articles]})
        summ = await summarizer.run(s_task)
        return AgentResult(agent=self.name, task=task,
                            output={"summary": summ.output, "articles": articles},
                            cost_usd=summ.cost_usd, model=summ.model)
