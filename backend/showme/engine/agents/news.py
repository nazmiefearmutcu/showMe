"""News Agent — collects + summarizes."""

from __future__ import annotations


from showme.engine.agents.summarizer import SummarizerAgent
from showme.engine.core.base_agent import AgentResult, AgentTask, BaseAgent


class NewsAgent(BaseAgent):
    name = "news"

    async def run(self, task: AgentTask) -> AgentResult:
        from showme.engine.functions.news.top import TOPFunction
        top = await TOPFunction(self.deps).execute(query=task.instruction)
        articles = (top.data or [])[:10]
        # Summarise via LLM router
        summarizer = SummarizerAgent(self.deps)
        s_task = AgentTask(role="summarize",
                            instruction="Summarise these headlines in 5 bullet points.",
                            inputs={"articles": [a.get("title") for a in articles]})
        summ = await summarizer.run(s_task)
        return AgentResult(agent=self.name, task=task,
                            output={"summary": summ.output, "articles": articles},
                            cost_usd=summ.cost_usd, model=summ.model)
