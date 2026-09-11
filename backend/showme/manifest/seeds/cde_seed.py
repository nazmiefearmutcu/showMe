"""CDE — Custom Data Fields (user-defined formulas).

Stores named custom data-field formulas in `runtime/cde_fields.json`
and evaluates them against a supplied row object with the same safe DSL
parser EQS uses. Never executes arbitrary Python. Resynced to the
shipped handler (``engine/functions/misc/cde.py``) by fix lane F14 —
the previous seed described an unimplemented document/format text
editor and a `count` field that no longer matches the wire.
"""
from __future__ import annotations

from ..enums import (
    Category,
    ControlKind,
    DataMode,
)
from ..registry import manifest
from ..spec import (
    CachingPolicy,
    CardSchema,
    CardSlot,
    ColumnSpec,
    FieldDef,
    FunctionManifest,
    InputSpec,
    OutputContract,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
    TableSchema,
)


@manifest()
def cde() -> FunctionManifest:
    return FunctionManifest(
        code="CDE",
        name="Custom Data Fields",
        category=Category.MISC,
        intent=(
            "Create, list, remove and evaluate named custom data-field formulas against a "
            "row object using the safe EQS DSL — purely local persistence, no provider, "
            "no arbitrary code execution."
        ),
        asset_classes=[],
        inputs=[
            InputSpec(
                name="action",
                label="Action",
                control=ControlKind.SELECT,
                required=True,
                description="Store operation.",
                options=["list", "add", "remove", "evaluate"],
            ),
            InputSpec(
                name="name",
                label="Field name",
                control=ControlKind.TEXT,
                required=False,
                description="Custom field identifier (required for add / remove / evaluate).",
            ),
            InputSpec(
                name="formula",
                label="Formula",
                control=ControlKind.TEXT,
                required=False,
                description="Safe ShowMe DSL expression validated by the EQS parser on add.",
            ),
            InputSpec(
                name="row",
                label="Row JSON",
                control=ControlKind.TEXT,
                required=False,
                description="Row object the evaluate action runs the formula against.",
            ),
        ],
        defaults={
            "action": "list",
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=[],
            acceptable_modes=[
                DataMode.CACHED_SNAPSHOT,
                DataMode.NOT_CONFIGURED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=0, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["status", "rows", "count", "actions", "methodology"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="name", label="Field", kind="text"),
                ColumnSpec(key="formula", label="Formula", kind="text"),
                ColumnSpec(key="operation", label="Operation", kind="tag"),
                ColumnSpec(key="source_mode", label="Source", kind="tag"),
            ],
            sortable=True,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="count", label="Stored fields", kind="kpi"),
                CardSlot(key="status", label="Status", kind="badge"),
                CardSlot(key="evaluation", label="Last evaluation", kind="badge"),
            ],
        ),
        methodology=(
            "CDE keeps named custom data-field formulas in runtime/cde_fields.json (atomic "
            "temp-file replace on every save). add requires both name and formula and "
            "validates the expression through the same parse_dsl used by EQS — a parse "
            "error returns status=input_error and nothing is stored. list returns the "
            "stored fields (or two labelled example rows when the store is empty); "
            "evaluate parses the named formula, runs it against the supplied row JSON, "
            "and returns the boolean result under `evaluation` while keeping `rows` and "
            "`count` equal to the store truth (count == number of stored fields, exactly "
            "the F14 fix to the old count==1 repurposing). remove deletes by name. User "
            "code is never executed: the DSL is parsed to an AST, not run through eval()."
        ),
        field_dict={
            "rows[].name": FieldDef(description="Custom field name.", source="store"),
            "rows[].formula": FieldDef(description="Safe ShowMe DSL expression.", source="store"),
            "rows[].operation": FieldDef(description="custom_field for stored rows, example for the empty-store samples.", source="store"),
            "rows[].source_mode": FieldDef(description="local_cde_store for stored rows.", source="store"),
            "count": FieldDef(description="Number of stored custom fields — not the returned row count.", source="store"),
            "evaluation.value": FieldDef(description="Boolean result of the evaluate action.", source="computed"),
            "evaluation.row": FieldDef(description="Row object the formula was evaluated against.", source="input"),
        },
        provenance=ProvenanceSpec(
            require_source_list=False,
            require_as_of=False,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="cde_invalid_formula_rejected_without_storing",
                description="add with a formula the DSL parser rejects returns input_error and does not persist the field.",
                inputs={"action": "add", "name": "bad", "formula": "{not_a_dsl"},
                assertions=[
                    "status_equals_input_error",
                    "store_unchanged",
                    "warning_describes_formula_parse_error",
                ],
            ),
            SemanticTest(
                name="cde_evaluate_keeps_stored_count_and_rows_truth",
                description="evaluate keeps `count` == number of stored fields and `rows` == stored fields; the boolean result lives under `evaluation` (regression for the old count→1 repurposing).",
                inputs={"action": "evaluate", "name": "large_cap_tech", "row": {"sector": "Technology", "marketCap": 90000000000}},
                assertions=[
                    "count_equals_len_store",
                    "rows_include_stored_fields",
                    "evaluation_has_value_and_row",
                ],
            ),
            SemanticTest(
                name="cde_never_executes_user_code",
                description="Formulas are parsed to an AST by the shared EQS parser; evaluate never calls python eval()/exec() or spawns a subprocess.",
                inputs={"action": "evaluate", "name": "x", "row": {}},
                assertions=[
                    "no_eval_exec_used",
                    "no_subprocess_spawned",
                ],
            ),
            SemanticTest(
                name="cde_remove_only_touches_named_field",
                description="remove deletes exactly the named field and leaves the rest of the store intact.",
                inputs={"action": "remove", "name": "large_cap_tech"},
                assertions=[
                    "named_field_removed",
                    "other_fields_preserved",
                ],
            ),
        ],
    )


__all__ = ["cde"]
