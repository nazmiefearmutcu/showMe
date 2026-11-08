"""PEOP — People search (executives, analysts, contacts)."""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.services import people_directory as pd
from showme.engine.services import people_search as ps

APPLE_LEADERSHIP_SOURCE = (
    "https://www.apple.com/ca/newsroom/2026/04/"
    "tim-cook-to-become-apple-executive-chairman-john-ternus-to-become-apple-ceo/"
)

# The bundled reference set is a snapshot of an announcement, not a live lookup.
# Roles are written as the announcement stated them, so they never claim a
# current position; the snapshot date is surfaced with every row served from it.
REFERENCE_AS_OF = "2026-04-20"

PUBLIC_REFERENCE_PEOPLE: list[dict[str, Any]] = [
    {
        "full_name": "Tim Cook",
        "role": "Apple CEO as of the 2026-04-20 announcement; announced to become Executive Chairman effective 2026-09-01",
        "company": "Apple",
        "email": None,
        "linkedin": None,
        "twitter": None,
        "profile_url": "https://investor.apple.com/leadership-and-governance/person-details/default.aspx",
        "bio": "Apple announced Cook will continue as CEO through the summer and become Executive Chairman on 2026-09-01.",
        "tags": ["apple", "management", "ceo", "board", "succession"],
        "source": "apple_newsroom_public_reference",
        "source_url": APPLE_LEADERSHIP_SOURCE,
        "source_date": "2026-04-20",
        "contact_status": "public_profile_only",
    },
    {
        "full_name": "John Ternus",
        "role": "Senior Vice President, Hardware Engineering as of the 2026-04-20 announcement; announced as CEO effective 2026-09-01",
        "company": "Apple",
        "email": None,
        "linkedin": None,
        "twitter": None,
        "profile_url": APPLE_LEADERSHIP_SOURCE,
        "bio": "Apple announced Ternus will become CEO and join the board on 2026-09-01.",
        "tags": ["apple", "management", "hardware", "incoming_ceo", "succession"],
        "source": "apple_newsroom_public_reference",
        "source_url": APPLE_LEADERSHIP_SOURCE,
        "source_date": "2026-04-20",
        "contact_status": "public_profile_only",
    },
    {
        "full_name": "Arthur Levinson",
        "role": "Chairman of the Board as of the 2026-04-20 announcement; announced as Lead Independent Director effective 2026-09-01",
        "company": "Apple",
        "email": None,
        "linkedin": None,
        "twitter": None,
        "profile_url": APPLE_LEADERSHIP_SOURCE,
        "bio": "Apple announced Levinson will become Lead Independent Director on 2026-09-01.",
        "tags": ["apple", "management", "board", "governance", "succession"],
        "source": "apple_newsroom_public_reference",
        "source_url": APPLE_LEADERSHIP_SOURCE,
        "source_date": "2026-04-20",
        "contact_status": "public_profile_only",
    },
]


@FunctionRegistry.register
class PEOPFunction(BaseFunction):
    code = "PEOP"
    name = "People Search"
    category = "comm"
    description = "Search executives, analysts, and contacts (local directory)."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        action = (params.get("action") or "search").lower()
        if action == "stats":
            return FunctionResult(code=self.code, instrument=None, data=pd.stats())
        if action == "upsert":
            pid = pd.upsert_person(
                full_name=params["full_name"],
                role=params.get("role"),
                company=params.get("company"),
                email=params.get("email"),
                linkedin=params.get("linkedin"),
                twitter=params.get("twitter"),
                bio=params.get("bio"),
                tags=params.get("tags") or [],
            )
            for role in params.get("roles") or []:
                pd.add_role(pid, **role)
            return FunctionResult(code=self.code, instrument=None,
                                  data={"id": pid, "upserted": True})
        if action == "delete":
            ok = pd.delete(int(params["id"]))
            return FunctionResult(code=self.code, instrument=None,
                                  data={"deleted": ok})
        if action == "get":
            return FunctionResult(code=self.code, instrument=None,
                                  data=pd.get(int(params["id"])) or {})
        if action == "by_company":
            company = params.get("company") or (
                instrument.symbol if instrument else "")
            return FunctionResult(code=self.code, instrument=instrument,
                                  data={"items": pd.list_for_company(
                                      company, limit=int(params.get("limit", 50)))})
        # default: search
        query = params.get("query") or params.get("q") or ""
        limit = int(params.get("limit", 25))
        # PEOP#4: an empty or one-character query must never reach the local
        # LIKE search (LIKE '%%' matches every row). Same rule as the live and
        # reference searches below.
        items = pd.search(query, limit=limit) if _usable_query(query) else []
        source_mode = "local_directory"
        live_sources: list[str] = []
        provider_error: str | None = None
        live_scan: dict[str, Any] = {}
        if not items:
            # HNT-01: search_people is synchronous (sync httpx + up to 1 req/s
            # throttle sleep + ThreadPoolExecutor fan-out); calling it inline
            # froze the shared worker loop for every other pane. Offload it.
            live = await asyncio.to_thread(ps.search_people, query, limit=limit)
            if live.get("ok") and live.get("items"):
                items = live["items"]
                live_sources = list(live.get("sources") or [])
                source_mode = "wikipedia_live"
                live_scan = {
                    "candidates_scanned": live.get("candidates_scanned"),
                    "candidate_cap": live.get("candidate_cap"),
                }
            else:
                if not live.get("ok"):
                    provider_error = str(
                        live.get("reason") or "people provider unavailable"
                    )
                reference = reference_people_search(query, limit=limit)
                if reference:
                    items = reference
                    source_mode = "public_reference"
                elif provider_error:
                    source_mode = "provider_unavailable"
                else:
                    source_mode = "empty_directory"

        if source_mode == "local_directory":
            sources = ["people_directory"]
        elif source_mode == "wikipedia_live":
            sources = live_sources or ["wikipedia"]
        elif source_mode == "public_reference":
            sources = ["people_public_reference"]
        else:
            sources = []

        warnings: list[str] = [provider_error] if provider_error else []
        cap = live_scan.get("candidate_cap")
        scanned = live_scan.get("candidates_scanned")
        # PEOP#6: say so when the candidate cap, not the caller's limit, bounded the list.
        if cap and scanned is not None and scanned >= cap and limit > cap:
            warnings.append(
                f"Only the first {cap} Wikipedia search candidates were checked "
                f"(candidate cap {cap}, requested limit {limit}); more matching people may exist."
            )
        reference_as_of: str | None = None
        if source_mode == "public_reference":
            # PEOP#2: rows from the bundled snapshot are never a live answer.
            # Report needs_data with the snapshot date instead of status ok.
            reference_as_of = REFERENCE_AS_OF
            warnings.append(
                f"Only the bundled public-reference set matched (snapshot dated "
                f"{REFERENCE_AS_OF}); it may be out of date and is not a live lookup."
            )
            status = "needs_data"
        elif items:
            status = "ok"
        elif provider_error:
            status = "provider_unavailable"
        else:
            status = "needs_data"

        next_actions: list[str] = []
        if not items:
            # PEOP#3: on a provider outage the retry hint leads so the pane's
            # empty state explains the outage rather than "no people exist".
            if provider_error:
                next_actions.append(
                    "Retry once the Wikipedia/Wikidata public API is reachable."
                )
                next_actions.append(
                    "Add a person with action=upsert to keep a private local record."
                )
            else:
                next_actions.append(
                    "Add a person with action=upsert or broaden the search query."
                )
                next_actions.append(
                    "Connect/import a local people directory for private contacts."
                )

        return FunctionResult(code=self.code, instrument=None,
                              data={
                                  "query": query,
                                  "items": items,
                                  "rows": items,
                                  "source_mode": source_mode,
                                  "reference_as_of": reference_as_of,
                                  "candidates_scanned": scanned,
                                  "candidate_cap": cap,
                                  "connection_status": [
                                      {"source": "local_people_directory", "status": "used" if source_mode == "local_directory" else "checked"},
                                      {"source": "wikipedia", "status": "used" if source_mode == "wikipedia_live" else ("failed" if provider_error else "checked")},
                                      {"source": "public_reference", "status": "used" if source_mode == "public_reference" else "standby"},
                                  ],
                                  "methodology": (
                                      "PEOP searches the local SQLite people directory first. If no local row matches it runs a"
                                      " keyless live search against the Wikipedia search API + REST summaries, keeps person-like"
                                      " entities (Wikidata P31=Q5 when claims exist, otherwise a disclosed description keyword"
                                      " heuristic), enriches role/organization/nationality from Wikidata P39/P106/P108/P27, and"
                                      " labels every row with source_url + contact_status='public_profile_only'. The small bundled"
                                      " public-reference set remains only as a labelled fallback; provider failures are reported as"
                                      " provider_unavailable with a reason and never fabricate rows."
                                  ),
                                  "field_dictionary": {
                                      "full_name": "Person name.",
                                      "role": "Position held / occupation label from Wikidata, description fallback.",
                                      "company": "Employer label from Wikidata (P108); pattern-derived from the summary when absent (company_source=summary_pattern).",
                                      "description": "Short Wikipedia description (e.g. 'American entrepreneur and businessman').",
                                      "summary": "First ~280 chars of the Wikipedia extract.",
                                      "nationality": "Citizenship labels from Wikidata (P27).",
                                      "profile_url": "Wikipedia page URL.",
                                      "wikidata_id": "Wikidata entity id (QID) when present.",
                                      "contact_status": "Whether direct contact details are available or only a public profile is known.",
                                      "source_url": "Primary source used for the row.",
                                  },
                                  "status": status,
                                  "reason": provider_error,
                                  "provider_error": provider_error,
                                  **({"next_actions": next_actions} if next_actions else {}),
                              },
                              sources=sources,
                              warnings=warnings)


def _usable_query(query: Any) -> bool:
    """A query needs at least two characters to be searched at all."""
    return len(str(query or "").strip()) >= 2


def reference_people_search(query: str, *, limit: int = 25) -> list[dict[str, Any]]:
    """Search the small public-reference people set.

    2026-05-17 BugHunt S10: previously when the caller passed an empty query
    (or only single-char tokens), this function silently substituted
    ``tokens = ["apple"]`` and returned the 3 Apple-leadership reference
    entries. That meant PEOP responded to ``q=""``, ``q="BTC"``, ``q="?"``
    with three fabricated Apple matches, marked the response ``status="ok"``,
    and gave the UI no signal that the query never actually hit the index.
    The fix: return an empty list when the query has no usable tokens; the
    caller already converts that to ``status="needs_data"`` and surfaces a
    "broaden the search query" next-action.
    """
    q = str(query or "").strip().lower()
    tokens = [t for t in q.replace(",", " ").split() if len(t) > 1]
    if not tokens:
        return []
    scored: list[tuple[int, dict[str, Any]]] = []
    for row in PUBLIC_REFERENCE_PEOPLE:
        haystack = " ".join(
            str(row.get(k) or "")
            for k in ("full_name", "role", "company", "bio", "tags")
        ).lower()
        score = sum(1 for token in tokens if token in haystack)
        if score:
            scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], item[1]["full_name"]))
    return [dict(row, match_score=score) for score, row in scored[:limit]]
