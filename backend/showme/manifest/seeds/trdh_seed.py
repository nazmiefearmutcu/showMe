"""TRDH — Exchange trading hours from the Awareness exchange calendar."""
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
    FieldDef,
    FunctionManifest,
    InputSpec,
    OutputContract,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
)


@manifest()
def trdh() -> FunctionManifest:
    return FunctionManifest(
        code='TRDH',
        name='Trading Hours',
        category=Category.MACRO,
        intent=(
            "Exchange trading hours from Awareness: open or closed right now (lunch breaks count as closed), today's"
            "session, next open and next close in UTC, early closes and holiday closures. Crypto venues are not listed."
        ),
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF, AssetClass.FUTURE, AssetClass.FX, AssetClass.CRYPTO, AssetClass.BOND, AssetClass.COMMODITY],
        inputs=[
            InputSpec(name='exchanges', label='Exchanges', control=ControlKind.MULTISELECT, required=False, description='Exchange MIC codes. Legacy names (NYSE, NASDAQ, LSE, TSE, HKEX, BIST, ...) are mapped.', options=['XNYS', 'XNAS', 'XLON', 'XFRA', 'XTKS', 'XHKG', 'XASX', 'XIST']),
            InputSpec(name='days', label='Days ahead', control=ControlKind.NUMBER, required=False, description='Look-ahead window in days, 1 to 60. Default 14.'),
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
            must_have=['exchanges'],
            rows=True,
            series=False,
            cards=False,
            warnings=True,
            next_actions=True,
        ),
        methodology=(
            "TRDH reads /calendar/sessions for each exchange and /calendar/holidays for their closures. is_open_now"
            "is true only inside a regular session and outside the lunch break. Boundaries are the next future"
            "session open and close in UTC. Early closes carry early_close and their local close time."
        ),
        field_dict={
            'exchanges[].is_open_now': FieldDef(description='True inside a regular session and outside the lunch break.', source='computed'),
            'exchanges[].next_open_utc': FieldDef(description='Next future session open, UTC.', source='awareness'),
            'exchanges[].sessions[].early_close': FieldDef(description='True when the session closes early.', source='awareness'),
            'exchanges[].closures[].kind': FieldDef(description='market_closed or early_close.', source='awareness'),
        },
        provenance=ProvenanceSpec(require_source_list=True, require_as_of=True, require_latency_ms=True),
        alerting=None,
        semantic_tests=[
            SemanticTest(name='trdh_tokyo_lunch_is_closed', description='Inside the Tokyo lunch break the exchange reports closed.', inputs={'exchanges': 'XTKS'}, assertions=['lunch_break_closed']),
            SemanticTest(name='trdh_nyse_early_close', description='The NYSE day after Thanksgiving carries early_close with a 13:00 local close.', inputs={'exchanges': 'XNYS'}, assertions=['early_close_flagged']),
        ],
    )


__all__ = ['trdh']
