"""BMC — Market Concepts Education.

BMC serves a static, local market-concepts curriculum (13 lessons across 6
modules) from ``BMCFunction`` in ``engine/functions/misc/_extras.py``. It is
reference content, not live data, and it has no provider. Lesson completion
is kept in the browser by the pane; the backend carries no progress state.

It is a relocation candidate: the curriculum is teaching material and could
move to a learning-focused pane without changing its content.
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
def bmc() -> FunctionManifest:
    return FunctionManifest(
        code="BMC",
        name="Market Concepts Education",
        category=Category.MISC,
        intent=(
            "Static market-concepts curriculum: short lessons with a worked market example "
            "and a self-check question. Reference content only, not live data."
        ),
        asset_classes=[],
        # The handler reads this optional module filter. The pane loads the
        # whole curriculum once and filters it on the client, so it sends none.
        inputs=[
            InputSpec(
                name="module",
                label="Module",
                control=ControlKind.SELECT,
                required=False,
                description="Restrict the curriculum to one module (omit for all modules).",
                options=["Equities", "Fixed Income", "FX", "Commodities", "Macro", "Alternatives"],
            ),
        ],
        defaults={},
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=[],
            acceptable_modes=[
                DataMode.CACHED_SNAPSHOT,
                DataMode.NOT_CONFIGURED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=30, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["rows"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="module", label="Module", kind="tag"),
                ColumnSpec(key="lesson_no", label="No.", kind="text"),
                ColumnSpec(key="lesson", label="Lesson", kind="text"),
                ColumnSpec(key="objective", label="Objective", kind="text"),
                ColumnSpec(key="example", label="Example", kind="text"),
                ColumnSpec(key="quiz", label="Self-check", kind="text"),
            ],
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="modules", label="Modules", kind="kpi"),
                CardSlot(key="lessons", label="Lessons", kind="kpi"),
            ],
        ),
        methodology=(
            "BMC is a local market-concepts curriculum served by the backend: each row is a lesson with "
            "a module, learning objective, worked market example, and self-check question. The content is "
            "static reference material (source: showme_curriculum), not market data, so it carries no "
            "as-of time or provider. Lesson completion is tracked in the browser only; the backend has no "
            "progress state. BMC is a relocation candidate: the curriculum is teaching material that could "
            "move to a learning-focused pane without changing its content."
        ),
        field_dict={
            "rows[].module": FieldDef(description="Curriculum module.", source="curriculum"),
            "rows[].lesson_no": FieldDef(description="Lesson number within its module.", source="curriculum"),
            "rows[].lesson": FieldDef(description="Lesson title.", source="curriculum"),
            "rows[].objective": FieldDef(description="What the lesson should make clear.", source="curriculum"),
            "rows[].example": FieldDef(description="Market example used in the lesson.", source="curriculum"),
            "rows[].quiz": FieldDef(description="Self-check question.", source="curriculum"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=False,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="bmc_rows_are_static_curriculum_without_progress",
                description="Every row is a curriculum lesson; no row carries a constant progress field.",
                inputs={},
                assertions=[
                    "rows_non_empty_array",
                    "rows_have_no_progress_field",
                    "lesson_count_equals_cards_lessons",
                ],
            ),
            SemanticTest(
                name="bmc_module_filter_narrows_rows",
                description="With module set to one curriculum module, only that module's lessons are returned.",
                inputs={"module": "Fixed Income"},
                assertions=["all_rows_in_requested_module"],
            ),
        ],
    )


__all__ = ["bmc"]
