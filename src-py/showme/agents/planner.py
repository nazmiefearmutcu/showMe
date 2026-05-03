"""Planner — natural-language intent → execution plan.

Round 19 ships a deterministic, pattern-matching planner. When the
ShowMe `llm_router` is available *and* an API key is configured, the
orchestrator can call `plan_for_with_llm()` instead; that function lives
on the orchestrator side so the deterministic planner has zero
dependencies.

The contract — `Plan` shape — is the same in both worlds:
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any

# ── Plan vocabulary ───────────────────────────────────────────────────────

@dataclass
class Plan:
    intent: str
    """One of: scan / portfolio_overview / function / lookup / compare / news / unknown."""
    action: str
    """Human-readable rationale shown in the UI."""
    rationale: str = ""
    """Per-action structured arguments."""
    args: dict[str, Any] = field(default_factory=dict)
    """Names of agents to invoke (e.g. ['search', 'summarizer', 'viz'])."""
    agents: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Lexicon ──────────────────────────────────────────────────────────────

_TICKER = re.compile(r"\b[A-Z]{1,6}(?:USDT?)?\b")
_FUNCTION_CODE = re.compile(r"\b[A-Z]{2,6}\b")

_INTENT_PHRASES: list[tuple[str, str]] = [
    # (pattern, intent)
    (r"\b(brief|briefing|overview|what.?s\s+up|what should i watch|morning)\b", "briefing"),
    (r"\b(scan|find me|hunt|opportunit|overextend|pullback|breakout)\b", "scan"),
    (r"\b(portfolio|positions|book|exposure|holdings|risk)\b",            "portfolio_overview"),
    (r"\b(news|headline|sentiment|reaction|breaking)\b",                  "news"),
    (r"\b(compare|vs\.?|versus|difference between)\b",                    "compare"),
    (r"\b(what is|who is|describe|info on|tell me about)\b",              "lookup"),
    (r"\b(run|open|show me)\s+([A-Z]{2,6})\b",                            "function"),
]


# ── Public API ───────────────────────────────────────────────────────────

def plan_for(query: str, *, function_codes: set[str] | None = None) -> Plan:
    """Pure-Python planner. Returns a Plan no matter the input."""
    text = query.strip()
    if not text:
        return Plan(
            intent="unknown",
            action="empty_query",
            rationale="No query supplied.",
            agents=[],
        )
    norm = text.lower()
    intent = _classify_intent(norm)

    args: dict[str, Any] = {}
    rationale_parts: list[str] = []

    # Asset-class / universe hints (also surface them as Phase A inputs).
    asset_class = _asset_class_hint(norm)
    if asset_class:
        args["asset_class"] = asset_class
        rationale_parts.append(f"asset class: {asset_class}")

    # Pull explicit symbols (uppercase tokens).
    symbols = _extract_symbols(text, function_codes or set())
    if symbols:
        args["symbols"] = symbols
        rationale_parts.append(f"symbols: {', '.join(symbols)}")

    # Function code (e.g. "show me FA on AAPL").
    fn_code = _extract_function_code(text, function_codes or set())
    if fn_code:
        args["code"] = fn_code
        rationale_parts.append(f"function: {fn_code}")
        # Promote to function intent if not already set explicitly.
        if intent in ("unknown", "lookup"):
            intent = "function"

    # Direction keyword (LONG / SHORT bias for scans).
    direction = _direction_hint(norm)
    if direction:
        args["direction"] = direction
        rationale_parts.append(f"direction bias: {direction}")

    # Phases for scan intents — fine + risk by default.
    if intent == "scan":
        args.setdefault("phases", "A,B,C,D")
        args.setdefault("top_n", 12)

    # Fallback: unknown intent + a symbol → lookup the symbol on DES.
    if intent == "unknown" and symbols:
        intent = "lookup"
        rationale_parts.append("fallback: unknown intent + symbols → lookup")

    agents = _agents_for(intent)

    rationale = "; ".join(rationale_parts) if rationale_parts else f"intent: {intent}"
    return Plan(
        intent=intent,
        action=_action_for(intent, args),
        rationale=rationale,
        args=args,
        agents=agents,
    )


# ── Internals ────────────────────────────────────────────────────────────

def _classify_intent(norm: str) -> str:
    for pattern, intent in _INTENT_PHRASES:
        if re.search(pattern, norm):
            return intent
    return "unknown"


def _asset_class_hint(norm: str) -> str | None:
    if any(k in norm for k in ("crypto", "bitcoin", "btc", "ethereum", "eth")):
        return "CRYPTO"
    if any(k in norm for k in ("forex", "fx", "currency", "eur/usd", "usdjpy")):
        return "FX"
    if any(k in norm for k in ("commodity", "oil", "gold", "wheat", "energy")):
        return "COMMODITY"
    if any(k in norm for k in ("etf", "spy", "qqq")):
        return "ETF"
    if any(k in norm for k in ("equity", "stock", "s&p", "sp500", "nasdaq")):
        return "EQUITY"
    return None


def _extract_symbols(text: str, function_codes: set[str]) -> list[str]:
    out: list[str] = []
    for match in _TICKER.finditer(text):
        token = match.group(0)
        # Skip pure function codes ("FA", "DES") that the user just used as verbs.
        if token in function_codes and len(token) <= 4:
            continue
        out.append(token)
    # Dedupe preserving order.
    seen: set[str] = set()
    return [t for t in out if not (t in seen or seen.add(t))]


def _extract_function_code(text: str, function_codes: set[str]) -> str | None:
    if not function_codes:
        return None
    for match in _FUNCTION_CODE.finditer(text):
        token = match.group(0)
        if token in function_codes:
            return token
    return None


def _direction_hint(norm: str) -> str | None:
    if any(k in norm for k in ("long", "buy", "bullish", "uptrend")):
        return "LONG"
    if any(k in norm for k in ("short", "sell", "bearish", "downtrend")):
        return "SHORT"
    return None


def _agents_for(intent: str) -> list[str]:
    if intent == "briefing":
        # Fan-out: portfolio + scan + news in parallel.
        return ["fanout", "summarizer", "viz"]
    if intent == "scan":
        return ["search", "summarizer", "viz"]
    if intent == "portfolio_overview":
        return ["search", "summarizer", "viz"]
    if intent in ("function", "lookup"):
        return ["search", "summarizer", "viz"]
    if intent == "compare":
        return ["search", "summarizer", "viz"]
    if intent == "news":
        return ["search", "summarizer"]
    return []


def _action_for(intent: str, args: dict[str, Any]) -> str:
    if intent == "briefing":
        return "Fan-out: portfolio + quick scan + recent news"
    if intent == "scan":
        return f"Run scanner (phases {args.get('phases', 'A,B')})"
    if intent == "portfolio_overview":
        return "Pull portfolio snapshot via PORT function"
    if intent == "function":
        return f"Execute function {args.get('code', '?')}"
    if intent == "lookup":
        sym = args.get("symbols", ["?"])[0] if args.get("symbols") else "?"
        return f"Open DES on {sym}"
    if intent == "compare":
        return "Side-by-side compare via DES + GP"
    if intent == "news":
        return "Pull recent headlines via TOP / NI"
    return "No-op (unknown intent)"
