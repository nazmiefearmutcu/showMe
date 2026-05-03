"""PEOP — People search (executives, analysts, contacts)."""

from __future__ import annotations

from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument
from src.services import people_directory as pd


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
        return FunctionResult(code=self.code, instrument=None,
                              data={"query": query, "items": items},
                              sources=["people_directory"])
