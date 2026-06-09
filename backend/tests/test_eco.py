"""ECO — honest synthetic-fallback behaviour.

When BOTH live calendar providers (TradingEconomics, Finnhub) fail or return
empty, ``ECOFunction`` falls back to a HARDCODED synthetic calendar
(``_calendar_feed_model``). Before the honesty fix this fallback was silent:
``source_mode`` flipped to ``"calendar_feed_model"`` but no warning told the
caller the schedule + values were illustrative, and there was no machine
``as_of`` stamp for freshness. These tests pin the honest contract:

  - both providers failing → ``source_mode``/``sources`` is
    ``"calendar_feed_model"``;
  - a warning mentioning the synthetic / örnek fallback is surfaced;
  - the payload carries a parseable ISO ``as_of`` for real freshness;
  - the synthetic calendar does NOT print fabricated ``actual`` values
    (past-event actuals are nulled so only the schedule is shown).
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest  # noqa: E402

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.functions.macro import eco as eco_mod  # noqa: E402


class _FailingProvider:
    """Stand-in calendar provider whose async call always raises."""

    async def calendar(self, *args, **kwargs):
        raise RuntimeError("provider down")

    async def economic_calendar(self, *args, **kwargs):
        raise RuntimeError("provider down")


def _run(coro):
    return asyncio.run(coro)


def test_both_providers_failing_falls_back_to_synthetic_with_honest_warning():
    """Force BOTH live providers to fail → synthetic calendar, honestly flagged."""
    deps = FunctionDeps(
        tradingeconomics=_FailingProvider(),
        finnhub=_FailingProvider(),
    )
    fn = eco_mod.ECOFunction(deps=deps)
    result = _run(fn.execute(country="US", live_calendar=True, days=30))

    # 1) source mode + sources flag the synthetic fallback.
    assert result.data["source_mode"] == "calendar_feed_model"
    assert result.sources == ["calendar_feed_model"]

    # 2) a warning mentions the synthetic / örnek fallback so it surfaces
    #    honestly (NOT just the raw provider error strings).
    warning_blob = " ".join(result.warnings).lower()
    assert "örnek" in warning_blob or "sentetik" in warning_blob or "synthetic" in warning_blob
    # the original provider errors are still present for debugging.
    assert any("tradingeconomics" in w for w in result.warnings)
    assert any("finnhub" in w for w in result.warnings)

    # 3) machine-readable freshness stamp is a parseable ISO timestamp.
    as_of = result.data["as_of"]
    assert isinstance(as_of, str) and as_of
    parsed = datetime.fromisoformat(as_of)
    assert parsed is not None

    # 4) the synthetic calendar must NOT print fabricated actual values:
    #    every row's actual is None (schedule only, no fake prints).
    assert result.data["events"], "synthetic calendar should still show the schedule"
    assert all(row.get("actual") is None for row in result.data["events"])
    # …and consequently surprise is never a fabricated number.
    assert all(row.get("surprise") is None for row in result.data["events"])


def test_live_provider_success_is_not_flagged_synthetic():
    """When TradingEconomics returns rows, source_mode is live and there is
    NO synthetic warning."""

    class _LiveTE:
        async def calendar(self, *args, **kwargs):
            return [
                {
                    "country": "US",
                    "event": "CPI YoY",
                    "date": None,
                    "importance": "high",
                    "forecast": 3.1,
                    "actual": 3.2,
                    "previous": 3.0,
                    "unit": "%",
                },
            ]

    deps = FunctionDeps(tradingeconomics=_LiveTE(), finnhub=_FailingProvider())
    fn = eco_mod.ECOFunction(deps=deps)
    result = _run(fn.execute(country="US", live_calendar=True, days=30))

    assert result.data["source_mode"] == "tradingeconomics"
    assert result.sources == ["tradingeconomics"]
    warning_blob = " ".join(result.warnings).lower()
    assert "örnek" not in warning_blob and "sentetik" not in warning_blob
    # live actual is preserved (real print, not nulled).
    assert any(row.get("actual") == 3.2 for row in result.data["events"])
    # as_of is still present for freshness on the live path.
    assert isinstance(result.data["as_of"], str) and result.data["as_of"]


def test_synthetic_model_actuals_are_nulled_at_source():
    """The hardcoded calendar template itself must not carry fabricated
    actual prints (the honesty fix at the data source)."""
    events = eco_mod._calendar_feed_model("US", None)
    assert events, "template should produce rows"
    assert all(item["actual"] is None for item in events)
    # forecast / previous schedule context is still allowed (estimates, not prints).
    assert any(item["forecast"] is not None for item in events)
