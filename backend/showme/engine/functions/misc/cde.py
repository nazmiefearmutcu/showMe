"""CDE — Custom Data Fields (user-defined formulas)."""

from __future__ import annotations

import json
import os
from typing import Any

from showme.app_paths import runtime_path
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument


def _store():
    return runtime_path("cde_fields.json")


class _StoreError(Exception):
    """The stored-fields file exists but cannot be read as a formula store."""


def _load() -> dict[str, str]:
    path = _store()
    if not path.exists():
        return {}
    # CDE#2: an unreadable store used to load as {} and the next add wrote
    # the file back holding only the new field, silently dropping the rest.
    # Raise instead so every action reports the problem and no write happens.
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        raise _StoreError(f"cde_fields.json could not be parsed ({type(exc).__name__})") from exc
    if not isinstance(data, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in data.items()
    ):
        raise _StoreError("cde_fields.json does not hold a name-to-formula object")
    return data


def _store_error_payload(reason: str) -> dict[str, Any]:
    return {
        "status": "input_error",
        "reason": f"{reason}. Nothing was changed; fix or move the file aside, then retry.",
        "rows": [],
        "actions": ["list", "add", "remove", "evaluate"],
        "methodology": (
            "CDE stores named custom data-field formulas in runtime/cde_fields.json. "
            "The store is not readable, so no field is listed, added, removed or evaluated."
        ),
        "next_actions": ["Fix or move aside runtime/cde_fields.json, then retry the action."],
    }


def _save(data: dict[str, str]) -> None:
    # F6 [L]: write-temp + atomic replace so a crash mid-write cannot leave a
    # truncated store behind (the old plain write_text could corrupt it).
    path = _store()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


@FunctionRegistry.register
class CDEFunction(BaseFunction):
    code = "CDE"
    name = "Custom Data Fields"
    category = "misc"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        action = params.get("action", "list")
        try:
            store = _load()
        except _StoreError as exc:
            return FunctionResult(code=self.code, instrument=None,
                                  data=_store_error_payload(str(exc)))
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
            name = str(params.get("name") or "").strip()
            # CDE#4: removing an absent name used to report ready and rewrite
            # the store, so a typo looked like a successful removal.
            if name not in store:
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data=_payload(store, status="input_error", reason=f"unknown field {name or '(blank)'}"),
                )
            store.pop(name)
            _save(store)
        elif action == "evaluate":
            name = str(params.get("name") or "").strip()
            from showme.engine.functions.equity.eqs import And, Cond, Or, _eval, _is_missing, parse_dsl
            if name not in store:
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data=_payload(store, status="input_error", reason=f"unknown field {name}"),
                )
            try:
                row = _row_param(params.get("row") or params.get("row_json") or {})
            except ValueError as e:
                # CDE#3: unparseable row JSON used to become {} and evaluate to
                # a normal FALSE. The caller must hear that the input was bad.
                return FunctionResult(
                    code=self.code,
                    instrument=None,
                    data=_payload(store, status="input_error", reason=f"row must be a JSON object: {e}"),
                )
            try:
                ast = parse_dsl(store[name])
                # CDE#3: a referenced field the row lacks makes the result
                # unknown, not FALSE ("pe != 20" on a row without pe is not a
                # proven mismatch).
                needed = sorted(_referenced_fields(ast, Cond, And, Or))
                missing = [f for f in needed if _is_missing(row.get(f))]
                result = None if missing else bool(_eval(ast, row))
                # F6 fix: the evaluate branch used to repurpose `count` to 1
                # and replace `rows` with only the evaluation row — the
                # "Stored fields" KPI lied and the grid hid every stored
                # field. Keep the store truth (count + stored/example rows)
                # and expose the evaluation separately.
                payload = _payload(store, status="ready")
                warnings = []
                if missing:
                    warnings.append(
                        f"Row is missing {', '.join(missing)}; the result is unknown (null), not FALSE."
                    )
                return FunctionResult(code=self.code, instrument=None, warnings=warnings,
                                      data={
                                          **payload,
                                          "evaluation": {
                                              "name": name,
                                              "value": result,
                                              "missing_fields": missing,
                                              "row": row,
                                              "formula": store[name],
                                          },
                                          "cards": [
                                              {"label": "Field", "value": name},
                                              {"label": "Result",
                                               "value": "UNKNOWN" if result is None else result},
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
    """Row as a dict. Blank means an empty row; anything not an object raises."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except Exception as exc:
            raise ValueError(f"not valid JSON ({type(exc).__name__})") from exc
        if isinstance(parsed, dict):
            return parsed
        raise ValueError(f"got {type(parsed).__name__}")
    if value in (None, "", {}):
        return {}
    raise ValueError(f"got {type(value).__name__}")


def _referenced_fields(node: Any, cond_cls: type, and_cls: type, or_cls: type) -> set[str]:
    if isinstance(node, cond_cls):
        return {node.field}
    if isinstance(node, (and_cls, or_cls)):
        out: set[str] = set()
        for part in node.parts:
            out |= _referenced_fields(part, cond_cls, and_cls, or_cls)
        return out
    return set()
