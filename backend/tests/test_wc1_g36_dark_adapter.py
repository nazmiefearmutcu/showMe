"""wc1-g36 DARK-R1: an empty wired FINRA adapter frame is the answer.

When the wired adapter already queried FINRA and got no rows, DARK must not
send a second direct request to the same endpoint.
"""

from __future__ import annotations

import asyncio

import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.equity.dark import DARKFunction

import test_g3_finra_ats_window as g3


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- DARK-R1


class _EmptyWiredFinra:
    async def ats_weekly(self, symbol=None, limit=26):  # noqa: ANN001
        return pd.DataFrame()


def test_dark_empty_wired_adapter_does_not_requery_finra(monkeypatch) -> None:
    fake = g3.FakeFinra(g3._dataset())
    g3._patch_direct_finra(monkeypatch, fake)
    monkeypatch.setattr(DARKFunction, "_weekly_total_volume", lambda self, sym: g3._no_yfinance())

    result = _run(
        DARKFunction(deps=FunctionDeps(finra=_EmptyWiredFinra())).execute(symbol="AAPL", weeks=8)
    )

    assert fake.bodies == [], "the adapter already asked FINRA; no second direct request"
    assert result.data["status"] == "provider_unavailable"
    assert result.sources == []
