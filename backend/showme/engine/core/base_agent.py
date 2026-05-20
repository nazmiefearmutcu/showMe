"""BaseAgent ABC — building block for the ASKB-style agent network.

Each agent (Planner, Search, Code, Summarizer, Viz, Execution, Risk, News)
inherits this. Agents communicate through ``AgentTask`` envelopes and
return ``AgentResult`` objects so the orchestrator can compose DAGs.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from showme.engine.utils.helpers import datetime_now


@dataclass
class AgentTask:
    """A unit of work handed to an agent."""
    role: str                              # "planner","search","summarize"...
    instruction: str                       # the actual prompt / query
    context: dict[str, Any] = field(default_factory=dict)
    inputs: dict[str, Any] = field(default_factory=dict)
    parent_id: str | None = None
    task_id: str | None = None
    deadline_seconds: float = 60.0
    priority: int = 0


@dataclass
class AgentResult:
    """Outcome of an agent run."""
    agent: str
    task: AgentTask
    output: Any = None
    citations: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    model: str | None = None
    elapsed_ms: float | None = None
    error: str | None = None
    timestamp: datetime = field(default_factory=datetime_now)

    @property
    def ok(self) -> bool:
        return self.error is None


class BaseAgent(ABC):
    """Abstract agent."""
    name: str = "base"
    description: str = ""
    default_model: str = "haiku"

    def __init__(self, deps: Any | None = None) -> None:
        self.deps = deps

    @abstractmethod
    async def run(self, task: AgentTask) -> AgentResult: ...

    async def run_timed(self, task: AgentTask) -> AgentResult:
        t0 = time.perf_counter()
        try:
            result = await self.run(task)
        except Exception as e:
            result = AgentResult(agent=self.name, task=task, error=str(e))
        result.elapsed_ms = (time.perf_counter() - t0) * 1000
        return result
