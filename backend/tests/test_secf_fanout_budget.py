"""SECF quote enrichment must respect the screen budget (wb1-g19 SECF#3 follow-up).

When the batch quote request consumes the whole screen budget, the bounded
per-symbol fan-out must not run on a floor budget beyond it. The helper's
contract is "the remaining screen budget", so an exhausted budget means no
extra provider calls and an explicit warning, with the symbols left to the
reference state.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any

from showme.engine.functions.screen._funcs import _secf_quote_rows


class _HangingBatchProvider:
    """Batch endpoint never answers in time; per-symbol path answers at once."""

    def __init__(self) -> None:
        self.batch_calls = 0
        self.fetch_calls = 0

    async def fetch_refdata_batch(self, symbols: list[str]) -> dict[str, Any]:
        self.batch_calls += 1
        await asyncio.sleep(30)
        return {}

    async def fetch(self, request: Any) -> Any:
        self.fetch_calls += 1
        return SimpleNamespace(
            last=100.0,
            close_prev=99.0,
            high_24h=101.0,
            low_24h=98.0,
            volume_24h=1000.0,
        )


def test_exhausted_budget_after_batch_timeout_skips_fan_out() -> None:
    provider = _HangingBatchProvider()
    started = time.monotonic()
    quotes, warnings = asyncio.run(
        _secf_quote_rows(
            provider,
            ["AAPL", "MSFT"],
            timeout=1.0,
            screen_timeout=0.5,
            concurrency=8,
        )
    )
    elapsed = time.monotonic() - started

    assert provider.batch_calls == 1
    assert provider.fetch_calls == 0, "no per-symbol calls once the screen budget is spent"
    assert quotes == []
    assert elapsed < 0.5 + 0.25, f"enrichment ran {elapsed:.2f}s on a 0.5s screen budget"
    assert any("exceeded" in warning for warning in warnings)
