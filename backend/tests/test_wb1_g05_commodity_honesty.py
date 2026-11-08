"""wb1-g05 honesty fixes: ASOF-7 (LLM daily cap day boundary), NGAS#1
(unsupported contract is not substituted), WETR#2/#3/#5/R1 (Weather Trends
provenance, risk taxonomy, labels and provider-outage rows).

Network is never touched: providers and fetchers are patched with fakes.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

import pytest

from showme.engine.core.base_function import FunctionDeps


# ─────────────────────────────────────────────────────────────────────────
# ASOF-7 — daily LLM cap counts entries by their real local day
# ─────────────────────────────────────────────────────────────────────────


def test_asof7_today_spend_counts_entry_stamped_after_local_midnight(tmp_path: Path) -> None:
    from showme.llm import CostEntry, CostLedger

    # 00:30 on the LOCAL calendar day, written as a UTC ISO stamp the way
    # llm_plan_for records it. In UTC+ zones this UTC string still carries
    # the previous UTC date, so a prefix match on the local date misses it.
    local_0030 = datetime.combine(date.today(), time(0, 30)).astimezone()
    ts = local_0030.astimezone(timezone.utc).isoformat()
    led = CostLedger(path=tmp_path / "costs.json")
    led.append(CostEntry(
        ts=ts, provider="anthropic", model="claude-haiku-4-5",
        input_tokens=0, output_tokens=0, usd=0.25,
    ))
    assert led.today_spend() == pytest.approx(0.25)


def test_asof7_today_spend_excludes_yesterday_local(tmp_path: Path) -> None:
    from datetime import timedelta

    from showme.llm import CostEntry, CostLedger

    yesterday_noon = datetime.combine(date.today() - timedelta(days=1), time(12, 0)).astimezone()
    led = CostLedger(path=tmp_path / "costs.json")
    led.append(CostEntry(
        ts=yesterday_noon.astimezone(timezone.utc).isoformat(), provider="x", model="y",
        input_tokens=0, output_tokens=0, usd=0.5,
    ))
    assert led.today_spend() == pytest.approx(0.0)
