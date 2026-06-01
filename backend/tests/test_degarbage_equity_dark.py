"""De-garbage regression tests for the DARK (dark-pool / FINRA ATS) function.

DARK previously returned a hardcoded dark_pool_pct=38.0 with synthetic
``recent_week_rows`` placeholders whenever ``self.deps.finra`` was absent
(the normal runtime path). It now fetches REAL keyless FINRA OTC Transparency
weekly ATS data and joins yfinance weekly volume for a genuine dark-pool %.

These tests assert:
  * an OK payload exposes real per-venue rows (NOT the old 38.0 constant /
    UBSA-MSPL-CROS placeholder venues) plus methodology;
  * the graceful provider_unavailable shape is honest (empty venues +
    next_actions) when the network is unavailable.

Live-network assertions are guarded: if the FINRA fetch raises a network
error (offline CI), the handler itself converts that into a
provider_unavailable payload, so these tests pass cleanly with or without
connectivity. Symbols are passed via the ``symbol`` param so the tests do
not depend on the Instrument constructor signature.
"""

from __future__ import annotations

import asyncio

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.equity.dark import DARKFunction


# Old placeholder constants that must never reappear on the happy path.
_PLACEHOLDER_VENUES = {"UBSA", "MSPL", "CROS", "JPMX", "IATS"}


def _run(coro):
    return asyncio.run(coro)


def test_dark_no_longer_returns_hardcoded_model() -> None:
    """Default path must hit FINRA, not the old dark_pool_model/38.0 stub."""
    fn = DARKFunction(deps=FunctionDeps())  # no finra adapter wired -> direct API
    result = _run(fn.execute(symbol="AAPL", weeks=8))
    data = result.data

    # Contract keys always present regardless of online/offline.
    assert data["symbol"] == "AAPL"
    assert data["status"] in {"ok", "empty", "provider_unavailable"}
    assert isinstance(data.get("methodology"), str) and data["methodology"]
    assert isinstance(data.get("field_dictionary"), dict) and data["field_dictionary"]
    assert isinstance(data.get("rows"), list)
    # The legacy hardcoded "dark_pool_model" source must be gone.
    assert "dark_pool_model" not in result.sources

    if data["status"] == "ok":
        # Real venue rows, not the synthetic placeholder set.
        venues = data["venues"]
        assert venues, "ok status must carry non-empty venue rows"
        for row in venues:
            assert "venue" in row and "ats_share_volume" in row
            assert row.get("source_mode") == "finra_otc_weekly_ats"
            pct = row.get("dark_pool_pct")
            if pct is not None:
                assert 0.0 <= pct <= 100.0
        # Card slots required by the manifest card_schema.
        cards = data["cards"]
        for slot in ("latest_dark_pool_pct", "latest_ats_volume", "venue_count",
                     "data_mode", "as_of"):
            assert slot in cards
    else:
        # provider_unavailable / empty: honest shape, no fabricated venues.
        assert data["venues"] == []
        assert data.get("next_actions"), "outage path must offer next_actions"


def test_dark_unknown_symbol_is_unavailable_not_fabricated() -> None:
    """A bogus symbol must not yield invented venue rows."""
    fn = DARKFunction(deps=FunctionDeps())
    result = _run(fn.execute(symbol="ZZZZZZ"))
    data = result.data
    assert data["status"] in {"provider_unavailable", "empty", "ok"}
    if data["status"] != "ok":
        assert data["venues"] == []
        assert data.get("next_actions")
    # Even if FINRA happened to return something, no synthetic placeholder rows.
    for row in data.get("venues", []):
        assert row.get("source_mode") == "finra_otc_weekly_ats"


def test_dark_unavailable_shape_helper() -> None:
    """The provider_unavailable helper is self-consistent and honest."""
    from showme.engine.functions.equity.dark import _unavailable

    payload = _unavailable("AAPL", "boom", ["finra: timeout"])
    assert payload["status"] == "provider_unavailable"
    assert payload["venues"] == []
    assert payload["rows"] == []
    assert payload["next_actions"]
    assert payload["cards"]["data_mode"] == "provider_unavailable"
    assert "boom" in payload["reason"]


def test_dark_stale_reason_flips_status() -> None:
    """A months-old latest week must be reported as stale/unavailable."""
    from showme.engine.functions.equity.dark import _stale_reason

    assert _stale_reason("1999-01-04") is not None
    assert _stale_reason("not-a-date") is not None
    assert _stale_reason(None) is None


@pytest.mark.parametrize("weeks,expected", [(0, 2), (1, 2), (8, 8), (50, 26)])
def test_dark_weeks_clamped(weeks: int, expected: int) -> None:
    """`weeks` input is clamped to the manifest [2, 26] range."""
    fn = DARKFunction(deps=FunctionDeps())
    result = _run(fn.execute(symbol="AAPL", weeks=weeks))
    data = result.data
    if data["status"] == "ok":
        assert len(data["by_week"]) <= expected
