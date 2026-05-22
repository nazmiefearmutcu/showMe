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
