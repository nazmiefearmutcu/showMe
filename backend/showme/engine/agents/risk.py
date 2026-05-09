"""Risk Agent — VaR/ETL/scenario stress before sensitive actions."""

from __future__ import annotations


from showme.engine.core.base_agent import AgentResult, AgentTask, BaseAgent


class RiskAgent(BaseAgent):
    name = "risk"
    description = "Computes VaR/ETL/stress and gates risk-critical actions."

    async def run(self, task: AgentTask) -> AgentResult:
        # Delegate to PORT function for now.
        from showme.engine.functions.portfolio.port import PORTFunction
        port_fn = PORTFunction(self.deps)
        res = await port_fn.execute()
        return AgentResult(agent=self.name, task=task, output=res.to_dict())
