"""WEI — the region parameter filters the LIVE path server-side (finding WEI#2).

The live overlay must return only the requested region's rows and report the
filtered universe size, not the full board. Offline: the quote provider is an
injected fake that resolves every symbol it is asked for.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.quote import Quote
from showme.engine.functions.screen._funcs import WEIFunction, _WORLD_INDEX_META, _world_index_symbols


class _AllResolveProvider:
    name = "yfinance"

    async def fetch(self, request: object) -> Quote | None:
        symbol = str(getattr(getattr(request, "instrument", None), "symbol", ""))
        return Quote(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            last=100.0,
            close_prev=99.0,
        )


def _live_region(region: str):
    return asyncio.run(
        WEIFunction(deps=FunctionDeps(yfinance=_AllResolveProvider())).execute(
            region=region, live=True
        )
    )


def test_live_path_returns_only_the_requested_region() -> None:
    out = _live_region("europe")
    assert out.data["status"] == "ok"
    assert out.data["source_mode"] == "yfinance_live"
    assert out.data["rows"], "expected europe rows"
    assert all(row["region"] == "europe" for row in out.data["rows"])


def test_live_path_universe_size_reports_the_filtered_count() -> None:
    out = _live_region("europe")
    expected = sum(1 for s in _world_index_symbols() if _WORLD_INDEX_META[s]["region"] == "europe")
    assert out.data["universe_size"] == expected
    assert len(out.data["rows"]) == expected


def test_live_path_all_region_keeps_the_full_board() -> None:
    out = _live_region("all")
    assert out.data["universe_size"] == len(_world_index_symbols())
    assert len(out.data["rows"]) == len(_world_index_symbols())
