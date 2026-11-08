"""ECO — Economic Calendar (Awareness merged calendar, holidays for the same countries)."""
from __future__ import annotations

from ..enums import (
    Category,
    ControlKind,
    DataMode,
)
from ..registry import manifest
from ..spec import (
    CachingPolicy,
    FieldDef,
    FunctionManifest,
    InputSpec,
    OutputContract,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
)


@manifest()
def eco() -> FunctionManifest:
    return FunctionManifest(
        code='ECO',
        name='Economic Calendar',
        category=Category.MACRO,
        intent=(
            "Economic release calendar from Awareness: country, importance, consensus, previous and actual values,"
            "surprise direction, central-bank flags, and public or market holidays for the same countries."
            "No schedule is invented; when Awareness is down the function answers provider_unavailable."
        ),
        asset_classes=[],
        inputs=[
            InputSpec(name='country', label='Countries', control=ControlKind.MULTISELECT, required=False, description='ISO-2 country codes (GB for the UK). Empty or ALL = every country.', options=['US', 'EU', 'GB', 'JP', 'CN', 'TR']),
            InputSpec(name='importance', label='Minimum importance', control=ControlKind.NUMBER, required=False, description='1 low, 2 medium, 3 high. Default 1.'),
            InputSpec(name='days', label='Window (days)', control=ControlKind.NUMBER, required=False, description='Days ahead from the start date, 1 to 60. Default 7.'),
            InputSpec(name='from', label='Start date', control=ControlKind.TEXT, required=False, description='Start date YYYY-MM-DD. Default today (UTC).'),
            InputSpec(name='status', label='Release status', control=ControlKind.SELECT, required=False, description='Optional provider status filter.', options=['scheduled', 'released', 'revised', 'cancelled']),
        ],
        provider_chain=ProviderChain(
            primary="awareness",
            fallbacks=[],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=300, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=['rows', 'holidays'],
            rows=True,
            series=False,
            cards=False,
            warnings=True,
            next_actions=True,
        ),
        methodology=(
            "ECO reads /calendar/economic for the window and countries, filtered to the importance floor."
            "importance 3 is high, 2 medium, 1 low. Values pass through as Awareness reports them (K/M/B"
            "suffixes are already scaled upstream). surprise = actual minus forecast when both exist."
            "Holidays come from /calendar/holidays for the same countries. Empty windows say so."
        ),
        field_dict={
            'rows[].date': FieldDef(description='Scheduled release time (UTC).', source='awareness'),
            'rows[].importance': FieldDef(description='1 low, 2 medium, 3 high.', source='awareness'),
            'rows[].actual': FieldDef(description='Released value as published; blank until released.', source='awareness'),
            'rows[].forecast': FieldDef(description='Consensus estimate as published.', source='awareness'),
            'rows[].previous': FieldDef(description='Prior-period value as published.', source='awareness'),
            'rows[].surprise': FieldDef(description='Actual minus forecast in the same unit.', source='computed'),
            'holidays[].kind': FieldDef(description='public, market_closed or early_close.', source='awareness'),
        },
        provenance=ProvenanceSpec(require_source_list=True, require_as_of=True, require_latency_ms=True),
        alerting=None,
        semantic_tests=[
            SemanticTest(name='eco_rows_come_from_awareness', description='A window with an Awareness release returns it with its importance and source.', inputs={'country': 'US', 'days': 7}, assertions=['rows_nonempty_from_awareness']),
            SemanticTest(name='eco_unavailable_is_honest', description='Awareness down returns provider_unavailable with the client reason and no rows.', inputs={'days': 7}, assertions=['status_provider_unavailable', 'rows_empty']),
        ],
    )


__all__ = ['eco']
