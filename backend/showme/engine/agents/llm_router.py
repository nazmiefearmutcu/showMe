"""LLM Router — cheapest model that meets the reliability bar.

Provider chain (try in order, skip if no API key):
    Anthropic Haiku → Sonnet → Opus
    OpenAI    GPT-4o-mini → GPT-4o
    Mistral   small      → large

Budget cap: per-day $X via env LLM_DAILY_BUDGET_USD.
Logs every call to ``runtime/llm_calls.jsonl``.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from showme.app_paths import runtime_path


def _log_path():
    return runtime_path("llm_calls.jsonl")


@dataclass
class LLMRequest:
    role: str                       # "summarize", "plan", "search", "code", ...
    system: str = ""
    user: str = ""
    max_tokens: int = 1024
    temperature: float = 0.3
    risk_critical: bool = False
    expected_complexity: str = "low"  # "low"|"med"|"high"


@dataclass
class LLMResult:
    text: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    elapsed_ms: float = 0.0
    error: str | None = None


class LLMRouter:
    """Provider abstraction with cheapest-first routing."""

    # Approximate USD/1k tokens (haiku much cheaper, opus expensive)
    PRICING = {
        "claude-haiku":  {"input": 0.00025, "output": 0.00125},
        "claude-sonnet": {"input": 0.003,    "output": 0.015},
        "claude-opus":   {"input": 0.015,    "output": 0.075},
        "gpt-4o-mini":   {"input": 0.00015, "output": 0.0006},
        "gpt-4o":        {"input": 0.0025,  "output": 0.01},
    }

    def __init__(self) -> None:
        self.daily_budget = float(os.environ.get("LLM_DAILY_BUDGET_USD", "5"))
        self.spent_today = self._load_today_spend()
        self.anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        self.openai_key = os.environ.get("OPENAI_API_KEY")

    def _load_today_spend(self) -> float:
        if not _log_path().exists():
            return 0.0
        today = datetime.now(timezone.utc).date().isoformat()
        total = 0.0
        try:
            for line in _log_path().read_text().splitlines():
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if entry.get("date") == today:
                    total += float(entry.get("cost_usd", 0))
        except Exception:
            return 0.0
        return total

    def pick_model(self, req: LLMRequest) -> str:
        """Cheapest-first heuristic."""
        if req.risk_critical:
            if self.anthropic_key:
                return "claude-opus"
            if self.openai_key:
                return "gpt-4o"
        if req.expected_complexity == "high":
            if self.anthropic_key:
                return "claude-sonnet"
            if self.openai_key:
                return "gpt-4o"
        if self.anthropic_key:
            return "claude-haiku"
        if self.openai_key:
            return "gpt-4o-mini"
        return "no-llm"

    async def complete(self, req: LLMRequest) -> LLMResult:
        if self.spent_today >= self.daily_budget:
            return LLMResult(text="", model="budget-exceeded",
                             error=f"daily budget {self.daily_budget} USD exceeded")
        model = self.pick_model(req)
        if model == "no-llm":
            return LLMResult(text="", model="none", error="no LLM provider configured")
        t0 = time.monotonic()
        try:
            if model.startswith("claude"):
                text, in_t, out_t = await self._call_anthropic(model, req)
            elif model.startswith("gpt"):
                text, in_t, out_t = await self._call_openai(model, req)
            else:
                return LLMResult(text="", model=model, error="unknown model")
        except Exception as e:
            return LLMResult(text="", model=model, error=str(e),
                             elapsed_ms=(time.monotonic() - t0) * 1000)
        pricing = self.PRICING.get(model, {"input": 0, "output": 0})
        cost = (in_t * pricing["input"] + out_t * pricing["output"]) / 1000
        self.spent_today += cost
        result = LLMResult(text=text, model=model, tokens_in=in_t, tokens_out=out_t,
                            cost_usd=cost, elapsed_ms=(time.monotonic() - t0) * 1000)
        self._log(req, result)
        return result

    async def _call_anthropic(self, model: str, req: LLMRequest) -> tuple[str, int, int]:
        try:
            import anthropic  # type: ignore
        except Exception as e:
            raise RuntimeError(f"anthropic SDK missing: {e}")
        model_map = {
            "claude-haiku":  "claude-haiku-4-5-20251001",
            "claude-sonnet": "claude-sonnet-4-6",
            "claude-opus":   "claude-opus-4-7",
        }
        client = anthropic.AsyncAnthropic(api_key=self.anthropic_key)
        msg = await client.messages.create(
            model=model_map[model], max_tokens=req.max_tokens,
            system=req.system or "You are a precise financial assistant.",
            messages=[{"role": "user", "content": req.user}],
            temperature=req.temperature,
        )
        text = "".join(b.text for b in msg.content if hasattr(b, "text"))
        return text, msg.usage.input_tokens, msg.usage.output_tokens

    async def _call_openai(self, model: str, req: LLMRequest) -> tuple[str, int, int]:
        try:
            from openai import AsyncOpenAI  # type: ignore
        except Exception as e:
            raise RuntimeError(f"openai SDK missing: {e}")
        client = AsyncOpenAI(api_key=self.openai_key)
        r = await client.chat.completions.create(
            model=model, max_tokens=req.max_tokens, temperature=req.temperature,
            messages=[
                {"role": "system", "content": req.system or "You are a precise financial assistant."},
                {"role": "user", "content": req.user},
            ],
        )
        text = r.choices[0].message.content or ""
        return text, r.usage.prompt_tokens, r.usage.completion_tokens

    def _log(self, req: LLMRequest, res: LLMResult) -> None:
        _log_path().parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "date": datetime.now(timezone.utc).date().isoformat(),
            "role": req.role, "model": res.model,
            "tokens_in": res.tokens_in, "tokens_out": res.tokens_out,
            "cost_usd": res.cost_usd, "elapsed_ms": res.elapsed_ms,
            "error": res.error,
        }
        with _log_path().open("a") as f:
            f.write(json.dumps(entry) + "\n")
