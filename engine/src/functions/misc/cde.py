"""CDE — Custom Data Fields (user-defined formulas)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument


_STORE = Path("runtime/cde_fields.json")


def _load() -> dict[str, str]:
    if _STORE.exists():
        try:
            return json.loads(_STORE.read_text())
        except Exception:
            return {}
    return {}


def _save(data: dict[str, str]) -> None:
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    _STORE.write_text(json.dumps(data, indent=2))


@FunctionRegistry.register
class CDEFunction(BaseFunction):
    code = "CDE"
    name = "Custom Data Fields"
    category = "misc"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        action = params.get("action", "list")
        store = _load()
        if action == "add":
            name = params["name"]; formula = params["formula"]
            from src.functions.equity.eqs import parse_dsl
            try:
                parse_dsl(formula)
            except Exception as e:
                return FunctionResult(code=self.code, instrument=None, data=store,
                                      warnings=[f"formula parse error: {e}"])
            store[name] = formula
            _save(store)
        elif action == "remove":
            store.pop(params["name"], None)
            _save(store)
        elif action == "evaluate":
            name = params["name"]
            row = params.get("row") or {}
            from src.functions.equity.eqs import parse_dsl, _eval
            if name not in store:
                return FunctionResult(code=self.code, instrument=None, data=store,
                                      warnings=[f"unknown field {name}"])
            try:
                ast = parse_dsl(store[name])
                result = _eval(ast, row)
                return FunctionResult(code=self.code, instrument=None,
                                      data={"name": name, "value": bool(result),
                                             "row": row, "formula": store[name]})
            except Exception as e:
                return FunctionResult(code=self.code, instrument=None, data=store,
                                      warnings=[f"eval error: {e}"])
        return FunctionResult(code=self.code, instrument=None,
                              data={"fields": store, "count": len(store),
                                    "actions": ["list", "add", "remove", "evaluate"]})
