"""DVD — Dividends for one symbol (Awareness calendar, Yahoo history, frequency summary)."""
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
def dvd() -> FunctionManifest:
    return FunctionManifest(
        code='DVD',
        name='Dividends',
        category=Category.EQUITIES,
        intent=(
            "Upcoming cash dividends with record, pay and annualised amounts from the Awareness calendar,"
            "plus the live dividend history and a summary of payment frequency. No template or model rows."
        ),
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF],
        inputs=[
            InputSpec(name='symbol', label='Symbol', control=ControlKind.SYMBOL_PICKER, required=True, description='Equity or ETF ticker, e.g. AAPL.'),
            InputSpec(name='history', label='Include history', control=ControlKind.BOOLEAN, required=False, description='Also load the live dividend history. Default true.'),
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
            must_have=['rows', 'summary'],
            rows=True,
            series=False,
            cards=False,
            warnings=True,
            next_actions=True,
        ),
        methodology=(
            "DVD reads /calendar/corporate (dividend, next 365 days) for the symbol. History is the live Yahoo"
            "event series for the last year. summary.annual_amount sums the last 12 months of history and"
            "frequency_guess counts those payments. Empty sources stay empty; nothing is filled in."
        ),
        field_dict={
            'upcoming[].date': FieldDef(description='Ex-dividend date.', source='awareness'),
            'upcoming[].amount': FieldDef(description='Cash dividend per share.', source='awareness', unit='USD'),
            'history[].amount': FieldDef(description='Cash dividend per share from the live event series.', source='yfinance', unit='USD'),
            'summary.frequency_guess': FieldDef(description='annual, semi-annual, quarterly, monthly or irregular.', source='computed'),
        },
        provenance=ProvenanceSpec(require_source_list=True, require_as_of=True, require_latency_ms=True),
        alerting=None,
        semantic_tests=[
            SemanticTest(name='dvd_upcoming_from_awareness', description='An Awareness dividend row becomes an upcoming row with record and pay dates.', inputs={'symbol': 'AAPL'}, assertions=['upcoming_rows_from_awareness']),
            SemanticTest(name='dvd_no_template_rows', description='Without provider rows the result is empty, never a template.', inputs={'symbol': 'ZZZZ'}, assertions=['status_empty']),
        ],
    )


__all__ = ['dvd']
