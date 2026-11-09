"""IPO — IPO calendar: priced, upcoming, filed and withdrawn offerings (Awareness)."""
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
def ipo() -> FunctionManifest:
    return FunctionManifest(
        code='IPO',
        name='IPO Calendar',
        category=Category.MACRO,
        intent=(
            "IPO calendar from Awareness, grouped into priced, upcoming, filed (S-1 and F-1 registrations) and withdrawn."
            "Price and deal fields appear only when the provider states them. Nothing is estimated."
        ),
        asset_classes=[],
        inputs=[
            InputSpec(name='days_back', label='Days back', control=ControlKind.NUMBER, required=False, description='Lookback in days, 0 to 365. Default 30.'),
            InputSpec(name='days_ahead', label='Days ahead', control=ControlKind.NUMBER, required=False, description='Look-ahead in days, 0 to 365. Default 60.'),
            InputSpec(name='status', label='Section', control=ControlKind.SELECT, required=False, description='Optional single section filter.', options=['priced', 'upcoming', 'filed', 'withdrawn']),
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
            must_have=['sections'],
            rows=True,
            series=False,
            cards=False,
            warnings=True,
            next_actions=True,
        ),
        methodology=(
            "IPO reads /calendar/corporate for IPO rows and filings. Status priced, upcoming or withdrawn sorts IPO"
            "rows; S-1 and F-1 filings are filed; RW filings are withdrawn. Rows are never estimated."
        ),
        field_dict={
            'sections.priced[].price': FieldDef(description='Offer price per share when priced.', source='awareness', unit='USD'),
            'sections.filed[].form': FieldDef(description='SEC registration form (S-1 or F-1 variant).', source='awareness'),
            'sections.upcoming[].date': FieldDef(description='Expected pricing date.', source='awareness'),
        },
        provenance=ProvenanceSpec(require_source_list=True, require_as_of=True, require_latency_ms=True),
        alerting=None,
        semantic_tests=[
            SemanticTest(name='ipo_filed_from_registration_forms', description='An S-1 filing in the window appears under filed.', inputs={'days_back': 30}, assertions=['s1_in_filed']),
            SemanticTest(name='ipo_unavailable_is_honest', description='Awareness down returns provider_unavailable, not an empty calendar.', inputs={}, assertions=['status_provider_unavailable']),
        ],
    )


__all__ = ['ipo']
