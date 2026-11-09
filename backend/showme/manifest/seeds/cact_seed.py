"""CACT — Corporate actions for one symbol (dividends, splits and 8-K filings, de-duplicated)."""
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
def cact() -> FunctionManifest:
    return FunctionManifest(
        code='CACT',
        name='Corporate Actions',
        category=Category.EQUITIES,
        intent=(
            "Dividends, splits and material 8-K filings for one equity, merged from the Awareness calendar and SEC"
            "index, with duplicates across providers removed. Every row names its source."
        ),
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF],
        inputs=[
            InputSpec(name='symbol', label='Symbol', control=ControlKind.SYMBOL_PICKER, required=True, description='Equity or ETF ticker, e.g. AAPL.'),
            InputSpec(name='days_back', label='Days back', control=ControlKind.NUMBER, required=False, description='Lookback in days, 0 to 3650. Default 365.'),
            InputSpec(name='days_ahead', label='Days ahead', control=ControlKind.NUMBER, required=False, description='Look-ahead in days, 0 to 365. Default 90.'),
        ],
        provider_chain=ProviderChain(
            primary="awareness",
            fallbacks=["yfinance"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=300, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=['rows'],
            rows=True,
            series=False,
            cards=False,
            warnings=True,
            next_actions=True,
        ),
        methodology=(
            "CACT merges /calendar/corporate (dividend, split), /filings (8-K) and the Yahoo event series as a"
            "supplement. Duplicates are dropped on (action type, date, value). Each row carries its source"
            "(awareness:corporate, awareness:filings or yfinance). Awareness down gives provider_unavailable."
        ),
        field_dict={
            'rows[].action_type': FieldDef(description='dividend, split or 8-K.', source='computed'),
            'rows[].event_date': FieldDef(description='Event or filing date.', source='awareness'),
            'rows[].value': FieldDef(description='Dividend per share or split ratio; null for 8-K rows.', source='awareness'),
            'rows[].source': FieldDef(description='Provider the row came from.', source='computed'),
        },
        provenance=ProvenanceSpec(require_source_list=True, require_as_of=True, require_latency_ms=True),
        alerting=None,
        semantic_tests=[
            SemanticTest(name='cact_dedupes_across_providers', description='The same dividend from Awareness and Yahoo appears once.', inputs={'symbol': 'AAPL'}, assertions=['one_row_per_action_date_value']),
            SemanticTest(name='cact_requires_symbol', description='A missing symbol answers input_required.', inputs={}, assertions=['status_input_required']),
        ],
    )


__all__ = ['cact']
