"""PEOP — People search (executives, analysts, contacts)."""

from __future__ import annotations

from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.services import people_directory as pd

APPLE_LEADERSHIP_SOURCE = (
    "https://www.apple.com/ca/newsroom/2026/04/"
    "tim-cook-to-become-apple-executive-chairman-john-ternus-to-become-apple-ceo/"
)

PUBLIC_REFERENCE_PEOPLE: list[dict[str, Any]] = [
    {
        "full_name": "Tim Cook",
        "role": "CEO through summer 2026; Executive Chairman effective 2026-09-01",
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
        "role": "Senior Vice President, Hardware Engineering; incoming CEO effective 2026-09-01",
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
        "role": "Non-Executive Chairman; Lead Independent Director effective 2026-09-01",
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
        items = pd.search(query, limit=int(params.get("limit", 25)))
        source_mode = "local_directory"
        if not items:
            items = reference_people_search(query, limit=int(params.get("limit", 25)))
            source_mode = "public_reference" if items else "empty_directory"
        return FunctionResult(code=self.code, instrument=None,
                              data={
                                  "query": query,
                                  "items": items,
                                  "rows": items,
                                  "source_mode": source_mode,
                                  "connection_status": [
                                      {"source": "local_people_directory", "status": "checked"},
                                      {"source": "public_reference", "status": "used" if items and source_mode == "public_reference" else "standby"},
                                  ],
                                  "methodology": "PEOP searches the local SQLite people directory first. If no local row matches, it falls back to a small public-reference directory with source URLs and public-profile-only contact status.",
                                  "field_dictionary": {
                                      "full_name": "Person name.",
                                      "role": "Current or announced role from the source.",
                                      "company": "Associated company or organization.",
                                      "contact_status": "Whether direct contact details are available or only a public profile is known.",
                                      "source_url": "Primary source used for the row.",
                                  },
                                  "status": "ok" if items else "needs_data",
                                  **({} if items else {
                                      "next_actions": [
                                          "Add a person with action=upsert or broaden the search query.",
                                          "Connect/import a local people directory for private contacts.",
                                      ],
                                  }),
                              },
                              sources=["people_directory"] if source_mode == "local_directory" else ["people_public_reference"])


def reference_people_search(query: str, *, limit: int = 25) -> list[dict[str, Any]]:
    q = str(query or "").strip().lower()
    tokens = [t for t in q.replace(",", " ").split() if len(t) > 1]
    if not tokens:
        tokens = ["apple"]
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
