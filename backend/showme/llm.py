"""LLM planner — natural language → Plan, with cost ledger.

Round 26 wires Anthropic Haiku (primary) + OpenAI GPT-4o-mini (fallback)
into the planner pipeline. The provider HTTP transport is injected so
unit tests can drive the contract without an API key.

Cost protection:
    * Per-call charges are computed from the published per-million-token
      prices and recorded in a JSON ledger under
      ``~/Library/Application Support/showMe/data/llm_costs.json``.
    * Before each call we read the ledger; if today's tally has already
      met or exceeded the cap (default $1.00, override via
      ``SHOWME_LLM_DAILY_USD``) the call short-circuits.
    * The deterministic planner remains the safety net: any LLM error or
      cap hit triggers ``plan_for_smart`` to fall back to ``plan_for``.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from collections.abc import Awaitable, Callable, Iterable

from .agents.planner import Plan, plan_for

LOG = logging.getLogger("showme.llm")

# ── Pricing (per 1M tokens, USD) — kept local so we don't hit a network ──
PRICING: dict[str, tuple[float, float]] = {
    # provider:model → (input, output)
    "anthropic:claude-haiku-4-5": (1.00, 5.00),
    "anthropic:claude-haiku-4-5-20251001": (1.00, 5.00),
    "openai:gpt-4o-mini": (0.15, 0.60),
}

DEFAULT_DAILY_CAP_USD = 1.00


# ── Errors ────────────────────────────────────────────────────────────────


class LlmPlannerError(RuntimeError):
    """All providers failed (or none configured)."""


class CostCapExceeded(RuntimeError):
    """Today's spend already met the cap; callers should fall back."""


# ── Cost ledger ───────────────────────────────────────────────────────────

@dataclass
class CostEntry:
    ts: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    usd: float
    purpose: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "usd": round(self.usd, 6),
            "purpose": self.purpose,
        }


@dataclass
class CostLedger:
    path: Path
    entries: list[CostEntry] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None = None) -> "CostLedger":
        target = path or default_ledger_path()
        if not target.exists():
            return cls(path=target)
        try:
            blob = json.loads(target.read_text())
            entries = [
                CostEntry(
                    ts=e.get("ts", ""),
                    provider=e.get("provider", ""),
                    model=e.get("model", ""),
                    input_tokens=int(e.get("input_tokens") or 0),
                    output_tokens=int(e.get("output_tokens") or 0),
                    usd=float(e.get("usd") or 0.0),
                    purpose=e.get("purpose") or "",
                )
                for e in blob.get("entries", [])
            ]
            return cls(path=target, entries=entries)
        except Exception as exc:  # noqa: BLE001 — corrupt ledger should not crash planner
            LOG.warning("ledger %s unreadable, starting fresh: %s", target, exc)
            return cls(path=target)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(
            {"entries": [e.to_dict() for e in self.entries]},
            indent=2,
        ))

    def append(self, entry: CostEntry) -> None:
        self.entries.append(entry)

    def today_spend(self) -> float:
        today = date.today().isoformat()
        return sum(e.usd for e in self.entries if e.ts.startswith(today))


def default_ledger_path() -> Path:
    return Path.home() / "Library/Application Support/showMe/data/llm_costs.json"


def daily_cap_usd() -> float:
    raw = os.environ.get("SHOWME_LLM_DAILY_USD")
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            return DEFAULT_DAILY_CAP_USD
    return DEFAULT_DAILY_CAP_USD


def cost_for(provider: str, model: str, in_tokens: int, out_tokens: int) -> float:
    key = f"{provider}:{model}".lower()
    pricing = PRICING.get(key)
    if pricing is None:
        # Unknown model → conservative high estimate so we don't undercharge.
        pricing = (3.0, 15.0)
    in_p, out_p = pricing
    return (in_tokens / 1_000_000.0) * in_p + (out_tokens / 1_000_000.0) * out_p


# ── Provider transports (injectable) ──────────────────────────────────────

ProviderCall = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
"""Coroutine taking the prompt envelope, returning {plan_json, in_tokens, out_tokens}."""


@dataclass
class Provider:
    name: str            # "anthropic" or "openai"
    model: str           # e.g. "claude-haiku-4-5"
    call: ProviderCall   # coroutine implementation


# ── Planner contract ──────────────────────────────────────────────────────

PLANNER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["intent", "action", "agents", "args"],
    "properties": {
        "intent": {"type": "string"},
        "action": {"type": "string"},
        "rationale": {"type": "string"},
        "agents": {"type": "array", "items": {"type": "string"}},
        "args": {"type": "object"},
    },
}


def _system_prompt(function_codes: Iterable[str] | None) -> str:
    codes = sorted(function_codes or [])
    code_hint = ", ".join(codes[:30]) if codes else "(none)"
    return (
        "You are showMe's plan dispatcher. Translate the user's natural-"
        "language request into a JSON object that conforms to the showMe "
        "Plan schema:\n\n"
        '{"intent": str, "action": str, "rationale": str, '
        '"agents": [str], "args": {str: any}}\n\n'
        "Allowed intents: scan, portfolio_overview, function, lookup, "
        "compare, news, briefing, unknown.\n"
        "Allowed agents: search, summarizer, viz, fanout.\n"
        f"Available function codes: {code_hint}.\n\n"
        "Return ONLY the JSON object, no surrounding prose."
    )


def parse_plan_response(payload: str) -> dict[str, Any]:
    """Strip markdown code fences, parse JSON, validate required keys."""
    raw = payload.strip()
    if raw.startswith("```"):
        # Optional language tag, e.g. ```json
        first_newline = raw.find("\n")
        if first_newline != -1:
            raw = raw[first_newline + 1:]
        if raw.endswith("```"):
            raw = raw[: -3]
    raw = raw.strip()
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise LlmPlannerError(f"plan response not an object: {type(obj).__name__}")
    for key in ("intent", "action", "agents", "args"):
        if key not in obj:
            raise LlmPlannerError(f"plan response missing key: {key}")
    if not isinstance(obj["agents"], list):
        raise LlmPlannerError("plan.agents must be a list")
    if not isinstance(obj["args"], dict):
        raise LlmPlannerError("plan.args must be an object")
    return obj


# ── High-level entry points ───────────────────────────────────────────────

async def llm_plan_for(
    query: str,
    *,
    function_codes: Iterable[str] | None = None,
    providers: list[Provider] | None = None,
    ledger: CostLedger | None = None,
    purpose: str = "planner",
) -> tuple[Plan, CostEntry]:
    """Run the LLM planner; raise on failure (caller falls back)."""
    text = (query or "").strip()
    if not text:
        raise LlmPlannerError("empty query")
    ledger = ledger or CostLedger.load()
    cap = daily_cap_usd()
    spent = ledger.today_spend()
    if spent >= cap:
        raise CostCapExceeded(f"daily cap exhausted: {spent:.4f} ≥ {cap:.2f}")
    if not providers:
        raise LlmPlannerError("no providers configured")
    last_err: Exception | None = None
    for prov in providers:
        try:
            envelope = {
                "system": _system_prompt(function_codes),
                "user": text,
                "model": prov.model,
            }
            res = await prov.call(envelope)
            plan_dict = parse_plan_response(res["plan_json"])
            in_tokens = int(res.get("input_tokens") or 0)
            out_tokens = int(res.get("output_tokens") or 0)
            usd = cost_for(prov.name, prov.model, in_tokens, out_tokens)
            entry = CostEntry(
                ts=datetime.now(tz=timezone.utc).isoformat(),
                provider=prov.name,
                model=prov.model,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                usd=usd,
                purpose=purpose,
            )
            ledger.append(entry)
            ledger.save()
            return Plan(
                intent=str(plan_dict["intent"]),
                action=str(plan_dict["action"]),
                rationale=str(plan_dict.get("rationale", "")),
                args=dict(plan_dict["args"]),
                agents=list(plan_dict["agents"]),
            ), entry
        except Exception as exc:  # noqa: BLE001
            LOG.warning("provider %s failed: %s", prov.name, exc)
            last_err = exc
            continue
    raise LlmPlannerError(f"all providers failed: {last_err}")


async def plan_for_smart(
    query: str,
    *,
    function_codes: Iterable[str] | None = None,
    providers: list[Provider] | None = None,
    ledger: CostLedger | None = None,
) -> Plan:
    """Try LLM, fall back to deterministic planner on any error/cap hit."""
    if providers:
        try:
            plan, _ = await llm_plan_for(
                query,
                function_codes=function_codes,
                providers=providers,
                ledger=ledger,
            )
            return plan
        except (LlmPlannerError, CostCapExceeded) as exc:
            LOG.info("LLM planner skipped (%s); using deterministic fallback", exc)
        except Exception as exc:  # noqa: BLE001 — never let LLM faults break /api/ask
            LOG.warning("LLM planner crashed (%s); falling back", exc)
    return plan_for(query, function_codes=set(function_codes or []))


# ── Provider builders (real network) ─────────────────────────────────────

def build_default_providers() -> list[Provider]:
    """Build providers from environment.

    Honors:
      * ``ANTHROPIC_API_KEY`` → Haiku 4.5 (latest at time of writing).
      * ``OPENAI_API_KEY``   → GPT-4o-mini.
    Returns an empty list if neither is configured (planner falls back).
    """
    out: list[Provider] = []
    if os.environ.get("ANTHROPIC_API_KEY"):
        out.append(Provider(
            name="anthropic",
            model=os.environ.get("SHOWME_LLM_HAIKU_MODEL", "claude-haiku-4-5"),
            call=_anthropic_call,
        ))
    if os.environ.get("OPENAI_API_KEY"):
        out.append(Provider(
            name="openai",
            model=os.environ.get("SHOWME_LLM_OPENAI_MODEL", "gpt-4o-mini"),
            call=_openai_call,
        ))
    return out


async def _anthropic_call(envelope: dict[str, Any]) -> dict[str, Any]:
    """Anthropic Messages API. Imports kept lazy so tests don't need httpx."""
    import httpx  # type: ignore
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise LlmPlannerError("ANTHROPIC_API_KEY missing")
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": envelope["model"],
        "max_tokens": 512,
        "system": envelope["system"],
        "messages": [{"role": "user", "content": envelope["user"]}],
    }
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post("https://api.anthropic.com/v1/messages",
                                headers=headers, json=body)
        res.raise_for_status()
        data = res.json()
    text = "".join(p.get("text", "") for p in data.get("content", []))
    usage = data.get("usage", {}) or {}
    return {
        "plan_json": text,
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
    }


async def _openai_call(envelope: dict[str, Any]) -> dict[str, Any]:
    import httpx  # type: ignore
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise LlmPlannerError("OPENAI_API_KEY missing")
    headers = {
        "authorization": f"Bearer {api_key}",
        "content-type": "application/json",
    }
    body = {
        "model": envelope["model"],
        "messages": [
            {"role": "system", "content": envelope["system"]},
            {"role": "user", "content": envelope["user"]},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post("https://api.openai.com/v1/chat/completions",
                                headers=headers, json=body)
        res.raise_for_status()
        data = res.json()
    text = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {}) or {}
    return {
        "plan_json": text,
        "input_tokens": int(usage.get("prompt_tokens") or 0),
        "output_tokens": int(usage.get("completion_tokens") or 0),
    }


# ── Time-helper exposed for unit tests / orchestrator instrumentation ──

def now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


__all__ = [
    "CostCapExceeded",
    "CostEntry",
    "CostLedger",
    "DEFAULT_DAILY_CAP_USD",
    "LlmPlannerError",
    "PRICING",
    "Provider",
    "ProviderCall",
    "build_default_providers",
    "cost_for",
    "daily_cap_usd",
    "default_ledger_path",
    "llm_plan_for",
    "now_iso",
    "parse_plan_response",
    "plan_for_smart",
]
