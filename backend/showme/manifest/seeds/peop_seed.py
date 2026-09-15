"""PEOP — People search (executives, analysts, contacts).

A directory pane: query a local SQLite people directory first (executives,
analysts, contacts) and fall back to a small public-reference set when
no local row matches. The semantic tests pin the S10 BugHunt fix: an
empty / single-char query must NOT fabricate the three Apple-leadership
reference entries — the directory returns no rows and the UI surfaces a
"broaden the query" next-action.
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
def peop() -> FunctionManifest:
    return FunctionManifest(
        code="PEOP",
        name="People Search",
        category=Category.COMMS_PEOPLE,
        intent=(
            "Search executives, analysts, and contacts — local people directory first,"
            " then a keyless live Wikipedia/Wikidata people search — and surface profile"
            " cards (name / role / company / description / source) so an operator can"
            " prepare for an outreach or meeting in one pane."
        ),
        asset_classes=[],
        inputs=[
            InputSpec(
                name="action",
                label="Action",
                control=ControlKind.SELECT,
                required=True,
                description=(
                    "Directory operation: search by query, list by_company, get/upsert/delete"
                    " a single row, or pull aggregate stats."
                ),
                options=["search", "by_company", "get", "upsert", "delete", "stats"],
            ),
            InputSpec(
                name="query",
                label="Query",
                control=ControlKind.TEXT,
                required=False,
                description=(
                    "Free-text query (full name, role, company, tag). An empty query"
                    " returns an empty result set with a 'broaden the query' next-action."
                ),
            ),
            InputSpec(
                name="company",
                label="Company",
                control=ControlKind.TEXT,
                required=False,
                description="Used when action=by_company to filter rows by associated company.",
                depends_on=["action"],
            ),
            InputSpec(
                name="limit",
                label="Limit",
                control=ControlKind.NUMBER,
                required=False,
                description="Maximum rows to return.",
                min=1,
                max=200,
                step=1,
            ),
            InputSpec(
                name="full_name",
                label="Full name",
                control=ControlKind.TEXT,
                required=False,
                description="Required when action=upsert; person's display name.",
                depends_on=["action"],
            ),
            InputSpec(
                name="role",
                label="Role",
                control=ControlKind.TEXT,
                required=False,
                description="Optional role string used on upsert.",
                depends_on=["action"],
            ),
            InputSpec(
                name="tags",
                label="Tags",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Optional tag list used on upsert.",
                depends_on=["action"],
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
            "action": "search",
            "limit": 25,
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
        caching=CachingPolicy(ttl_seconds=60, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["items", "rows", "source_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=None,
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="full_name", label="Name", kind="text", width_hint=180),
                ColumnSpec(key="role", label="Role", kind="text"),
                ColumnSpec(key="company", label="Company", kind="text", width_hint=140),
                ColumnSpec(key="description", label="Description", kind="text"),
                ColumnSpec(key="summary", label="Summary", kind="text"),
                ColumnSpec(key="nationality", label="Nationality", kind="tag"),
                ColumnSpec(key="profile_url", label="Profile URL", kind="text"),
                ColumnSpec(key="linkedin", label="LinkedIn", kind="text"),
                ColumnSpec(key="twitter", label="Twitter", kind="text"),
                ColumnSpec(key="contact_status", label="Contact", kind="tag"),
                ColumnSpec(key="source", label="Source", kind="tag"),
                ColumnSpec(key="source_url", label="Source URL", kind="text"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="query", label="Query", kind="badge"),
                CardSlot(key="result_count", label="Results", kind="kpi"),
                CardSlot(key="source_mode", label="Source", kind="mode_pill"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "PEOP searches the local SQLite people directory first. With ``action=search`` the engine"
            " tokenizes the query and ranks rows by tag/role/bio match. When the local set has no"
            " hits the engine runs a keyless live search against the Wikipedia search API + REST"
            " summaries, keeps person-like entities (Wikidata ``P31=Q5`` when claims exist, otherwise"
            " a disclosed description keyword heuristic; disambiguation pages always dropped), and"
            " enriches role / organization / nationality from Wikidata ``P39`` / ``P106`` / ``P108`` /"
            " ``P27`` with referenced-QID labels resolved in a batched call. When Wikidata has no"
            " employer statement an explicitly tagged pattern heuristic may derive the organization"
            " from the summary (``company_source='summary_pattern'``). Every row carries"
            " ``source_url`` and ``contact_status='public_profile_only'`` so public profiles are"
            " never confused with private contact data. The small bundled public-reference set"
            " remains as a labelled fallback, and provider failures surface as"
            " ``status='provider_unavailable'`` with a reason — never fabricated rows. The S10"
            " BugHunt fix is preserved: an empty or single-character query returns no rows and the"
            " response carries ``status='needs_data'`` with a 'broaden the query' next-action."
            " Auxiliary actions (``upsert`` / ``delete`` / ``stats`` / ``by_company``) hit the"
            " directory directly and surface ``items`` for the renderer to draw as profile cards."
        ),
        formula_dict={},
        field_dict={
            "items[].full_name": FieldDef(description="Person display name.", source="directory"),
            "items[].role": FieldDef(
                description="Position held / occupation label from Wikidata, description fallback.",
                source="wikidata",
            ),
            "items[].company": FieldDef(
                description="Employer label from Wikidata (P108); pattern-derived from the summary when absent (company_source=summary_pattern).",
                source="wikidata",
            ),
            "items[].description": FieldDef(description="Short Wikipedia description.", source="wikipedia"),
            "items[].summary": FieldDef(description="First ~280 chars of the Wikipedia extract.", source="wikipedia"),
            "items[].nationality": FieldDef(description="Citizenship labels from Wikidata (P27).", source="wikidata"),
            "items[].profile_url": FieldDef(description="Wikipedia page URL.", source="wikipedia"),
            "items[].wikidata_id": FieldDef(description="Wikidata entity id (QID) when present.", source="wikidata"),
            "items[].linkedin": FieldDef(description="LinkedIn URL when available.", source="directory"),
            "items[].twitter": FieldDef(description="Twitter handle when available.", source="directory"),
            "items[].contact_status": FieldDef(
                description="Whether direct contact details are available or only a public profile is known.",
                source="adapter",
            ),
            "items[].source": FieldDef(description="Provenance tag for the row.", source="adapter"),
            "items[].source_url": FieldDef(description="Primary source URL for the row.", source="adapter"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="peop_people_directory_results_have_profile_cards",
                description=(
                    "People directory results have profile cards: every item must carry full_name,"
                    " role, company, source and source_url so the renderer can paint a profile card"
                    " (not just a row of names). Bug S10 — fabricated cards on empty query — must"
                    " not regress."
                ),
                inputs={"action": "search", "query": "tim cook"},
                assertions=[
                    "every_item_has_full_name",
                    "every_item_has_role",
                    "every_item_has_source_url",
                    "items_render_as_profile_cards",
                ],
            ),
            SemanticTest(
                name="peop_empty_query_returns_no_rows_not_fabricated_apple_set",
                description=(
                    "S10 BugHunt: an empty or single-char query must NOT fabricate the three"
                    " Apple-leadership reference entries. The directory returns no rows and the"
                    " response carries status=needs_data with a 'broaden the query' next-action."
                ),
                inputs={"action": "search", "query": ""},
                assertions=[
                    "items_length_equals_0",
                    "status_equals_needs_data",
                    "next_action_mentions_broaden_query",
                ],
            ),
            SemanticTest(
                name="peop_fallback_rows_are_labelled_public_profile_only",
                description=(
                    "When the local directory has no hits, fallback rows carry"
                    " contact_status='public_profile_only' and source_url so they are never"
                    " confused with private contact data."
                ),
                inputs={"action": "search", "query": "tim cook apple"},
                assertions=[
                    "fallback_items_contact_status_equals_public_profile_only",
                    "fallback_items_have_source_url",
                ],
            ),
            SemanticTest(
                name="peop_by_company_filters_to_that_company",
                description="action=by_company returns only rows whose company matches the requested value.",
                inputs={"action": "by_company", "company": "Apple"},
                assertions=["every_item_company_matches_apple"],
            ),
            SemanticTest(
                name="peop_live_wikipedia_search_returns_real_people",
                description=(
                    "A search for a well-known executive ('jensen huang') resolves through the"
                    " keyless live Wikipedia/Wikidata chain: rows carry a wikipedia source, a"
                    " Wikipedia profile_url and a Wikipedia-derived description/summary; rows are"
                    " never fabricated and provider failure surfaces provider_unavailable with a"
                    " reason instead of made-up people."
                ),
                inputs={"action": "search", "query": "jensen huang"},
                assertions=[
                    "items_include_wikipedia_source",
                    "every_item_has_profile_url",
                    "every_item_has_description_or_summary",
                    "provider_failure_returns_provider_unavailable_with_reason",
                ],
            ),
        ],
    )


__all__ = ["peop"]
