"""Session-06 bug-hunt regression tests.

Pins backend P0 fixes for the 10 scope codes (EVTS, EXEC, FA, FLDS, FLY,
FORM4, FRD, FRH, FSRC, FTS):

1. ``SYNTHETIC_SOURCE_MARKERS`` now catches ``_model``-suffixed labels so
   FRH/FORM4/EVTS/FTS fabricated rows are suppressed by
   ``sanitize_function_payload``.
2. ``FORM4._fallback_form4`` no longer emits an all-None sentinel row.
3. ``FTS._fallback_hits`` was removed; offline/empty paths now return ``[]``.
4. ``FRH`` non-live check uses ``_truthy`` so ``live="false"`` (string)
   stays in the template path instead of going live.

Each test stays purely local — no sidecar boot required.
"""
from __future__ import annotations

import asyncio

import pytest

from showme import server
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity import form4 as form4_mod
from showme.engine.functions.equity import fts as fts_mod
from showme.engine.functions.screen import frh as frh_mod


# ─── 1. Synthetic markers catch *_model labels ───────────────────────────

def test_synthetic_markers_include_model_suffix() -> None:
    """`*_model` labels must be flagged so sanitize_function_payload hides them."""
    assert "_model" in server.SYNTHETIC_SOURCE_MARKERS

    assert server._is_synthetic_source("funding_rate_model")
    assert server._is_synthetic_source("form4_model")
    assert server._is_synthetic_source("corporate_events_model")
    assert server._is_synthetic_source("sec_search_model")
    # Live sources must NOT be flagged.
    assert not server._is_synthetic_source("yfinance")
    assert not server._is_synthetic_source("sec_edgar")
    assert not server._is_synthetic_source("binance")


# ─── 2. FORM4 fallback returns empty rows (no sentinel) ──────────────────

def test_form4_fallback_emits_empty_rows_and_actionable_next_actions() -> None:
    payload = form4_mod._fallback_form4("AAPL")
    assert payload["status"] == "provider_unavailable"
    assert payload["symbol"] == "AAPL"
    assert payload["rows"] == []
    assert payload["filings"] == []
    # next_actions should guide the user to a fix, not pretend data exists.
    assert isinstance(payload.get("next_actions"), list) and payload["next_actions"]


# ─── 3. FTS no-adapter path returns empty rows ───────────────────────────

def test_fts_no_adapter_returns_empty_rows() -> None:
    fn = fts_mod.FTSFunction(deps=None)
    instrument = Instrument(symbol="MSFT", asset_class=AssetClass.EQUITY)
    result = asyncio.run(fn.execute(instrument=instrument, query="risk factors", live=True))
    assert result.data["status"] == "provider_unavailable"
    assert result.data["rows"] == []
    # Must not advertise the now-removed `sec_search_model` synthetic label.
    assert "sec_search_model" not in (result.sources or [])
    assert "no_live_source" in (result.sources or [])


def test_fts_no_live_returns_empty_rows() -> None:
    """When live=false, FTS must also return empty rows (no sentinel)."""

    class _StubSec:
        async def search(self, *a, **kw):  # pragma: no cover
            raise AssertionError("sec_efts.search should not be called when live=false")

    class _Deps:
        sec_efts = _StubSec()

    fn = fts_mod.FTSFunction(deps=_Deps())
    instrument = Instrument(symbol="MSFT", asset_class=AssetClass.EQUITY)
    result = asyncio.run(fn.execute(instrument=instrument, query="risk", live=False))
    assert result.data["status"] == "provider_unavailable"
    assert result.data["rows"] == []


# ─── 4. FRH _truthy handling of "false" string ───────────────────────────

def test_frh_live_false_string_keeps_template_path() -> None:
    """`live="false"` (JSON string) must NOT route into the live exchange call."""
    fn = frh_mod.FRHFunction(deps=None)
    # If the truthy fix is missing, this triggers an httpx network call and
    # the test fails with a different error type.
    result = asyncio.run(fn.execute(symbols="BTCUSDT", live="false"))
    # Non-live path returns the deterministic template, label = funding_rate_model
    assert "funding_rate_model" in (result.sources or [])
    # And that label is suppressed by sanitize_function_payload (P0-1):
    payload = {"data": result.data, "sources": result.sources, "metadata": {}}
    sanitized = server.sanitize_function_payload("FRH", {}, payload)
    assert sanitized.get("metadata", {}).get("synthetic") is True


@pytest.mark.parametrize("val", ["0", "false", "False", "", "no", "off"])
def test_frh_falsy_strings_are_falsy(val: str) -> None:
    assert frh_mod._truthy(val) is False


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on"])
def test_frh_truthy_strings_are_truthy(val: str) -> None:
    assert frh_mod._truthy(val) is True
