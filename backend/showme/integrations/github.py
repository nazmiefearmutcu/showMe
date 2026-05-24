"""GitHub code search via the public REST API (anon by default).

QA-fix: callers can now read a structured status via the module-level
``last_status`` global (populated for every ``search_code`` call) so
they can flag degraded results in their response metadata
(``degraded=True``, ``degraded_reason="github_anon_blocked"``).
"""
import logging
import os
import time
from dataclasses import dataclass, asdict
from typing import Literal

import httpx

LOG = logging.getLogger("showme.integrations.github")

# Status values returned alongside the hit list so callers can attribute
# empty responses correctly:
#   * ok           — request succeeded
#   * anon_blocked — anon rate-limited or 401/403 without a GITHUB_TOKEN
#   * rate_limited — token present but still rate-limited
#   * network      — connection/timeout/SSL error
#   * other        — unexpected HTTP failure
GithubStatus = Literal["ok", "anon_blocked", "rate_limited", "network", "other"]


@dataclass(frozen=True)
class CodeHit:
    repo: str
    path: str
    url: str
    snippet: str
    score: float

    def to_dict(self): return asdict(self)

_CACHE: dict[str, tuple[float, list[CodeHit]]] = {}
_CACHE_STATUS: dict[str, GithubStatus] = {}
_CACHE_TTL = 300.0


async def search_code(q: str, language: str | None = None, limit: int = 10) -> list[CodeHit]:
    """Search GitHub code. Never raises — returns [] on rate-limit/network/timeout.

    QA-fix: alongside the cached hit list we record a per-key status into
    ``_CACHE_STATUS`` so callers can read the failure reason via
    ``search_code_with_status``.
    """
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
                # QA-fix: log the failure shape so operators can tell anon
                # rate-limits apart from auth issues.
                if r.status_code in (401, 403):
                    status: GithubStatus = "rate_limited" if token else "anon_blocked"
                    LOG.warning(
                        "github code search blocked (%s, token=%s): %s",
                        r.status_code,
                        "yes" if token else "no",
                        (r.text or "")[:200],
                    )
                else:
                    status = "other"
                    LOG.warning(
                        "github code search non-200 %s: %s",
                        r.status_code,
                        (r.text or "")[:200],
                    )
                _CACHE[key] = (now, [])
                _CACHE_STATUS[key] = status
                return []
            body = r.json()
    except Exception as exc:  # noqa: BLE001
        # QA-fix: log + structured status so callers can flag degraded.
        LOG.warning("github code search network error: %s", exc)
        _CACHE[key] = (now, [])
        _CACHE_STATUS[key] = "network"
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
    _CACHE_STATUS[key] = "ok"
    return hits


async def search_code_with_status(
    q: str,
    language: str | None = None,
    limit: int = 10,
) -> tuple[list[CodeHit], GithubStatus]:
    """Search GitHub code and report a structured status to the caller.

    Delegates to ``search_code`` so monkeypatching ``search_code`` in tests
    still works; the status is then read out of ``_CACHE_STATUS`` (or
    inferred from the patched return when no status was published).
    """
    key = f"{q}|{language}|{limit}"
    hits = await search_code(q, language, limit)
    status: GithubStatus = _CACHE_STATUS.get(key, "ok" if hits else "other")
    return hits, status
