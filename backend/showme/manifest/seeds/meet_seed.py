"""MEET — Meeting briefing workspace.

Pre-meeting briefing: composes Notion search pages, recent Granola notes,
recent GDELT news, a DES company snapshot, the operator's portfolio
position in the discussed instrument, and (when the instrument is equity)
SOSC sentiment into a single briefing JSON. Primary provider is
``internal`` because the function orchestrates other adapters rather than
hitting a single feed.
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
def meet() -> FunctionManifest:
    return FunctionManifest(
        code="MEET",
        name="Meeting Briefing",
        category=Category.COMMS_PEOPLE,
        intent=(
            "Compose a one-pane meeting briefing — Notion pages, recent Granola"
            " notes, recent news, a DES company snapshot, and the operator's"
            " portfolio position — so the user walks into a meeting ready to talk."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.INDEX,
        ],
        inputs=[
            InputSpec(
                name="topic",
                label="Topic",
                control=ControlKind.TEXT,
                required=True,
                description=(
                    "Meeting topic — typically a company name, person name, or"
                    " instrument symbol; used to seed every downstream search."
                ),
            ),
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=False,
                description=(
                    "Optional instrument symbol — when set, DES and portfolio match"
                    " blocks are populated for that instrument."
                ),
            ),
            InputSpec(
                name="live_meeting",
                label="Live composition",
                control=ControlKind.BOOLEAN,
                required=False,
                description=(
                    "When true the briefing fans out to Notion/Granola/GDELT/DES/portfolio"
                    " in parallel; when false a local template is returned."
                ),
            ),
            InputSpec(
                name="include_sources",
                label="Include sources",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Which composition blocks to include in the live briefing.",
                options=["notion", "granola", "gdelt", "des", "portfolio", "sosc"],
            ),
            InputSpec(
                name="timeout",
                label="Per-source timeout",
                control=ControlKind.NUMBER,
                required=False,
                description="Per-source asyncio timeout used when fanning out the live composition.",
                min=1.0,
                max=30.0,
                step=0.5,
                unit="s",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred provider mode; chain may downgrade and report it.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.MODELED.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "live_meeting": False,
            "include_sources": ["notion", "granola", "gdelt", "des", "portfolio"],
            "timeout": 8.0,
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.MODELED,
                DataMode.CACHED_SNAPSHOT,
                DataMode.NOT_CONFIGURED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=120, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["topic", "data_mode"],
            rows=False,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=None,
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="source", label="Source", kind="tag", width_hint=110),
                ColumnSpec(key="title", label="Title", kind="text"),
                ColumnSpec(key="excerpt", label="Excerpt", kind="text"),
                ColumnSpec(key="timestamp", label="When", kind="datetime"),
                ColumnSpec(key="link", label="Link", kind="text"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="topic", label="Topic", kind="big_number"),
                CardSlot(key="company_name", label="Company", kind="kpi"),
                CardSlot(key="portfolio_position", label="Position", kind="kpi"),
                CardSlot(key="news_count", label="News (48h)", kind="kpi"),
                CardSlot(key="notion_count", label="Notion", kind="kpi"),
                CardSlot(key="granola_count", label="Granola", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "MEET composes a meeting briefing from the operator's connected adapters. With"
            " ``live_meeting=true`` the engine fans out per-source asyncio tasks in parallel:"
            " Notion search (pages whose title/body match the topic), Granola list_recent (the last"
            " 15 local meeting notes), GDELT news (last 48 hours filtered by query), DES (when an"
            " equity/ETF symbol is supplied — pulls name/sector/industry/market_cap/ceo/website),"
            " and the operator's portfolio position. Per-source timeouts are configurable and a"
            " failure on one source surfaces as a warning rather than failing the whole briefing."
            " With ``live_meeting=false`` a local template is returned so the pane still renders"
            " when none of the adapters are wired. The briefing is intended as a profile-card"
            " composition next to PEOP results, not a chart."
        ),
        formula_dict={},
        field_dict={
            "topic": FieldDef(description="Echo of the requested meeting topic.", source="adapter"),
            "notion_pages[]": FieldDef(description="Notion pages whose content matches the topic.", source="notion"),
            "granola_recent[]": FieldDef(description="Recent Granola meeting notes.", source="granola"),
            "recent_news[]": FieldDef(description="GDELT news from the last 48 hours.", source="gdelt"),
            "company.name": FieldDef(description="Company display name from DES.", source="yfinance"),
            "company.sector": FieldDef(description="GICS sector from DES.", source="yfinance"),
            "portfolio_position.symbol": FieldDef(description="Position symbol when the topic matches a holding.", source="portfolio_state"),
            "portfolio_position.quantity": FieldDef(description="Position quantity.", source="portfolio_state"),
            "portfolio_position.avg_cost": FieldDef(description="Average cost basis.", source="portfolio_state"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="meet_people_directory_results_have_profile_cards",
                description=(
                    "People directory results have profile cards: when the briefing surfaces"
                    " people (executives, analysts, attendees) every entry carries name + role +"
                    " source so the renderer can paint a profile card next to the Notion/news strip."
                ),
                inputs={"topic": "Apple"},
                assertions=[
                    "people_entries_have_full_name",
                    "people_entries_have_role_or_company",
                    "people_entries_render_as_profile_cards",
                ],
            ),
            SemanticTest(
                name="meet_missing_topic_raises_or_warns",
                description=(
                    "A call with no topic and no instrument must NOT silently return an empty"
                    " briefing; the response carries a warning that topic is required."
                ),
                inputs={},
                assertions=["warning_mentions_topic_or_instrument_required"],
            ),
            SemanticTest(
                name="meet_per_source_timeout_isolates_failure",
                description=(
                    "A timeout on one source (e.g. notion) surfaces as a warning but never breaks"
                    " the other blocks — the live briefing degrades gracefully."
                ),
                inputs={"topic": "Apple", "live_meeting": True, "_mock": "notion_timeout"},
                assertions=[
                    "warning_mentions_notion_timeout",
                    "other_source_blocks_present_in_response",
                ],
            ),
            SemanticTest(
                name="meet_offline_returns_local_template",
                description=(
                    "With live_meeting=false the briefing is a local template marked"
                    " source_mode=local_briefing — the pane still renders without any adapter."
                ),
                inputs={"topic": "Apple", "live_meeting": False},
                assertions=[
                    "sources_includes_local_briefing",
                    "metadata_live_is_false",
                ],
            ),
        ],
    )


__all__ = ["meet"]
