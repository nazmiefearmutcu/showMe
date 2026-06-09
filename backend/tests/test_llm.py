"""Round 26 — LLM planner contract + cost ledger."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from showme.llm import (
    CostCapExceeded,
    CostEntry,
    CostLedger,
    LlmPlannerError,
    Provider,
    cost_for,
    llm_plan_for,
    parse_plan_response,
    plan_for_smart,
)


def _stub_provider(payload: dict[str, str | int]) -> Provider:
    async def _call(envelope: dict[str, object]) -> dict[str, object]:
        return dict(payload)

    return Provider(name="anthropic", model="claude-haiku-4-5", call=_call)


def test_cost_for_uses_published_anthropic_pricing() -> None:
    # 1M input + 1M output at the Haiku rate ⇒ $1 + $5 = $6.
    assert cost_for("anthropic", "claude-haiku-4-5", 1_000_000, 1_000_000) == pytest.approx(6.0)


def test_cost_for_falls_back_for_unknown_models() -> None:
    # Conservative high estimate so we err toward fallback.
    cheap = cost_for("anthropic", "claude-haiku-4-5", 1_000, 0)
    fallback = cost_for("openai", "gpt-99", 1_000, 0)
    assert fallback > cheap


def test_parse_plan_response_strips_markdown_fence() -> None:
    raw = '```json\n{"intent":"scan","action":"x","agents":[],"args":{}}\n```'
    out = parse_plan_response(raw)
    assert out["intent"] == "scan"


def test_parse_plan_response_rejects_missing_keys() -> None:
    with pytest.raises(LlmPlannerError):
        parse_plan_response('{"intent":"scan"}')


def test_ledger_round_trips_through_disk(tmp_path: Path) -> None:
    p = tmp_path / "costs.json"
    led = CostLedger(path=p)
    led.append(CostEntry(
        ts="2026-05-01T00:00:00+00:00",
        provider="anthropic",
        model="claude-haiku-4-5",
        input_tokens=100,
        output_tokens=10,
        usd=0.0001,
    ))
    led.save()
    re = CostLedger.load(p)
    assert len(re.entries) == 1
    assert re.entries[0].usd == 0.0001


def test_today_spend_only_counts_today(tmp_path: Path) -> None:
    p = tmp_path / "costs.json"
    led = CostLedger(path=p)
    from datetime import date
    today = date.today().isoformat()
    led.append(CostEntry(ts="2024-01-01T00:00:00+00:00",
                         provider="x", model="y", input_tokens=0, output_tokens=0, usd=0.5))
    led.append(CostEntry(ts=f"{today}T00:00:00+00:00",
                         provider="x", model="y", input_tokens=0, output_tokens=0, usd=0.04))
    assert led.today_spend() == pytest.approx(0.04)


def test_llm_plan_for_records_cost_on_success(tmp_path: Path) -> None:
    led = CostLedger(path=tmp_path / "costs.json")
    provider = _stub_provider({
        "plan_json": json.dumps({
            "intent": "scan",
            "action": "Run scanner with crypto majors",
            "rationale": "user mentioned BTC",
            "agents": ["search", "summarizer", "viz"],
            "args": {"asset_class": "CRYPTO", "phases": "A,B,C,D", "top_n": 10},
        }),
        "input_tokens": 800,
        "output_tokens": 200,
    })
    plan, entry = asyncio.run(
        llm_plan_for(
            "find me overextended crypto majors",
            providers=[provider],
            ledger=led,
        )
    )
    assert plan.intent == "scan"
    assert plan.args["asset_class"] == "CRYPTO"
    assert entry.input_tokens == 800
    assert entry.usd == pytest.approx(cost_for("anthropic", "claude-haiku-4-5", 800, 200))
    assert (tmp_path / "costs.json").exists()


def test_llm_plan_for_falls_back_to_second_provider(tmp_path: Path) -> None:
    failing = Provider(
        name="anthropic",
        model="claude-haiku-4-5",
        call=lambda envelope: _raise(LlmPlannerError("503")),
    )
    succeeding = _stub_provider({
        "plan_json": json.dumps({
            "intent": "function",
            "action": "DES on AAPL",
            "agents": ["search"],
            "args": {"code": "DES", "symbols": ["AAPL"]},
        }),
        "input_tokens": 200,
        "output_tokens": 30,
    })
    led = CostLedger(path=tmp_path / "costs.json")
    plan, entry = asyncio.run(
        llm_plan_for("show me DES on AAPL", providers=[failing, succeeding], ledger=led)
    )
    assert plan.intent == "function"
    assert entry.provider == "anthropic"


def test_llm_plan_for_raises_when_cap_already_hit(tmp_path: Path) -> None:
    led = CostLedger(path=tmp_path / "costs.json")
    from datetime import date
    today = date.today().isoformat()
    led.append(CostEntry(ts=f"{today}T00:00:00+00:00",
                         provider="x", model="y", input_tokens=0, output_tokens=0, usd=10.0))
    with pytest.raises(CostCapExceeded):
        asyncio.run(
            llm_plan_for("anything", providers=[_stub_provider({})], ledger=led)
        )


def test_plan_for_smart_falls_back_to_deterministic_when_no_providers() -> None:
    plan, entry = asyncio.run(
        plan_for_smart("show me FA on AAPL", providers=[], function_codes={"FA", "DES"})
    )
    # Deterministic planner classifies this as a function intent on AAPL.
    assert plan.args.get("symbols") == ["AAPL"]
    assert plan.args.get("code") == "FA"
    # No LLM ran ⇒ no CostEntry threaded back.
    assert entry is None


def test_plan_for_smart_uses_llm_when_provider_succeeds(tmp_path: Path) -> None:
    led = CostLedger(path=tmp_path / "costs.json")
    provider = _stub_provider({
        "plan_json": json.dumps({
            "intent": "briefing",
            "action": "morning briefing",
            "agents": ["fanout", "summarizer", "viz"],
            "args": {},
        }),
        "input_tokens": 50,
        "output_tokens": 50,
    })
    plan, entry = asyncio.run(plan_for_smart("morning briefing", providers=[provider], ledger=led))
    assert plan.intent == "briefing"
    assert "fanout" in plan.agents
    # The succeeding provider's CostEntry is threaded back for honest provenance.
    assert entry is not None
    assert entry.provider == "anthropic"
    assert entry.model == "claude-haiku-4-5"


def test_plan_for_smart_retries_deterministic_when_llm_returns_invalid_json(
    tmp_path: Path,
) -> None:
    bad = _stub_provider({"plan_json": "not-json", "input_tokens": 0, "output_tokens": 0})
    led = CostLedger(path=tmp_path / "costs.json")
    plan, entry = asyncio.run(plan_for_smart("scan oversold tech", providers=[bad], ledger=led))
    assert plan.intent == "scan"  # deterministic fallback still classifies it
    assert entry is None  # all providers failed ⇒ deterministic, no entry


def _raise(exc: Exception):
    async def _impl(_: dict[str, object]) -> dict[str, object]:
        raise exc

    return _impl
