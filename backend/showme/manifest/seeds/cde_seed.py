"""CDE — Code editor / custom data entry.

CDE is an in-app text / code / structured-data editor for power users
who need to author strategy snippets, JSON config blobs, or quick CSV
inputs without leaving the cockpit. It is purely internal — no upstream
provider, no network calls; persistence rides the Round 16 preset
filesystem (localStorage fallback).
"""
from __future__ import annotations

from ..enums import (
    AssetClass,
    Category,
    ControlKind,
    DataMode,
)
from ..registry import manifest
from ..spec import (
    CachingPolicy,
    CardSchema,
    CardSlot,
    FieldDef,
    FunctionManifest,
    InputSpec,
    OutputContract,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
)


@manifest()
def cde() -> FunctionManifest:
    return FunctionManifest(
        code="CDE",
        name="Code / Data Editor",
        category=Category.MISC,
        intent=(
            "In-app text / code / structured-data editor for authoring strategy snippets, "
            "JSON config, or CSV inputs without leaving the cockpit — fully internal, "
            "no upstream provider, no network calls."
        ),
        asset_classes=[],
        inputs=[
            InputSpec(
                name="format",
                label="Format",
                control=ControlKind.SELECT,
                required=True,
                description="Editor mode and validation grammar.",
                options=["plain", "json", "yaml", "csv", "python"],
            ),
            InputSpec(
                name="document_id",
                label="Document",
                control=ControlKind.SELECT,
                required=False,
                description="Stored document slot (defaults to scratch).",
            ),
            InputSpec(
                name="initial_value",
                label="Initial value",
                control=ControlKind.TEXT,
                required=False,
                description="Seed contents for new documents.",
            ),
        ],
        defaults={
            "format": "plain",
            "document_id": "scratch",
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
            must_have=["document_id", "format"],
            rows=False,
            series=False,
            cards=True,
            warnings=True,
            next_actions=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="document_id", label="Doc", kind="badge"),
                CardSlot(key="format", label="Format", kind="badge"),
                CardSlot(key="size_bytes", label="Size", kind="kpi", unit="B"),
                CardSlot(key="modified_at", label="Modified", kind="timestamp"),
            ],
        ),
        methodology=(
            "CDE is a purely local editor. Documents are persisted in the Round 16 preset "
            "filesystem on Tauri (localStorage fallback in the browser); there is no upstream "
            "provider, no autosave to a remote service, no telemetry. Format-aware validation "
            "runs in-process on save: JSON / YAML are parsed and rejected on syntax errors; "
            "CSV is sanity-checked for row-count consistency; Python is linted for parse-"
            "errors only (no execution). CDE never executes user code — execution belongs to "
            "STRA / BOT, which read from CDE's stored documents by id."
        ),
        field_dict={
            "document_id": FieldDef(description="Storage slot identifier.", source="store"),
            "format": FieldDef(description="Format echoed back from the request.", source="store"),
            "size_bytes": FieldDef(unit="bytes", description="Document byte length.", source="computed"),
            "modified_at": FieldDef(unit="iso8601", description="Last modification time.", source="store"),
        },
        provenance=ProvenanceSpec(
            require_source_list=False,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="cde_save_then_load_round_trip",
                description="Saving a document by id and loading it back returns the identical bytes.",
                inputs={"document_id": "test_doc", "initial_value": "hello world"},
                assertions=["loaded_value_equals_saved"],
            ),
            SemanticTest(
                name="cde_invalid_json_rejected_with_message",
                description="Saving a document with format='json' and invalid syntax is rejected with a parse-error warning — never silently stored.",
                inputs={"format": "json", "initial_value": "{not_json"},
                assertions=[
                    "save_rejected",
                    "warning_describes_parse_error",
                ],
            ),
            SemanticTest(
                name="cde_never_executes_user_code",
                description="Saving a python document with potentially destructive code does NOT execute the code — CDE is editor-only and never spawns a subprocess.",
                inputs={"format": "python", "initial_value": "print('hello')"},
                assertions=["no_subprocess_spawned", "document_saved_unchanged"],
            ),
        ],
    )


__all__ = ["cde"]
