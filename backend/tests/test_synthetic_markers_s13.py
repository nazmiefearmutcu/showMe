"""S13 BugHunt 2026-05-17 — pin the synthetic-source sanitiser gap.

`SYNTHETIC_SOURCE_MARKERS` in `showme/server.py` decides whether a payload's
`sources[]` label is "live" or "synthetic". The pre-fix tuple only matched
substrings template|sample|placeholder|synthetic|continuity. That gate
silently let internal template/fallback labels pass as live data:

  - TAUC: `treasury_auction_model`, `treasury_auction_fallback`
  - TLH:  `tax_loss_model`
  - TRA:  `total_return_model`
  - TLDR: `local_briefing_model`, `local_deterministic_tldr_*`

So users got fake auctions, fake tax-loss candidates, fake total-return
KPIs branded as live. S13 added the missing labels to the marker tuple;
this test pins each of them.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from showme.server import _has_live_source, _is_synthetic_source  # noqa: E402


def test_template_substring_markers_remain_classified_synthetic():
    for label in (
        "template_v1",
        "rss_sample",
        "placeholder",
        "synthetic_macro",
        "continuity_check",
    ):
        assert _is_synthetic_source(label), f"{label!r} should be synthetic"


def test_S13_added_markers_now_classified_synthetic():
    for label in (
        "treasury_auction_model",
        "treasury_auction_fallback",
        "tax_loss_model",
        "total_return_model",
        "local_briefing_model",
        "local_deterministic_tldr",
        "local_deterministic_tldr_v2",
    ):
        assert _is_synthetic_source(label), (
            f"{label!r} should be synthetic — S13 marker fix regression"
        )


def test_real_providers_remain_classified_live():
    for label in (
        "yfinance",
        "coingecko",
        "rss",
        "gdelt",
        "treasurydirect",
        "seekingalpha",
        "exchange_calendars",
        "order_history",
        "portfolio_state",
        "stress_scenarios",
    ):
        assert not _is_synthetic_source(label), (
            f"{label!r} should be live (not flagged by markers)"
        )


def test_has_live_source_mixed_sources():
    assert _has_live_source(["yfinance", "tax_loss_model"])
    assert not _has_live_source(["tax_loss_model", "total_return_model"])
    assert not _has_live_source([])
    assert not _has_live_source([""])
