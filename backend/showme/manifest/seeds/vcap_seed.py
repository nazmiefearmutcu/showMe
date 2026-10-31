"""VCAP manifest; direct OECD and licensed local releases have honest provenance."""
from __future__ import annotations

from ..enums import AssetClass, Category, ControlKind, DataMode
from ..registry import manifest
from ..spec import (CachingPolicy, ColumnSpec, FunctionManifest, InputSpec, OutputContract,
                    ProvenanceSpec, ProviderChain, SemanticTest, TableSchema)


@manifest()
def vcap() -> FunctionManifest:
    return FunctionManifest(
        code="VCAP", name="Venture Capital Research", category=Category.MACRO,
        intent="Compare source-specific venture investment, deals and fund fundraising across countries, global reports, Turkey and crypto with dated provenance and local versioned imports.",
        asset_classes=[AssetClass.EQUITY, AssetClass.CRYPTO],
        inputs=[
            InputSpec(name="scope", label="Scope", control=ControlKind.SELECT, required=False, description="Measurement universe", options=["countries", "global", "turkey", "crypto"]),
            InputSpec(name="source_ids", label="Sources", control=ControlKind.MULTISELECT, required=False, description="Source catalogue ids or saved custom slugs", options=["oecd", "kpmg_pitchbook", "crunchbase", "cb_insights", "dealroom", "startups_watch", "galaxy", "defillama", "custom"]),
            InputSpec(name="geographies", label="Geographies", control=ControlKind.TEXT, required=False, description="ISO3 codes, WORLD or TUR_DIASPORA; coverage comes from actual saved observations"),
            InputSpec(name="metric", label="Metric", control=ControlKind.SELECT, required=False, description="Company investment, deals and fund fundraising are separate", options=["investment", "deals", "fundraising"]),
            InputSpec(name="stage", label="Stage", control=ControlKind.SELECT, required=False, description="Publisher stage definitions are retained", options=["total", "seed", "early", "late"]),
            InputSpec(name="frequency", label="Frequency", control=ControlKind.SELECT, required=False, description="No automatic annual/quarterly splicing", options=["annual", "quarterly"]),
            InputSpec(name="unit", label="Unit", control=ControlKind.SELECT, required=False, description="Percent GDP is already percent, not a fraction", options=["USD", "PERCENT_GDP", "COUNT"]),
            InputSpec(name="start_year", label="Start year", control=ControlKind.NUMBER, required=False, description="First observation year", min=1900, max=2100),
            InputSpec(name="end_year", label="End year", control=ControlKind.NUMBER, required=False, description="Last observation year (up to current year)", min=1900, max=2100),
            InputSpec(name="financing_scope", label="Crypto financing", control=ControlKind.SELECT, required=False, description="Strict VC needs classification; all raises includes token sales", options=["vc", "all_raises"]),
            InputSpec(name="vintage", label="Vintage", control=ControlKind.TEXT, required=False, description="Opaque snapshot_id; pins its source while other selected sources remain latest"),
            InputSpec(name="refresh", label="Refresh", control=ControlKind.BOOLEAN, required=False, description="Explicit provider refresh, subject to 60-second cooldown"),
        ],
        defaults={"scope": "countries", "source_ids": ["oecd"], "geographies": ["USA"], "metric": "investment", "stage": "total", "frequency": "annual", "unit": "USD", "start_year": 2007, "refresh": False, "financing_scope": "vc"},
        provider_chain=ProviderChain(primary="internal", fallbacks=[], acceptable_modes=[DataMode.DELAYED_REFERENCE, DataMode.CACHED_SNAPSHOT, DataMode.PROVIDER_UNAVAILABLE, DataMode.NOT_CONFIGURED]),
        caching=CachingPolicy(ttl_seconds=0, scope="per_input", persist=False),
        output_contract=OutputContract(must_have=["sources", "methodology"], rows=True, series=True, cards=False, warnings=True, next_actions=True),
        table_schema=TableSchema(columns=[ColumnSpec(key="source_name", label="Source", kind="text"), ColumnSpec(key="geography", label="Geography", kind="tag"), ColumnSpec(key="period", label="Period", kind="text"), ColumnSpec(key="value", label="Value", kind="number"), ColumnSpec(key="unit", label="Unit", kind="tag"), ColumnSpec(key="published_at", label="Published", kind="datetime"), ColumnSpec(key="retrieved_at", label="Retrieved", kind="datetime")]),
        methodology="Reported source-specific data, never synthetic. OECD market geography, stages, flags and multipliers preserved. Vendor sources use owned/licensed local imports. No country-to-world summation, source splicing or automatic annualization. DefiLlama announced all-raises funding is distinct from strict VC. Independent methodologies block percentage gaps.",
        provenance=ProvenanceSpec(require_source_list=True, require_as_of=True, require_latency_ms=False),
        semantic_tests=[SemanticTest(name="source_boundaries", description="Missing values and independent source totals remain separate", inputs={"scope": "countries"}, assertions=["null is never zero", "USD_EXC UNIT_MULT is applied", "no invented WORLD or TUR OECD coverage", "local imports are immutable and atomic"])],
    )
