"""TRDH — Trading Hours by Venue / Timezone.

Tabular reference for trading-session hours across the world's major
venues — equity exchanges, futures venues, FX/crypto windows, bond
markets — with timezone-aware open/close, lunch break, post-market
extensions, and the current open/closed state derived from `now`.
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
def trdh() -> FunctionManifest:
    return FunctionManifest(
        code="TRDH",
        name="Trading Hours",
        category=Category.MACRO,
        intent=(
            "Reference table of trading-session hours across the world's major venues — "
            "equity exchanges, futures venues, FX windows, crypto (24/7), bond markets — "
            "with timezone-aware open/close, lunch break, post-market extensions, and the "
            "current open/closed state derived from server now."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.FUTURE,
            AssetClass.FX,
            AssetClass.CRYPTO,
            AssetClass.BOND,
            AssetClass.COMMODITY,
        ],
        inputs=[
            InputSpec(
                name="asset_classes",
                label="Asset classes",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Filter venues by asset class; empty = all.",
                options=["equity", "future", "fx", "crypto", "bond", "commodity"],
            ),
            InputSpec(
                name="regions",
                label="Regions",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Filter venues by region; empty = all.",
                options=["americas", "emea", "apac"],
            ),
            InputSpec(
                name="display_tz",
                label="Display timezone",
                control=ControlKind.SELECT,
                required=False,
                description="Render open/close in this IANA tz; default uses the user's OS tz.",
                options=[
                    "auto",
                    "UTC",
                    "America/New_York",
                    "America/Chicago",
                    "Europe/London",
                    "Europe/Frankfurt",
                    "Asia/Tokyo",
                    "Asia/Hong_Kong",
                    "Asia/Shanghai",
                    "Europe/Istanbul",
                ],
            ),
            InputSpec(
                name="now",
                label="Reference time",
                control=ControlKind.DATE_RANGE,
                required=False,
                description="UTC reference for the open/closed derivation; defaults to server now.",
            ),
        ],
        defaults={
            "asset_classes": [],
            "regions": [],
            "display_tz": "auto",
            "now": "server_now",
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=60, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["as_of", "venues", "display_tz"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=False,
        ),
        chart_grammar=None,
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="venue", label="Venue", kind="text"),
                ColumnSpec(key="mic", label="MIC", kind="tag"),
                ColumnSpec(key="region", label="Region", kind="tag"),
                ColumnSpec(key="asset_class", label="Class", kind="tag"),
                ColumnSpec(key="tz", label="Venue TZ", kind="tag"),
                ColumnSpec(key="open_local", label="Open", kind="text"),
                ColumnSpec(key="close_local", label="Close", kind="text"),
                ColumnSpec(key="lunch_break", label="Lunch", kind="text"),
                ColumnSpec(key="state", label="State", kind="tag"),
                ColumnSpec(key="next_event", label="Next", kind="datetime", format="rel-time"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="venues_total", label="Venues", kind="kpi"),
                CardSlot(key="venues_open", label="Open Now", kind="kpi"),
                CardSlot(key="venues_pre_open", label="Pre-Open", kind="kpi"),
                CardSlot(key="display_tz", label="Display TZ", kind="badge"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "TRDH is a curated calendar maintained in-repo (showme/engine/functions/macro/trdh.py "
            "and a YAML calendar file) covering NYSE, NASDAQ, CME, CBOT, LSE, XETRA, Euronext, "
            "TSE, HKEX, SSE, SGX, ASX, BIST, BMV, BVMF; major FX windows (Sydney, Tokyo, London, "
            "New York); and bond markets (TRACE, MTS, JGB). Each venue carries its IANA tz, "
            "regular session open/close in local time, optional lunch break, pre-market and "
            "post-market extension windows, the half-day calendar, and the holiday calendar. The "
            "open/closed state for each venue is derived by taking the input `now` (UTC), "
            "converting to the venue's local tz, and comparing against the session windows minus "
            "the holiday and half-day overrides. The `next_event` field exposes the upcoming "
            "open/close/lunch transition. Crypto venues are always 'open' with no next_event. "
            "Display tz defaults to the user's OS tz (resolved client-side) and falls back to UTC."
        ),
        field_dict={
            "venues[].venue": FieldDef(description="Venue display name.", source="reference"),
            "venues[].mic": FieldDef(description="ISO 10383 Market Identifier Code.", source="reference"),
            "venues[].region": FieldDef(description="americas / emea / apac.", source="reference"),
            "venues[].asset_class": FieldDef(description="Venue asset class.", source="reference"),
            "venues[].tz": FieldDef(description="IANA timezone for the venue's local sessions.", source="reference"),
            "venues[].open_local": FieldDef(description="Regular session open in venue local time (HH:MM).", source="reference"),
            "venues[].close_local": FieldDef(description="Regular session close in venue local time (HH:MM).", source="reference"),
            "venues[].lunch_break": FieldDef(description="Optional lunch break window (HH:MM-HH:MM).", source="reference"),
            "venues[].state": FieldDef(description="Derived state: open / pre_open / lunch / post_close / closed / holiday.", source="computed"),
            "venues[].next_event": FieldDef(unit="iso8601", description="Upcoming open/close/lunch transition in UTC.", source="computed"),
            "display_tz": FieldDef(description="IANA tz used to render open/close in the UI.", source="input"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="trdh_state_open_during_session",
                description="Given a `now` that falls inside NYSE's regular session, asserts the NYSE row's state == 'open' and next_event points to the close.",
                inputs={"now": "2026-05-22T15:00:00Z"},
                assertions=[
                    "nyse_state_is_open",
                    "nyse_next_event_is_close",
                ],
            ),
            SemanticTest(
                name="trdh_holiday_state_is_holiday",
                description="Given a `now` on a US market holiday, asserts NYSE state == 'holiday' and next_event points to the following open.",
                inputs={"now": "2026-07-04T15:00:00Z"},
                assertions=[
                    "nyse_state_is_holiday",
                    "nyse_next_event_is_following_open",
                ],
            ),
            SemanticTest(
                name="trdh_crypto_is_always_open",
                description="Asserts every crypto venue row carries state == 'open' regardless of `now`.",
                inputs={"asset_classes": ["crypto"]},
                assertions=["all_crypto_venues_state_is_open"],
            ),
            SemanticTest(
                name="trdh_display_tz_auto_resolves_to_real_tz",
                description="Asserts display_tz == 'auto' is resolved to a real IANA tz before render and never leaks 'auto' into open_local strings.",
                inputs={"display_tz": "auto"},
                assertions=["display_tz_resolved_to_iana_tz"],
            ),
        ],
    )


__all__ = ["trdh"]
