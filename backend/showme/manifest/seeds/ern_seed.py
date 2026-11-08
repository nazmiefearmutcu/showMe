"""ERN — Earnings calendar (Awareness corporate calendar, BMO/AMC timing, watchlist flag)."""
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
def ern() -> FunctionManifest:
    return FunctionManifest(
        code='ERN',
        name='Earnings Calendar',
        category=Category.MACRO,
        intent=(
            "Scheduled company earnings reports from the Awareness corporate calendar: date, before-open or after-close"
            "timing, EPS consensus, estimate count and market cap, with a watchlist highlight and per-day counts."
        ),
        asset_classes=[],
        inputs=[
            InputSpec(name='from', label='Start date', control=ControlKind.TEXT, required=False, description='Start date YYYY-MM-DD. Default today (UTC).'),
            InputSpec(name='days', label='Window (days)', control=ControlKind.NUMBER, required=False, description='Days ahead from the start date, 1 to 30. Default 7.'),
            InputSpec(name='symbols', label='Symbols', control=ControlKind.TEXT, required=False, description='Optional comma-separated tickers to restrict the list.'),
            InputSpec(name='min_market_cap', label='Minimum market cap', control=ControlKind.NUMBER, required=False, description='Keep companies at or above this market cap in USD.'),
            InputSpec(name='time_of_day', label='Report timing', control=ControlKind.SELECT, required=False, description='bmo (before open) or amc (after close).', options=['bmo', 'amc']),
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
            must_have=['rows', 'by_day'],
            rows=True,
            series=False,
            cards=False,
            warnings=True,
            next_actions=True,
        ),
        methodology=(
            "ERN reads /calendar/corporate (earnings) for the window and optional symbols. time_of_day is bmo, amc"
            "or unknown when the provider did not state it. Rows sort by date, then market cap descending."
            "in_watchlist marks symbols on the Awareness watchlist. Nothing is estimated."
        ),
        field_dict={
            'rows[].date': FieldDef(description='Scheduled report date.', source='awareness'),
            'rows[].time_of_day': FieldDef(description='bmo, amc or unknown.', source='awareness'),
            'rows[].eps_estimate': FieldDef(description='Consensus EPS for the quarter.', source='awareness'),
            'rows[].num_estimates': FieldDef(description='Analyst estimates behind the consensus.', source='awareness'),
            'rows[].market_cap': FieldDef(description='Market capitalisation reported by the provider.', source='awareness', unit='USD'),
            'rows[].in_watchlist': FieldDef(description='True when the symbol is on the Awareness watchlist.', source='awareness'),
        },
        provenance=ProvenanceSpec(require_source_list=True, require_as_of=True, require_latency_ms=True),
        alerting=None,
        semantic_tests=[
            SemanticTest(name='ern_sorted_by_date_then_market_cap', description='Rows sort by date, then larger market cap first.', inputs={'days': 7}, assertions=['sorted_date_then_cap']),
            SemanticTest(name='ern_watchlist_flag', description='A watchlisted ticker in the window is flagged in_watchlist.', inputs={'days': 7}, assertions=['watchlist_flagged']),
        ],
    )


__all__ = ['ern']
