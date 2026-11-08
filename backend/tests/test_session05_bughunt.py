"""S05 BUGHUNT regression guards.

Covers four observable bugs flagged during ShowMe BugHunt session 05:

* B4 (ECO):  the UK/GB country token must reach the calendar as one ISO code.
  Country normalisation moved to the Awareness service (2026-11); showme keeps
  only the ``calendar._common.country_codes`` fold of the legacy UK/EZ tokens and
  sends ISO-2 codes to Awareness.

* B6 (EQS):  the backend used to default to a hard-coded 15-symbol stub
  but the UI footer continued to label the universe "SP500", over-stating
  scanned coverage by ~485 symbols. ``_resolve_universe`` must now return
  a label that reflects what is actually scanned for every common
  universe-name string the UI sends.

These tests pin the labels and the alias map so the regressions cannot
quietly come back.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow `python -m pytest backend/tests/test_session05_bughunt.py` from the
# worktree root without an editable install of the backend package.
_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest  # noqa: E402

from showme.engine.functions.macro import eco as eco_mod  # noqa: E402
from showme.engine.functions.calendar._common import country_codes  # noqa: E402
from showme.engine.functions.equity import eqs as eqs_mod  # noqa: E402


# ── B4 — ECO country alias folding ────────────────────────────────────────

@pytest.mark.parametrize(
    "raw, iso",
    [
        ("GB", ["GB"]),
        ("UK", ["GB"]),  # legacy UI token folds onto the ISO-2 code Awareness keys on
        ("gb", ["GB"]),
        ("EZ", ["EU"]),
        ("us", ["US"]),
        ("JP", ["JP"]),
        ("TR", ["TR"]),
        ("ZZ", ["ZZ"]),  # unknown stays untouched, never normalised to a wrong neighbour
        ("ALL", []),  # ALL means no country filter
        ("", []),
        (None, []),
    ],
)
def test_country_codes_fold_legacy_tokens_and_pass_iso_through(raw, iso):
    """Country-name normalisation now lives in Awareness (the calendar contract sends ISO codes).
    showme only folds the legacy UK/EZ UI tokens; the long-form aliases such as 'United Kingdom'
    are Awareness's job and are no longer mapped here."""
    assert country_codes(raw) == iso


def test_eco_uk_request_is_sent_to_awareness_as_iso_gb_and_keeps_its_rows():
    """Replaces the old _normalize_events UK/GB alias tests: the request's UK token reaches
    Awareness as the ISO code GB, and the rows Awareness returns keep their country."""
    from datetime import datetime, timedelta, timezone

    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.data_sources.awareness import AwarenessResponse

    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    event = {
        "id": "gb-retail", "country": "GB", "currency": "GBP", "title": "Retail Sales",
        "category": "retail", "scheduled_at": tomorrow.isoformat(), "all_day": False, "importance": 2,
        "actual": None, "forecast": None, "previous": None, "revised": None, "actual_value": None,
        "forecast_value": None, "previous_value": None, "unit": "%", "surprise": None,
        "surprise_direction": None, "status": "scheduled", "description": None, "sources": [],
    }

    class _Fake:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        async def get(self, path, params=None):
            self.calls.append((path, dict(params or {})))
            data = [event] if path == "/calendar/economic" else []
            return AwarenessResponse(data=data, meta={"providers": [], "notes": [], "generated_at": None}, url=path)

    fake = _Fake()
    fn = eco_mod.ECOFunction(FunctionDeps())
    fn._awareness = fake
    result = asyncio.run(fn.execute(country="UK", days=14))

    econ_params = next(params for path, params in fake.calls if path == "/calendar/economic")
    assert econ_params["countries"] == "GB"
    assert result.data["status"] == "ok"
    assert [row["country"] for row in result.data["rows"]] == ["GB"]


# ── B6 — EQS universe label honesty ───────────────────────────────────────

def test_resolve_universe_sp500_returns_degraded_label_not_sp500():
    """Until the SP500 constituent file is bundled, the backend must NOT
    claim it scanned the S&P 500 when it only scanned the 15-symbol stub."""
    symbols, label = eqs_mod._resolve_universe("SP500")
    assert len(symbols) == 15
    assert "MEGA15" in label
    assert "SP500" in label  # acknowledges what was requested
    assert label != "SP500"  # but does NOT lie about coverage


def test_resolve_universe_mega15_passthrough():
    symbols, label = eqs_mod._resolve_universe("MEGA15")
    assert label == "MEGA15"
    assert len(symbols) == 15
    assert "AAPL" in symbols and "DIS" in symbols


def test_resolve_universe_tech10_preset():
    symbols, label = eqs_mod._resolve_universe("TECH10")
    assert label == "TECH10"
    assert len(symbols) == 10
    assert "AAPL" in symbols and "AMD" in symbols


def test_resolve_universe_custom_csv_string():
    symbols, label = eqs_mod._resolve_universe("AAPL, MSFT, NVDA")
    assert symbols == ["AAPL", "MSFT", "NVDA"]
    assert "3" in label  # surfaces the actual count


def test_resolve_universe_explicit_list():
    symbols, label = eqs_mod._resolve_universe(["nvda", "amd"])
    assert symbols == ["NVDA", "AMD"]
    assert "2" in label


def test_resolve_universe_empty_falls_back_to_mega15():
    symbols, label = eqs_mod._resolve_universe(None)
    assert label == "MEGA15"
    assert len(symbols) == 15
