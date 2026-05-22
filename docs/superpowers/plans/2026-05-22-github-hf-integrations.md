# GitHub/HF integrations (Sub-system K) Implementation Plan

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** GitHub code search + HF classify/explain primitives. Reuses XSEN's bundled RoBERTa.

---

## Tasks

### Task K1: Modules + routes + tests

**Files:**
- `backend/showme/integrations/__init__.py` (empty)
- `backend/showme/integrations/github.py`
- `backend/showme/integrations/hf.py`
- `backend/showme/server_routes/integrations.py`
- Modify: `backend/showme/server_routes/__init__.py` (add `integrations` family register — alphabetical between `instant` and `mis`)
- `backend/tests/test_integrations_github.py`
- `backend/tests/test_integrations_hf.py`
- `backend/tests/test_integrations_route.py`

`github.py`:
```python
"""GitHub code search via the public REST API (anon by default)."""
import os, time, asyncio
from dataclasses import dataclass, asdict

import httpx

@dataclass(frozen=True)
class CodeHit:
    repo: str
    path: str
    url: str
    snippet: str
    score: float

    def to_dict(self): return asdict(self)

_CACHE: dict[str, tuple[float, list[CodeHit]]] = {}
_CACHE_TTL = 300.0

async def search_code(q: str, language: str | None = None, limit: int = 10) -> list[CodeHit]:
    """Search GitHub code. Never raises — returns [] on rate-limit/network/timeout."""
    key = f"{q}|{language}|{limit}"
    now = time.time()
    cached = _CACHE.get(key)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1]
    params = {"q": (q + (f" language:{language}" if language else "")).strip(), "per_page": min(max(limit, 1), 30)}
    headers = {"Accept": "application/vnd.github.v3.text-match+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get("https://api.github.com/search/code", params=params, headers=headers)
            if r.status_code != 200:
                _CACHE[key] = (now, [])
                return []
            body = r.json()
    except Exception:  # noqa: BLE001
        _CACHE[key] = (now, [])
        return []
    hits: list[CodeHit] = []
    for item in body.get("items") or []:
        snippet = ""
        tm = item.get("text_matches") or []
        if tm and isinstance(tm, list):
            snippet = (tm[0].get("fragment") or "")[:400]
        hits.append(CodeHit(
            repo=(item.get("repository") or {}).get("full_name", ""),
            path=item.get("path") or "",
            url=item.get("html_url") or "",
            snippet=snippet,
            score=float(item.get("score") or 0),
        ))
    _CACHE[key] = (now, hits)
    return hits
```

`hf.py`:
```python
"""HF classify + rule-based explain primitives.

Reuses XSEN's bundled RoBERTa for classification. No new model download.
"""
import hashlib, logging, time
from typing import Any

LOG = logging.getLogger("showme.integrations.hf")

_PIPELINE = None
_HF_CACHE: dict[str, tuple[float, dict]] = {}
_HF_TTL = 3600.0


def _get_pipeline():
    """Lazy-init the sentiment pipeline using showMe's bundled model.

    Looks for showme.x_analysis._ensure_sentiment_pipeline() first; falls
    back to None if XSEN module not importable.
    """
    global _PIPELINE
    if _PIPELINE is not None:
        return _PIPELINE
    try:
        from showme import x_analysis
        _PIPELINE = x_analysis._ensure_sentiment_pipeline()  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        LOG.warning("HF pipeline unavailable: %s", exc)
        _PIPELINE = None
    return _PIPELINE


def classify(text: str) -> dict[str, Any]:
    """Sentiment-style classification via the bundled RoBERTa.

    Returns {label, score, top_3}. On model unavailability returns
    {label: "unknown", score: 0, top_3: [], error: str}.
    """
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    now = time.time()
    cached = _HF_CACHE.get(key)
    if cached and (now - cached[0]) < _HF_TTL:
        return cached[1]
    pipe = _get_pipeline()
    if pipe is None:
        result = {"label": "unknown", "score": 0.0, "top_3": [], "error": "model unavailable"}
        _HF_CACHE[key] = (now, result)
        return result
    try:
        out = pipe(text, top_k=3, truncation=True)
        if isinstance(out, list) and out and isinstance(out[0], list):
            out = out[0]
        top_3 = [{"label": r["label"], "score": float(r["score"])} for r in out]
        best = max(top_3, key=lambda r: r["score"])
        result = {"label": best["label"], "score": best["score"], "top_3": top_3}
    except Exception as exc:  # noqa: BLE001
        result = {"label": "unknown", "score": 0.0, "top_3": [], "error": str(exc)}
    _HF_CACHE[key] = (now, result)
    return result


def explain(spec: dict[str, Any]) -> str:
    """Rule-based NL summary of a StrategySpec dict. Deterministic, no LLM."""
    name = spec.get("name") or "(isimsiz)"
    tf = spec.get("timeframe") or "1h"
    indicators = spec.get("indicators") or []
    entry_rules = spec.get("entry_rules") or []
    exit_rules = spec.get("exit_rules") or []
    entry_logic = spec.get("entry_logic") or "all"
    exit_logic = spec.get("exit_logic") or "any"
    position = spec.get("position") or {}

    parts: list[str] = []
    parts.append(f"**{name}** stratejisi {tf} timeframe'inde çalışır.")
    if indicators:
        ind_summary = ", ".join(
            f"{i.get('alias', '?')}={i.get('id', '?')}"
            + (f"({','.join(f'{k}={v}' for k,v in (i.get('params') or {}).items())})" if i.get("params") else "")
            for i in indicators
        )
        parts.append(f"Kullanılan indikatörler: {ind_summary}.")
    if entry_rules:
        rules_str = " VE ".join(_rule_to_tr(r) for r in entry_rules) if entry_logic == "all" \
                   else " VEYA ".join(_rule_to_tr(r) for r in entry_rules)
        parts.append(f"Pozisyon açar: {rules_str}.")
    if exit_rules:
        rules_str = " VE ".join(_rule_to_tr(r) for r in exit_rules) if exit_logic == "all" \
                   else " VEYA ".join(_rule_to_tr(r) for r in exit_rules)
        parts.append(f"Pozisyon kapatır: {rules_str}.")
    side = position.get("side") or "long"
    sz = position.get("sizing_value")
    if sz:
        parts.append(f"Yön: {side}, büyüklük: {sz} {position.get('sizing_kind') or 'fixed_quote'}.")
    sl = position.get("stop_loss_pct")
    if sl:
        parts.append(f"Stop loss: %{sl}.")
    return " ".join(parts)


def _rule_to_tr(rule: dict[str, Any]) -> str:
    kind = rule.get("kind") or ""
    left = rule.get("left") or "?"
    right = rule.get("right") or "?"
    if kind == "crosses_above":
        return f"{left} {right}'i yukarı kestiğinde"
    if kind == "crosses_below":
        return f"{left} {right}'i aşağı kestiğinde"
    if kind == "greater_than":
        return f"{left} > {right}"
    if kind == "less_than":
        return f"{left} < {right}"
    if kind == "equals_approximately":
        tol = rule.get("tolerance") or 0
        return f"{left} ≈ {right} (±{tol})"
    return f"{kind} {left} {right}"
```

`integrations.py` route file:
```python
"""Routes: /api/integrations/* — GitHub search + HF classify/explain."""
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, FastAPI, HTTPException
from . import AppDeps


def register(app: FastAPI, deps: AppDeps) -> None:
    router = APIRouter()

    @router.get("/api/integrations/github/search")
    async def github_search(q: str, language: str | None = None, limit: int = 10) -> dict[str, Any]:
        from showme.integrations.github import search_code
        if not q or not q.strip():
            raise HTTPException(400, detail="q is required")
        hits = await search_code(q, language=language, limit=min(max(limit, 1), 30))
        return {"q": q, "language": language, "hits": [h.to_dict() for h in hits]}

    @router.post("/api/integrations/hf/classify")
    async def hf_classify(payload: dict[str, Any]) -> dict[str, Any]:
        from showme.integrations.hf import classify
        text = (payload or {}).get("text") or ""
        if not text.strip():
            raise HTTPException(400, detail="text is required")
        return classify(text)

    @router.post("/api/integrations/hf/explain")
    async def hf_explain(payload: dict[str, Any]) -> dict[str, Any]:
        from showme.integrations.hf import explain
        from showme.strategies.store import StrategyStore, UnknownStrategy
        body = payload or {}
        if "strategy_id" in body:
            try:
                spec = StrategyStore.fresh().get(body["strategy_id"])
            except UnknownStrategy:
                raise HTTPException(404, detail="unknown strategy")
            return {"explanation": explain(spec.model_dump())}
        if "spec" in body:
            return {"explanation": explain(body["spec"])}
        raise HTTPException(400, detail="provide either strategy_id or spec")

    app.include_router(router)
```

Tests:
- `test_integrations_github.py`: mock httpx; success returns hits; non-200 returns []; network error returns []; cache hit.
- `test_integrations_hf.py`: when pipeline=None returns `unknown`; explain produces TR string ≥50 chars; rule-to-tr for each kind; explain on empty spec returns string with name placeholder.
- `test_integrations_route.py`: GET github/search 400 on empty q; POST hf/classify 400 on empty text; POST hf/explain with inline spec works; with strategy_id 404 path; mock heavy deps.

### Task K2: Native rebuild + close-out

Tests; build; deploy; live smoke (`GET /api/integrations/github/search?q=rsi&language=python`, `POST /api/integrations/hf/explain` with spec); screenshot; memory note `showme_subsystem_k.md`; `backend/SUBSYSTEM_K.md`.
