"""Execution Agent — places orders via ShowMe broker layer with verification pass."""

from __future__ import annotations

from typing import Any

from showme.engine.agents.llm_router import LLMRequest, LLMRouter
from showme.engine.core.base_agent import AgentResult, AgentTask, BaseAgent
from showme.engine.core.broker import BrokerOrder, OrderSide, OrderType, TimeInForce


class ExecutionAgent(BaseAgent):
    name = "execution"
    description = "Risk-critical: routes orders through verification pass."

    def __init__(self, deps: Any | None = None, router: LLMRouter | None = None) -> None:
        super().__init__(deps)
        self.router = router or LLMRouter()

    async def run(self, task: AgentTask) -> AgentResult:
        spec = task.inputs.get("order") or {}
        # Verification pass: ask Opus / GPT-4o whether order makes sense.
        verify_prompt = (
            f"Order spec: {spec}\n"
            "Reply with one of YES_OK or NO with one-line reason."
        )
        v = await self.router.complete(LLMRequest(
            role="risk_verify", system="Trading risk reviewer.",
            user=verify_prompt, max_tokens=120, risk_critical=True,
        ))
        if not v.text or "NO" in v.text.upper().split():
            return AgentResult(agent=self.name, task=task,
                                output={"status": "rejected", "reason": v.text or "no LLM"})
        # Look up broker, place order.
        broker = task.inputs.get("broker") or "binance_broker"
        b = getattr(self.deps, broker, None)
        if b is None:
            return AgentResult(agent=self.name, task=task, error=f"broker {broker} not configured")
        from showme.engine.core.instrument import Instrument, AssetClass
        instrument = Instrument(
            symbol=spec["symbol"], asset_class=AssetClass(spec.get("asset_class", "EQUITY")),
            exchange=spec.get("exchange"),
        )
        order = BrokerOrder(
            instrument=instrument,
            side=OrderSide(spec["side"]), quantity=float(spec["quantity"]),
            order_type=OrderType(spec.get("type", "MARKET")),
            price=spec.get("price"),
            time_in_force=TimeInForce(spec.get("tif", "GTC")),
            leverage=spec.get("leverage"),
        )
        try:
            order_id = await b.place_order(order)
            return AgentResult(agent=self.name, task=task,
                                output={"status": "placed", "order_id": order_id, "broker": broker})
        except Exception as e:
            return AgentResult(agent=self.name, task=task, error=str(e))
