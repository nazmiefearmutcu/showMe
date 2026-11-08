"""EVTS — Corporate events for one symbol (Awareness corporate calendar and filings index)."""
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
def evts() -> FunctionManifest:
    return FunctionManifest(
        code='EVTS',
        name='Corporate Events',
        category=Category.NEWS_INTEL,
        intent=(
            "Dated corporate events for one equity from Awareness: earnings, dividends, splits, IPOs and SEC filings."
            "Rows are split into upcoming (ascending) and recent (descending). Empty means no dated events in the window."
        ),
        asset_classes=[AssetClass.EQUITY],
        inputs=[
            InputSpec(name='symbol', label='Symbol', control=ControlKind.SYMBOL_PICKER, required=True, description='Equity ticker, e.g. AAPL.'),
            InputSpec(name='days_back', label='Days back', control=ControlKind.NUMBER, required=False, description='Lookback in days, 0 to 730. Default 90.'),
            InputSpec(name='days_ahead', label='Days ahead', control=ControlKind.NUMBER, required=False, description='Look-ahead in days, 0 to 730. Default 180.'),
            InputSpec(name='types', label='Event types', control=ControlKind.MULTISELECT, required=False, description='Subset of earnings, dividend, split, ipo, filing.', options=['earnings', 'dividend', 'split', 'ipo', 'filing']),
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
            must_have=['rows'],
            rows=True,
            series=False,
            cards=False,
            warnings=True,
            next_actions=True,
        ),
        methodology=(
            "EVTS queries /calendar/corporate for the symbol (earnings, dividend, split, ipo) and /filings for"
            "SEC filings. Rows carry type, date, company and the provider fields. Upcoming and recent groups"
            "are sorted by date. Nothing is estimated; missing providers are reported as warnings."
        ),
        field_dict={
            'rows[].date': FieldDef(description='Event date (YYYY-MM-DD).', source='awareness'),
            'rows[].type': FieldDef(description='earnings, dividend, split, ipo or filing.', source='awareness'),
            'rows[].details': FieldDef(description='Provider fields for the event (EPS estimate, amount, ratio, form).', source='awareness'),
        },
        provenance=ProvenanceSpec(require_source_list=True, require_as_of=True, require_latency_ms=True),
        alerting=None,
        semantic_tests=[
            SemanticTest(name='evts_sorted_upcoming_then_recent', description='Upcoming rows ascend, recent rows descend, rows = upcoming + recent.', inputs={'symbol': 'AAPL'}, assertions=['upcoming_ascending', 'recent_descending']),
            SemanticTest(name='evts_requires_symbol', description='A missing symbol answers input_required.', inputs={}, assertions=['status_input_required']),
        ],
    )


__all__ = ['evts']
