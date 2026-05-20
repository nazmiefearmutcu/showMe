"""CDE — Custom Data Fields (user-defined formulas)."""

from __future__ import annotations

import json
from typing import Any

from showme.app_paths import runtime_path
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument


def _store():
    return runtime_path("cde_fields.json")


def _load() -> dict[str, str]:
    if _store().exists():
        try:
            return json.loads(_store().read_text())
        except Exception:
            return {}
    return {}


def _save(data: dict[str, str]) -> None:
    _store().parent.mkdir(parents=True, exist_ok=True)
    _store().write_text(json.dumps(data, indent=2))


@FunctionRegistry.register
class CDEFunction(BaseFunction):
    code = "CDE"
    name = "Custom Data Fields"
    category = "misc"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        action = params.get("action", "list")
        store = _load()
        if action == "add":
            name = str(params.get("name") or "").strip()
            formula = str(params.get("formula") or "").strip()
            if not name or not formula:
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data=_payload(store, status="input_error", reason="name and formula are required for add"),
                )
            from showme.engine.functions.equity.eqs import parse_dsl
            try:
                parse_dsl(formula)
            except Exception as e:
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data=_payload(store, status="input_error", reason=f"formula parse error: {e}"),
                )
            store[name] = formula
            _save(store)
        elif action == "remove":
            store.pop(str(params.get("name") or ""), None)
            _save(store)
        elif action == "evaluate":
            name = str(params.get("name") or "").strip()
            row = _row_param(params.get("row") or params.get("row_json") or {})
            from showme.engine.functions.equity.eqs import parse_dsl, _eval
            if name not in store:
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data=_payload(store, status="input_error", reason=f"unknown field {name}"),
                )
            try:
                ast = parse_dsl(store[name])
                result = _eval(ast, row)
                evaluation_row = {
                    "name": name,
                    "formula": store[name],
                    "operation": "evaluation",
                    "evaluation": bool(result),
                    "row_json": json.dumps(row, sort_keys=True),
                    "source_mode": "local_cde_store",
                }
                payload = _payload(store, status="ready")
                payload["rows"] = [evaluation_row]
                payload["count"] = 1
                return FunctionResult(code=self.code, instrument=None,
                                      data={
                                          **payload,
                                          "evaluation": {
                                              "name": name,
                                              "value": bool(result),
                                              "row": row,
                                              "formula": store[name],
                                          },
                                          "cards": [
                                              {"label": "Field", "value": name},
                                              {"label": "Result", "value": bool(result)},
                                          ],
                                      })
            except Exception as e:
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data=_payload(store, status="calc_error", reason=f"eval error: {e}"),
                )
        return FunctionResult(code=self.code, instrument=None,
                              data=_payload(store, status="ready"))


def _payload(store: dict[str, str], *, status: str, reason: str | None = None) -> dict[str, Any]:
    rows = [
        {"name": name, "formula": formula, "operation": "custom_field", "source_mode": "local_cde_store"}
        for name, formula in sorted(store.items())
    ]
    examples = [
        {"name": "large_cap_tech", "formula": 'sector = "Technology" AND marketCap > 50000000000', "operation": "example"},
        {"name": "cheap_quality", "formula": "pe < 25 AND beta < 1.2", "operation": "example"},
    ]
    return {
        "status": status,
        **({"reason": reason} if reason else {}),
        "rows": rows or examples,
        "count": len(store),
        "actions": ["list", "add", "remove", "evaluate"],
        "methodology": (
            "CDE stores named custom data-field formulas in runtime/cde_fields.json. "
            "Formulas use the same safe DSL parser as EQS; evaluate runs the parsed expression "
            "against the provided row JSON and does not execute arbitrary Python."
        ),
        "field_dictionary": {
            "name": "Custom field name.",
            "formula": "Safe ShowMe DSL expression.",
            "operation": "Stored field or example row.",
            "evaluation": "Boolean result when action=evaluate is used.",
        },
        "next_actions": [
            "Set action=add with Name and Formula to create a field.",
            "Set action=evaluate with Name and Row JSON to test a field.",
        ],
    }


def _row_param(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}
