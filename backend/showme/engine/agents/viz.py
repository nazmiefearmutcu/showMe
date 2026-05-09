"""Viz Agent — produces Plotly JSON or HTML chart code from data."""

from __future__ import annotations

import json

from showme.engine.core.base_agent import AgentResult, AgentTask, BaseAgent


class VizAgent(BaseAgent):
    name = "viz"

    async def run(self, task: AgentTask) -> AgentResult:
        chart_type = task.inputs.get("type", "line")
        data = task.inputs.get("data", {})
        # Skeleton — output a Plotly Figure dict.
        try:
            import plotly.graph_objects as go  # type: ignore
            fig = go.Figure()
            x = data.get("x", [])
            y = data.get("y", [])
            if chart_type == "line":
                fig.add_trace(go.Scatter(x=x, y=y, mode="lines"))
            elif chart_type == "bar":
                fig.add_trace(go.Bar(x=x, y=y))
            elif chart_type == "candlestick":
                fig.add_trace(go.Candlestick(
                    x=data.get("dates", []),
                    open=data.get("open", []), high=data.get("high", []),
                    low=data.get("low", []), close=data.get("close", []),
                ))
            return AgentResult(agent=self.name, task=task,
                                output=json.loads(fig.to_json()))
        except Exception as e:
            return AgentResult(agent=self.name, task=task, error=str(e))
