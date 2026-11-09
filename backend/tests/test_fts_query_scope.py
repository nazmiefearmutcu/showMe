"""FTS query scope: the instrument symbol is prepended only when the user scoped it.

Regression for FTS#2 (fts.py prepended the router-injected default symbol, so
'supply chain disruption' searched AAPL-scoped text). The SEC adapter is a
recording fake, so no network is used.
"""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.fts import FTSFunction

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
TSLA = Instrument(symbol="TSLA", asset_class=AssetClass.EQUITY)


class _RecordingSec:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, query: str, forms: Any = None, start: Any = None, end: Any = None, limit: int = 50):
        self.queries.append(query)
        return []


def _query_sent(instrument: Instrument, **params: Any) -> str:
    sec = _RecordingSec()
    asyncio.run(FTSFunction(FunctionDeps(sec_efts=sec)).execute(instrument=instrument, **params))
    assert len(sec.queries) == 1
    return sec.queries[0]


def test_router_injected_symbol_is_not_prepended() -> None:
    # The router injects the default symbol and flags it __explicit_symbol=False.
    sent = _query_sent(AAPL, query="supply chain disruption", __explicit_symbol=False)
    assert sent == "supply chain disruption"


def test_query_text_is_sent_verbatim_without_symbol_scope() -> None:
    sent = _query_sent(TSLA, query="AAPL supply chain disruption", __explicit_symbol=False)
    assert sent == "AAPL supply chain disruption"


def test_missing_scope_flag_does_not_prepend() -> None:
    sent = _query_sent(AAPL, query="supply chain disruption")
    assert sent == "supply chain disruption"


def test_user_scoped_symbol_is_still_prepended() -> None:
    sent = _query_sent(AAPL, query="supply chain disruption", __explicit_symbol=True)
    assert sent == "AAPL supply chain disruption"
