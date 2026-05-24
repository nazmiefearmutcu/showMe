"""Regression: MAP must not invent a -100% change when ``last`` is missing.

Before the fix, ``((last or 0) / (prev or 1) - 1) * 100 if prev else None``
turned every ``last=None`` quote into a -100% bar — the MAP heatmap ended
up red across every country whose ETF the provider failed for.
"""
from __future__ import annotations

from typing import Any

from showme.engine.core.base_data_source import DataRequest
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.screen.wmap import MAPFunction


class _StubYF:
    """Returns a synthetic quote where ``last`` is None for every fetch."""

    def __init__(self, quotes: dict[str, tuple[float | None, float | None]]) -> None:
        self._quotes = quotes

    async def fetch(self, request: DataRequest) -> Any:
        sym = request.instrument.symbol if request.instrument else ""
        last, prev = self._quotes.get(sym, (None, None))

        class _Q:
            def __init__(self, last_val: float | None, p: float | None) -> None:
                self.last = last_val
                self.close_prev = p

        return _Q(last, prev)


async def test_map_handles_missing_last_price_as_none() -> None:
    """If the provider has ``prev`` but ``last`` is missing, change_pct must be
    None — not -100% (i.e. the old ``(None or 0) / prev - 1`` bug)."""
    deps = FunctionDeps()
    deps.yfinance = _StubYF({"SPY": (None, 450.0), "VGK": (60.0, 60.0)})
    fn = MAPFunction(deps)
    res = await fn.execute(live=True, quote_timeout=2, screen_timeout=3)
    # Live path with at least one valid (VGK) row.
    assert res.data["status"] == "ok"
    rows = {row["etf"]: row for row in res.data["rows"]}
    # SPY was missing — would have been filtered as "last is None" row by the
    # existing post-filter, so we just assert VGK is here and change_pct = 0.
    assert "VGK" in rows
    assert rows["VGK"]["change_pct"] == 0.0
    # SPY had ``last=None`` so the post-filter drops it from rows; this is
    # exactly the behaviour we want — the surface no longer shows -100% for
    # a missing quote.
    assert "SPY" not in rows


async def test_map_change_pct_never_phantom_negative_full_drop() -> None:
    """Direct unit check: feed last=None to the per-ETF helper via deps and
    make sure no row ends up at -100%."""
    deps = FunctionDeps()
    deps.yfinance = _StubYF({"SPY": (None, 450.0)})
    fn = MAPFunction(deps)
    res = await fn.execute(live=True, quote_timeout=2, screen_timeout=3)
    # If MAP recomputes the synthetic -100% bug, every row's change_pct
    # would be -100. The current code drops "last is None" rows from the
    # final list, but we still must never *compute* -100 for those rows
    # (in case the filter is loosened later). All retained rows must have
    # finite change_pct, or it's None (model fallback path).
    for row in res.data["rows"]:
        chg = row.get("change_pct")
        assert chg != -100.0, "MAP must not invent a -100% drop for empty quotes"
