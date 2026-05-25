"""BQUANT — Local notebook bridge (JupyterLab embed pointer).

BQUANT is a thin manifest surface: it reports whether the packaged sidecar
has a Jupyter runtime mounted plus a set of local example notebooks, and
honestly declares ``not_configured`` (rather than claiming readiness) when
no notebook server is reachable. Real notebook execution lives in the
launcher process, not in the sidecar.
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
def bquant() -> FunctionManifest:
    return FunctionManifest(
        code="BQUANT",
        name="BQuant Notebook",
        category=Category.API_DEV,
        intent=(
            "Surface the readiness of the local JupyterLab bridge — notebook URL, kernel "
            "modules, and example notebooks — without claiming execution unless a Jupyter "
            "server is actually mounted."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.FX,
            AssetClass.COMMODITY,
            AssetClass.BOND,
        ],
        inputs=[
            InputSpec(
                name="notebook_url",
                label="Notebook URL",
                control=ControlKind.TEXT,
                required=False,
                description=(
                    "Where the launcher exposes the Jupyter server (default /notebook). "
                    "BQUANT does not connect; it surfaces the route for the user to open."
                ),
            ),
            InputSpec(
                name="jupyter_running",
                label="Jupyter running",
                control=ControlKind.BOOLEAN,
                required=False,
                description=(
                    "Hint that a Jupyter runtime is mounted by the launcher. When True, "
                    "BQUANT reports configured even if no local example notebooks exist."
                ),
            ),
            InputSpec(
                name="examples_dir",
                label="Examples directory",
                control=ControlKind.TEXT,
                required=False,
                description="Local path scanned for example .ipynb files.",
            ),
        ],
        defaults={
            "notebook_url": "/notebook",
            "jupyter_running": False,
            "examples_dir": "examples",
        },
        # Internal-only surface: BQUANT is a readiness pointer, not a live
        # data provider. acceptable_modes declares NOT_CONFIGURED so the UI
        # surfaces "no Jupyter mounted" without treating it as an error.
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=[],
            acceptable_modes=[
                DataMode.MODELED,
                DataMode.NOT_CONFIGURED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=60, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["status", "rows", "summary"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="component", label="Component", kind="text"),
                ColumnSpec(key="status", label="Status", kind="tag"),
                ColumnSpec(key="value", label="Value", kind="text"),
                ColumnSpec(key="action", label="Next action", kind="text"),
            ],
            sortable=True,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="notebook_ready", label="Notebook", kind="mode_pill"),
                CardSlot(key="notebook_url", label="URL", kind="badge"),
                CardSlot(key="examples_found", label="Examples", kind="kpi"),
                CardSlot(key="preloaded_modules", label="Modules", kind="kpi"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "BQUANT is a local-only readiness pointer for the JupyterLab bridge. It scans the "
            "examples_dir for .ipynb files, checks the jupyter_running hint, and concatenates "
            "those into a status summary (configured / not_configured). It never claims notebook "
            "execution succeeded — that responsibility belongs to the launcher process which "
            "owns the Jupyter runtime. Preloaded modules (showme.data, showme.functions, "
            "showme.portfolio) are surfaced as a static list because they ship with the sidecar "
            "regardless of whether a kernel is mounted."
        ),
        field_dict={
            "status": FieldDef(description="ok when a notebook runtime is reachable; not_configured otherwise.", source="bquant"),
            "rows[].component": FieldDef(description="Notebook integration surface being checked.", source="bquant"),
            "rows[].status": FieldDef(description="Readiness of the component.", source="bquant"),
            "rows[].value": FieldDef(description="Route, module list, or example path discovered.", source="bquant"),
            "rows[].action": FieldDef(description="Next concrete action for the user.", source="bquant"),
            "summary.notebook_ready": FieldDef(description="True iff configured.", source="bquant"),
            "summary.examples_found": FieldDef(unit="count", description="How many example notebooks exist.", source="bquant"),
            "summary.preloaded_modules": FieldDef(unit="count", description="Count of static preloaded modules.", source="bquant"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        semantic_tests=[
            SemanticTest(
                name="bquant_no_jupyter_returns_not_configured",
                description="With no jupyter_running hint and no example notebooks present, BQUANT reports status=not_configured.",
                inputs={"jupyter_running": False, "examples_dir": "/nonexistent"},
                assertions=[
                    "status == 'not_configured'",
                    "summary.notebook_ready == False",
                    "next_actions_non_empty",
                ],
            ),
            SemanticTest(
                name="bquant_jupyter_hint_marks_ready",
                description="jupyter_running=True flips status to ok / summary.notebook_ready=True even without examples.",
                inputs={"jupyter_running": True},
                assertions=[
                    "status == 'ok'",
                    "summary.notebook_ready == True",
                ],
            ),
            SemanticTest(
                name="bquant_reports_preloaded_modules",
                description="BQUANT always reports the static list of preloaded modules (>=3 entries).",
                inputs={},
                assertions=["summary.preloaded_modules >= 3"],
            ),
            SemanticTest(
                name="bquant_no_silent_notebook_execution",
                description="BQUANT must never claim notebook execution succeeded — only readiness reporting.",
                inputs={},
                assertions=["no_kernel_call_made"],
            ),
        ],
    )


__all__ = ["bquant"]
