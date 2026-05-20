"""ASKB-style agent network.

Round 19 ships the deterministic spine:

    orchestrator  →  planner  →  [search, summarizer, viz]

Every agent is a plain function returning a typed dict; the orchestrator
glues them together. LLM-augmented variants are best-effort and fall
back to the deterministic path when no router is configured.

Per ARCH-03 P1: re-exports are now lazy via ``__getattr__`` so importing
``showme.agents`` does NOT pull ``orchestrator`` (which imports
``showme.llm``) at module load time. ``showme.llm`` itself imports
``showme.agents.planner`` directly during its own boot path; eager
re-exports here previously turned that into a real circular import.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover — import-time hints only
    from .orchestrator import AskRequest, AskResponse, ask
    from .planner import Plan, plan_for
    from .search import search
    from .summarizer import summarize
    from .viz import pick_viz


__all__ = [
    "AskRequest",
    "AskResponse",
    "Plan",
    "ask",
    "pick_viz",
    "plan_for",
    "search",
    "summarize",
]


_LAZY_TARGETS = {
    "AskRequest": ("showme.agents.orchestrator", "AskRequest"),
    "AskResponse": ("showme.agents.orchestrator", "AskResponse"),
    "ask": ("showme.agents.orchestrator", "ask"),
    "Plan": ("showme.agents.planner", "Plan"),
    "plan_for": ("showme.agents.planner", "plan_for"),
    "search": ("showme.agents.search", "search"),
    "summarize": ("showme.agents.summarizer", "summarize"),
    "pick_viz": ("showme.agents.viz", "pick_viz"),
}


def __getattr__(name: str) -> Any:
    """Lazy import of agent helpers (PEP 562) to avoid the llm↔agents cycle."""
    target = _LAZY_TARGETS.get(name)
    if target is None:
        raise AttributeError(f"module 'showme.agents' has no attribute {name!r}")
    module_name, attr = target
    import importlib
    module = importlib.import_module(module_name)
    value = getattr(module, attr)
    globals()[name] = value
    return value
