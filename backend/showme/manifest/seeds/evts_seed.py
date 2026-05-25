"""EVTS — Upcoming Events Ticker.

Time-sorted ticker of upcoming events: economic releases (from ECO),
corporate actions (from CACT), earnings (from EARN), and central-bank
meetings — merged into one cross-source feed so the analyst can see
what's queued for the next N hours/days at a glance.
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
    AlertingSpec,
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
def evts() -> FunctionManifest:
    return FunctionManifest(
        code="EVTS",
        name="Upcoming Events",
        category=Category.NEWS_INTEL,
        intent=(
            "Time-sorted ticker of upcoming events — economic releases from ECO, corporate "
            "actions from CACT, earnings from EARN, central-bank meetings — merged into one "
            "cross-source feed with countdown, importance, and one-click drilldown to the "
            "originating surface."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.CRYPTO,
            AssetClass.ETF,
            AssetClass.FX,
            AssetClass.COMMODITY,
            AssetClass.BOND,
            AssetClass.RATE,
            AssetClass.INDEX,
        ],
        inputs=[
            InputSpec(
                name="horizon",
                label="Horizon",
                control=ControlKind.SELECT,
                required=True,
                description="How far forward to look.",
                options=["next_6h", "next_24h", "next_3d", "next_7d", "next_14d"],
            ),
            InputSpec(
                name="event_types",
                label="Event types",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Which event categories to include; empty = all.",
                options=["economic_release", "earnings", "corporate_action", "central_bank", "ipo"],
            ),
            InputSpec(
                name="importance",
                label="Importance",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Filter by editorial importance.",
                options=["low", "medium", "high"],
            ),
            InputSpec(
                name="symbols",
                label="Symbols",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Filter to events tagged with these symbols; empty = no symbol filter.",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode; the chain may downgrade and report it.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "horizon": "next_24h",
            "event_types": [],
            "importance": ["high", "medium"],
            "symbols": [],
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=120, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["as_of", "horizon", "events", "data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="time_utc", label="Time", kind="datetime", format="rel-time"),
                ColumnSpec(key="countdown", label="In", kind="duration"),
                ColumnSpec(key="event_type", label="Type", kind="tag"),
                ColumnSpec(key="importance", label="Imp", kind="tag"),
                ColumnSpec(key="symbol", label="Symbol", kind="tag"),
                ColumnSpec(key="country", label="Country", kind="tag"),
                ColumnSpec(key="title", label="Event", kind="text"),
                ColumnSpec(key="source_surface", label="From", kind="tag"),
                ColumnSpec(key="open", label="Open", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="events_count", label="Events", kind="kpi"),
                CardSlot(key="next_event", label="Next", kind="big_number"),
                CardSlot(key="next_event_in", label="In", kind="kpi", unit="duration"),
                CardSlot(key="high_impact_count", label="High Impact", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "EVTS aggregates upcoming events from multiple internal surfaces. (1) ECO supplies "
            "scheduled economic releases (CPI, NFP, FOMC, etc.) within the horizon. (2) CACT "
            "supplies corporate actions (dividends, splits, buybacks, M&A closes). (3) EARN "
            "supplies the upcoming earnings calendar (symbol + ex-date + fiscal quarter). (4) "
            "The central_bank_calendar.yml supplies dated central-bank policy meetings. Each "
            "source returns its native row shape; EVTS normalizes to a common {time_utc, "
            "event_type, importance, symbol, country, title, source_surface} envelope and "
            "sorts ascending by time_utc. The `countdown` field is derived server-side from "
            "(time_utc - now) so the client can render it without timezone math. The "
            "`source_surface` field exposes which surface contributed the row (eco / cact / "
            "earn / central_bank) so the analyst can drill back to the origin. No event is ever "
            "fabricated — if all upstream surfaces fail, events=[] and a warning lists the "
            "failed surfaces."
        ),
        field_dict={
            "events[].time_utc": FieldDef(unit="iso8601", description="Scheduled UTC time.", source="upstream_surface"),
            "events[].countdown": FieldDef(unit="seconds", description="(time_utc - now) in seconds; never negative.", source="computed"),
            "events[].event_type": FieldDef(description="economic_release / earnings / corporate_action / central_bank / ipo.", source="upstream_surface"),
            "events[].importance": FieldDef(description="low / medium / high editorial importance.", source="upstream_surface"),
            "events[].symbol": FieldDef(description="Symbol tag (empty for macro events).", source="upstream_surface"),
            "events[].country": FieldDef(description="ISO 3166-1 alpha-2 country code (for macro events).", source="upstream_surface"),
            "events[].title": FieldDef(description="Display name.", source="upstream_surface"),
            "events[].source_surface": FieldDef(description="Originating internal surface (eco / cact / earn / central_bank).", source="derived"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=["event_in_15min", "high_impact_event_for_symbols"],
            delivery=["tray", "notification"],
        ),
        semantic_tests=[
            SemanticTest(
                name="evts_sorted_ascending_by_time_utc",
                description="Asserts events array is sorted ascending by time_utc.",
                inputs={"horizon": "next_24h"},
                assertions=["events_sorted_ascending_by_time_utc"],
            ),
            SemanticTest(
                name="evts_countdown_is_non_negative",
                description="Asserts every event's countdown >= 0 (no past events).",
                inputs={"horizon": "next_24h"},
                assertions=["every_countdown_ge_zero"],
            ),
            SemanticTest(
                name="evts_source_surface_present",
                description="Asserts every event row carries source_surface ∈ {eco, cact, earn, central_bank} so the analyst can drill back.",
                inputs={},
                assertions=["every_event_has_source_surface"],
            ),
            SemanticTest(
                name="evts_all_surfaces_down_returns_empty_not_synthetic",
                description="When every upstream surface fails, asserts events=[] and warning lists the failed surfaces; no synthetic 'no events today' row appears.",
                inputs={"_mock": "all_surfaces_down"},
                assertions=[
                    "events_empty_array",
                    "warning_lists_failed_surfaces",
                ],
            ),
        ],
    )


__all__ = ["evts"]
