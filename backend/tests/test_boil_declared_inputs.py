"""BOIL#3 — every input BOIL advertises is honoured, or it is not advertised.

The manifest used to expose range, interval, show_spread and provider_mode.
The handler read only days/live/benchmark/contract: show_spread had no
effect (the spread was always returned) and range/interval/provider_mode were
ignored. BOIL now honours show_spread and no longer advertises the inputs it
cannot honour (the pane's HISTORY control drives `days`).

No live network: the yfinance provider is a stub.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from showme.engine.core.base_data_source import DataKind
from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.commodity._funcs import BOILFunction
from showme.manifest.seeds.boil_seed import boil


class _PairYfinance:
    def __init__(self) -> None:
        self.quotes = {"CL=F": (78.0, 77.5), "BZ=F": (82.0, 81.0)}

    async def fetch(self, request: Any) -> Any:
        if request.kind == DataKind.OHLCV:
            raise RuntimeError("no history in this fixture")
        symbol = request.instrument.symbol
        last, prev = self.quotes[symbol]
        return SimpleNamespace(
            last=last,
            close_prev=prev,
            high_24h=None,
            low_24h=None,
            open_24h=None,
            volume_24h=None,
            source="yfinance",
            timestamp=datetime.now(UTC),
        )


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _fn() -> BOILFunction:
    return BOILFunction(deps=FunctionDeps(yfinance=_PairYfinance()))


def test_show_spread_true_returns_the_brent_minus_wti_spread() -> None:
    inst = Instrument(symbol="CL=F", asset_class=AssetClass.COMMODITY)
    data = _run(_fn().execute(instrument=inst, show_spread=True)).data
    assert data["spread"] == 4.0
    assert data["show_spread"] is True


def test_show_spread_false_suppresses_the_spread_envelope() -> None:
    inst = Instrument(symbol="CL=F", asset_class=AssetClass.COMMODITY)
    data = _run(_fn().execute(instrument=inst, show_spread=False)).data
    assert data["spread"] is None
    assert data["show_spread"] is False
    # The two contract rows are still served; only the spread is gated.
    assert [row["symbol"] for row in data["rows"]] == ["CL=F", "BZ=F"]


def test_show_spread_string_false_is_honoured() -> None:
    inst = Instrument(symbol="CL=F", asset_class=AssetClass.COMMODITY)
    data = _run(_fn().execute(instrument=inst, show_spread="false")).data
    assert data["spread"] is None


def test_show_spread_defaults_to_on_like_the_manifest() -> None:
    inst = Instrument(symbol="CL=F", asset_class=AssetClass.COMMODITY)
    data = _run(_fn().execute(instrument=inst)).data
    assert data["spread"] == 4.0


def test_manifest_only_declares_inputs_the_handler_reads() -> None:
    declared = {spec.name for spec in boil.inputs}
    # contract -> benchmark selector, show_spread -> spread gate. Anything else
    # advertised here would be an input the handler silently ignores.
    assert declared <= {"contract", "show_spread"}, declared
    assert "show_spread" in declared
