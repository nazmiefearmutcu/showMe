"""CSRC#2 — the pane's ALL-sectors query must not drop contracts that have no curated volume.

Reference rows carry no volume (volume is provider session data). The ALL predicate used to
be ``volume >= 0``, which the DSL evaluates False for a null volume, so 20 of 29 contracts
vanished without any warning. The ALL query must select every contract the sector filter
selects, regardless of volume.
"""
from __future__ import annotations

import asyncio

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.screen._funcs import CSRCFunction, _commodity_reference_rows

# The pane's exact all-sectors predicate (ui/src/functions/CSRC.tsx MATCH_ALL_QUERY).
ALL_SECTORS_QUERY = 'sector != "NONE"'


def _run(**params):
    return asyncio.run(CSRCFunction(deps=FunctionDeps()).execute(reference=True, limit=100, **params))


def test_all_sectors_query_keeps_every_reference_contract() -> None:
    total = len(_commodity_reference_rows())
    result = _run(query=ALL_SECTORS_QUERY)
    assert result.data["scanned"] == total
    assert result.data["matched"] == total, (result.data["matched"], total)
    symbols = {row["symbol"] for row in result.data["rows"]}
    # Contracts without a curated volume (e.g. the lithium and uranium rows) stay in the ALL view.
    assert {"LTH=F", "UX=F", "HE=F", "RB=F"} <= symbols


def test_all_sectors_query_is_not_a_volume_predicate() -> None:
    # Guard against the volume predicate returning: it silently drops null-volume contracts.
    result = _run(query=ALL_SECTORS_QUERY)
    assert result.data["matched"] > 9, result.data["matched"]
