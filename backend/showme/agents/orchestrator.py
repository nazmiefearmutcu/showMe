"""Orchestrator — glue between planner, search, summarizer, viz.

Single entry point `ask(req, deps)` runs:

    plan ← planner.plan_for(query)
    search_result ← search.search(plan, deps)         (if "search" in agents)
    narrative ← summarizer.summarize(plan, search_result)  (if "summarizer")
    viz ← viz.pick_viz(plan, search_result)           (if "viz")

The result is a wrapped envelope with phase timings so the UI can show
the same per-phase pills the SCAN pane already uses.
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .planner import Plan, plan_for
from .search import search as run_search
from .summarizer import summarize
from .viz import pick_viz
from ..llm import build_default_providers, plan_for_smart

LOG = logging.getLogger("showme.agents.orchestrator")


@dataclass
class AskRequest:
    query: str = ""


@dataclass
class AskPhase:
    name: str
    elapsed_ms: float
    output: dict[str, Any] = field(default_factory=dict)


@dataclass
class AskResponse:
    query: str
    plan: Plan
    search: dict[str, Any]
    narrative: str
    highlights: list[dict[str, Any]]
    viz: dict[str, Any]
    phases: list[AskPhase]
    elapsed_ms: float
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "plan": self.plan.to_dict(),
            "phases": [asdict(p) for p in self.phases],
        }


async def ask(req: AskRequest, deps: Any) -> AskResponse:
    started = time.perf_counter()
    function_codes = _function_codes()

    # Phase 1 — Planner. LLM-augmented when API keys are configured AND
    # the daily cost cap hasn't been reached; otherwise the deterministic
    # planner handles every query.
    p_started = time.perf_counter()
    providers = build_default_providers()
    if providers:
        plan = await plan_for_smart(
            req.query,
            function_codes=function_codes,
            providers=providers,
        )
    else:
        plan = plan_for(req.query, function_codes=function_codes)
    plan_phase = AskPhase(
        name="plan",
        elapsed_ms=(time.perf_counter() - p_started) * 1000,
        output={"intent": plan.intent, "agents": plan.agents,
                "args": plan.args, "rationale": plan.rationale},
    )

    phases: list[AskPhase] = [plan_phase]
    search_result: dict[str, Any] = {"kind": "noop", "warnings": []}
    if "fanout" in plan.agents:
        f_started = time.perf_counter()
        search_result = await _fanout(plan, deps)
        phases.append(AskPhase(
            name="fanout",
            elapsed_ms=(time.perf_counter() - f_started) * 1000,
            output={"kind": search_result.get("kind"),
                    "branches": search_result.get("branch_names", [])},
        ))
    elif "search" in plan.agents:
        s_started = time.perf_counter()
        search_result = await run_search(plan, deps)
        phases.append(AskPhase(
            name="search",
            elapsed_ms=(time.perf_counter() - s_started) * 1000,
            output={"kind": search_result.get("kind"),
                    "code": search_result.get("code")},
        ))

    summary: dict[str, Any] = {
        "narrative": "(no summarizer requested)",
        "highlights": [], "warnings": [],
    }
    if "summarizer" in plan.agents:
        sm_started = time.perf_counter()
        summary = summarize(plan, search_result)
        phases.append(AskPhase(
            name="summarize",
            elapsed_ms=(time.perf_counter() - sm_started) * 1000,
            output={"highlights_n": len(summary.get("highlights", []))},
        ))

    viz_block: dict[str, Any] = {"kind": "none"}
    if "viz" in plan.agents:
        v_started = time.perf_counter()
        viz_block = pick_viz(plan, search_result)
        phases.append(AskPhase(
            name="viz",
            elapsed_ms=(time.perf_counter() - v_started) * 1000,
            output={"kind": viz_block.get("kind")},
        ))

    warnings = list(search_result.get("warnings") or [])
    warnings.extend(summary.get("warnings") or [])

    return AskResponse(
        query=req.query,
        plan=plan,
        search=search_result,
        narrative=str(summary.get("narrative") or ""),
        highlights=list(summary.get("highlights") or []),
        viz=viz_block,
        phases=phases,
        elapsed_ms=(time.perf_counter() - started) * 1000,
        warnings=warnings,
    )


def _function_codes() -> set[str]:
    """Best-effort: pull the live FunctionRegistry codes for planner hints."""
    try:
        registry_mod = importlib.import_module("showme.engine.core.base_function")
        return set(registry_mod.FunctionRegistry.codes())
    except Exception:  # noqa: BLE001
        # QA-fix: log the import failure so silent "no functions"
        # behavior is observable instead of hidden.
        LOG.exception("FunctionRegistry import failed; planner gets empty hint set")
        return set()


# ── Fan-out search ───────────────────────────────────────────────────────

async def _fanout(plan: Plan, deps: Any) -> dict[str, Any]:
    """Run portfolio + scan + news in parallel and merge into one envelope.

    Each branch is best-effort — failures are surfaced in `warnings` rather
    than aborting the whole briefing.
    """
    portfolio_plan = Plan(
        intent="portfolio_overview",
        action="briefing portfolio leg",
        agents=["search"],
    )
    scan_args = dict(plan.args)
    scan_args.setdefault("asset_class", "CRYPTO")
    scan_args["quick"] = True
    scan_args.setdefault("phases", "A")
    scan_args.setdefault("top_n", 8)
    scan_args.setdefault("fine_top_k", 4)
    scan_plan = Plan(
        intent="scan",
        action="briefing scan leg",
        args=scan_args,
        agents=["search"],
    )
    news_plan = Plan(
        intent="news",
        action="briefing news leg",
        agents=["search"],
    )

    branches: dict[str, dict[str, Any]] = {}
    branch_warnings: list[str] = []

    async def _run_branch(name: str, p: Plan) -> None:
        try:
            res = await asyncio.wait_for(run_search(p, deps), timeout=8.0)
            branches[name] = res
            for w in (res.get("warnings") or []):
                branch_warnings.append(f"{name}: {w}")
        except asyncio.TimeoutError:
            branch_warnings.append(f"{name}: timed out after 8.0s")
            branches[name] = {"kind": "error", "warnings": ["timed out after 8.0s"]}
        except Exception as exc:  # noqa: BLE001
            branch_warnings.append(f"{name}: {exc}")
            branches[name] = {"kind": "error", "warnings": [str(exc)]}

    await asyncio.gather(
        _run_branch("portfolio", portfolio_plan),
        _run_branch("scan", scan_plan),
        _run_branch("news", news_plan),
    )
    evidence: list[dict[str, Any]] = []
    for branch_name, branch in branches.items():
        for item in _branch_evidence(branch_name, branch):
            evidence.append(item)
    return {
        "kind": "fanout",
        "branch_names": list(branches.keys()),
        "branches": branches,
        "evidence": evidence,
        "warnings": branch_warnings,
    }


def _branch_evidence(branch_name: str, branch: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(branch, dict):
        return []
    out: list[dict[str, Any]] = []
    for item in branch.get("evidence") or []:
        if isinstance(item, dict):
            out.append({"branch": branch_name, **item})
    if out:
        return out
    data = branch.get("data")
    rows = []
    code = branch.get("code") or branch_name.upper()
    sources: list[str] = []
    status = branch.get("kind") or "ok"
    elapsed_ms = None
    if isinstance(data, dict):
        payload = data.get("data") if isinstance(data.get("data"), (dict, list)) else data
        sources = list(data.get("sources") or [])
        elapsed_ms = data.get("elapsed_ms")
        rows = _extract_rows_for_evidence(payload)
        if isinstance(payload, dict):
            status = str(payload.get("status") or data.get("status") or status)
    return [{
        "branch": branch_name,
        "code": str(code).upper(),
        "sources": sources,
        "status": status,
        "rows": len(rows),
        "top": [_evidence_row_label(row) for row in rows[:5]],
        "elapsed_ms": elapsed_ms,
    }]


def _extract_rows_for_evidence(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for key in ("rows", "items", "news", "articles", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
            if isinstance(value, dict):
                rows = _extract_rows_for_evidence(value)
                if rows:
                    return rows
    return []


def _evidence_row_label(row: dict[str, Any]) -> str:
    for key in ("symbol", "title", "headline", "name", "event", "code"):
        value = row.get(key)
        if value:
            return str(value)
    return ", ".join(f"{k}={v}" for k, v in list(row.items())[:2])
