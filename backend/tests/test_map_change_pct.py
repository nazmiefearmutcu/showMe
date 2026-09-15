"""Regression: MAP must not invent a -100% change when ``last`` is missing.

Before the fix, ``((last or 0) / (prev or 1) - 1) * 100 if prev else None``
turned every ``last=None`` quote into a -100% bar — the MAP heatmap ended
up red across every country whose ETF the provider failed for.

The 2026-09-15 provider rewrite routes MAP through the keyless
``showme.quotes.fetch_quote_snapshot`` service. These tests pin the same
honesty contract against the new provider: a missing ``last`` leg yields a
null change (never a fabricated -100%), and the row is kept visible as
``quote_type="unavailable"`` instead of being silently dropped.
"""
from __future__ import annotations

from typing import Any

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.screen import wmap
from showme.engine.functions.screen.wmap import MAPFunction


def _stub_quotes(
    monkeypatch: Any,
    quotes: dict[str, tuple[float | None, float | None]],
) -> None:
    """Route ``wmap.fetch_quote_snapshot`` to a synthetic {last, prev} table."""

    async def _fake(symbol: str) -> dict[str, Any]:
        last, prev = quotes.get(symbol, (None, None))
        return {"last": last, "previous_close": prev}

    monkeypatch.setattr(wmap, "fetch_quote_snapshot", _fake)


async def test_map_handles_missing_last_price_as_none(monkeypatch: Any) -> None:
    """If the provider has ``prev`` but ``last`` is missing, change_pct must be
    None — not -100% (i.e. the old ``(None or 0) / prev - 1`` bug)."""
    _stub_quotes(monkeypatch, {"SPY": (None, 450.0), "VGK": (60.0, 60.0)})
    fn = MAPFunction(FunctionDeps())
    res = await fn.execute(live=True, screen_timeout=3)
    # Live path with at least one valid (VGK) row.
    assert res.data["status"] == "ok"
    rows = {row["etf"]: row for row in res.data["rows"]}
    assert "VGK" in rows
    assert rows["VGK"]["change_pct"] == 0.0
    # SPY had ``last=None``: the row stays in the list as an explicit
    # ``unavailable`` row with a null change — never silently dropped and
    # never computed as -100%.
    assert rows["SPY"]["quote_type"] == "unavailable"
    assert rows["SPY"]["last"] is None
    assert rows["SPY"]["change_pct"] is None
    # The full market map still renders (no silent shrink).
    assert len(res.data["rows"]) == len(wmap._COUNTRY_ETFS)


async def test_map_change_pct_never_phantom_negative_full_drop(monkeypatch: Any) -> None:
    """No usable live row → the deterministic template fallback (unchanged
    shape) and never a -100% bar anywhere."""
    _stub_quotes(monkeypatch, {"SPY": (None, 450.0)})
    fn = MAPFunction(FunctionDeps())
    res = await fn.execute(live=True, screen_timeout=3)
    assert res.data["status"] == "provider_unavailable"
    assert res.metadata.get("fallback") is True
    # If MAP recomputes the synthetic -100% bug, every row's change_pct
    # would be -100. The fallback rows are the deterministic model template.
    for row in res.data["rows"]:
        chg = row.get("change_pct")
        assert chg != -100.0, "MAP must not invent a -100% drop for empty quotes"
        assert row["quote_type"] == "model"
