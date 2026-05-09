"""ASKB-style agent network.

Round 19 ships the deterministic spine:

    orchestrator  →  planner  →  [search, summarizer, viz]

Every agent is a plain function returning a typed dict; the orchestrator
glues them together. LLM-augmented variants are best-effort and fall
back to the deterministic path when no router is configured.
"""

from .orchestrator import AskRequest, AskResponse, ask  # noqa: F401
from .planner import Plan, plan_for  # noqa: F401
from .search import search  # noqa: F401
from .summarizer import summarize  # noqa: F401
from .viz import pick_viz  # noqa: F401
