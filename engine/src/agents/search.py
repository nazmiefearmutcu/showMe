"""Search Agent — looks up data via ShowMe functions."""

from __future__ import annotations

from typing import Any

from src.core.base_agent import AgentResult, AgentTask, BaseAgent
from src.core.base_function import FunctionRegistry


class SearchAgent(BaseAgent):
    name = "search"
    description = "Looks up ShowMe functions by code, executes, returns FunctionResult."

    async def run(self, task: AgentTask) -> AgentResult:
        code = (task.inputs.get("function_code") or "").upper()
        symbol = task.inputs.get("symbol")
        params = task.inputs.get("params") or {}
        fn_cls = FunctionRegistry.get(code)
        if fn_cls is None:
            return AgentResult(agent=self.name, task=task, error=f"unknown function {code}")
        instrument = None
        if symbol and self.deps and self.deps.symbol_registry:
            instrument = await self.deps.symbol_registry.resolve(symbol)
        try:
            fn = fn_cls(self.deps)
            res = await fn.execute_timed(instrument=instrument, **params)
            return AgentResult(agent=self.name, task=task,
                                output=res.to_dict(), citations=list(res.sources))
        except Exception as e:
            return AgentResult(agent=self.name, task=task, error=str(e))
