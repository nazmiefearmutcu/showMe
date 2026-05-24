"""S05 BUGHUNT regression guards.

Covers four observable bugs flagged during ShowMe BugHunt session 05:

* B4 (ECO):  trading-economics returns ``country: "UK"``/``"United Kingdom"``
  while the UI used to send ``GB``. Without alias folding, live UK calendar
  prints were silently filtered out by the backend equality check. The
  canonicaliser in ``eco._canonical_country`` must fold both the old "GB"
  payloads and the canonical "UK"/"United Kingdom" provider strings onto
  the same token. The full ``_normalize_events`` path must keep an event
  whose ``country`` field reads ``"United Kingdom"`` when the request asks
  for ``"UK"``.

* B6 (EQS):  the backend used to default to a hard-coded 15-symbol stub
  but the UI footer continued to label the universe "SP500", over-stating
  scanned coverage by ~485 symbols. ``_resolve_universe`` must now return
  a label that reflects what is actually scanned for every common
  universe-name string the UI sends.

These tests pin the labels and the alias map so the regressions cannot
quietly come back.
"""

from __future__ import annotations

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
from showme.engine.functions.equity import eqs as eqs_mod  # noqa: E402


# ── B4 — ECO country alias folding ────────────────────────────────────────

@pytest.mark.parametrize(
    "raw, canonical",
    [
        ("GB", "UK"),
        ("gbr", "UK"),
        ("United Kingdom", "UK"),
        ("Britain", "UK"),
        ("UK", "UK"),
        ("EZ", "EU"),
        ("Eurozone", "EU"),
        ("European Union", "EU"),
        ("USA", "US"),
        ("United States", "US"),
        ("us", "US"),
        ("Türkiye", "TR"),
        ("turkey", "TR"),
        ("JP", "JP"),
        ("Japan", "JP"),
        ("", ""),
        (None, ""),
        ("ZZ", "ZZ"),  # unknown stays untouched, never normalised to a wrong neighbour
    ],
)
def test_canonical_country_folds_known_aliases(raw, canonical):
    assert eco_mod._canonical_country(raw) == canonical


def test_normalize_events_keeps_uk_event_when_request_is_uk_string():
    """The exact scenario reported in B4: live provider tags the row as
    ``country: 'United Kingdom'`` while the request asks for ``country: 'UK'``.
    Without the alias, the row is silently dropped."""
    events = [
        {
            "country": "United Kingdom",
            "event": "BoE Rate Decision",
            "date": None,
            "importance": "high",
            "forecast": 5.25,
            "actual": 5.25,
            "previous": 5.25,
            "unit": "%",
        },
        {
            "country": "US",
            "event": "CPI",
            "date": None,
            "importance": "high",
        },
    ]
    rows = eco_mod._normalize_events(
        events, country="UK", importance=None, days=14,
    )
    countries = {r["country"] for r in rows}
    assert "UK" in countries
    assert "US" not in countries  # UK request must filter out US
    boe = next(r for r in rows if r["event"] == "BoE Rate Decision")
    assert boe["country"] == "UK"


def test_normalize_events_legacy_gb_request_still_works():
    """Older clients persisted ``country: 'GB'`` in localStorage. Backend
    alias map must keep them working — the canonicaliser folds both onto
    the same internal key."""
    events = [
        {"country": "UK", "event": "Retail Sales", "importance": "medium"},
    ]
    rows = eco_mod._normalize_events(
        events, country="GB", importance=None, days=14,
    )
    assert len(rows) == 1
    assert rows[0]["country"] == "UK"


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
