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


# ─────────────────────────────────────────────────────────────────────────
# NGAS#1 — a contract NGAS cannot serve is an explicit state, not Henry Hub
# ─────────────────────────────────────────────────────────────────────────


def _patch_snapshot(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    from showme.engine.functions.commodity import _funcs

    async def _fake_snapshot(_yf: Any, symbol: str, **_kw: Any) -> tuple[Any, list[Any], list[str]]:
        calls.append(symbol)
        row = {
            "symbol": symbol, "name": "Henry Hub Natural Gas", "unit": "USD/MMBtu",
            "last": 2.975, "change_pct": 1.2, "as_of": "2026-09-07T22:15:56+00:00",
        }
        return row, [{"date": "2026-09-05", "close": 2.975}], []

    monkeypatch.setattr(_funcs, "_contract_snapshot", _fake_snapshot)


def test_ngas1_ttf_request_is_unsupported_not_served_as_henry_hub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from showme.engine.functions.commodity._funcs import NGASFunction

    snapshot_calls: list[str] = []
    _patch_snapshot(monkeypatch, snapshot_calls)
    result = asyncio.run(
        NGASFunction(FunctionDeps(yfinance=object())).execute(contract="TTF=F")
    )
    assert result.data["status"] == "unsupported_contract"
    assert result.data["rows"] == []
    assert result.data["history"] == []
    assert result.data["reason"]
    assert snapshot_calls == [], "no quote may be fetched for an unsupported contract"
    assert "2.975" not in str(result.data), "no Henry Hub quote may leak into the response"
    assert result.data.get("source_mode") is None, "no live source may be claimed"


def test_ngas1_ng_f_still_serves_the_live_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    from showme.engine.functions.commodity._funcs import NGASFunction

    snapshot_calls: list[str] = []
    _patch_snapshot(monkeypatch, snapshot_calls)
    result = asyncio.run(
        NGASFunction(FunctionDeps(yfinance=object())).execute(contract="NG=F")
    )
    assert result.data["status"] == "ok"
    assert result.data["source_mode"] == "live_yfinance"
    assert result.data["rows"][0]["symbol"] == "NG=F"
    assert snapshot_calls == ["NG=F"]


# ─────────────────────────────────────────────────────────────────────────
# WETR-R1 — a provider outage carries no weather rows (no synthetic model)
# ─────────────────────────────────────────────────────────────────────────


class _FailingOpenMeteo:
    def __init__(self) -> None:
        self.calls = 0

    async def onecall(self, lat: float, lon: float, days: int = 10) -> dict[str, Any]:  # noqa: ARG002
        self.calls += 1
        raise RuntimeError("open-meteo timeout")


def test_wetr_r1_provider_outage_returns_no_synthetic_rows() -> None:
    from showme.engine.functions.commodity._funcs import WETRFunction

    fake = _FailingOpenMeteo()
    result = asyncio.run(WETRFunction(FunctionDeps(open_meteo=fake)).execute(location="EU_NW"))
    assert fake.calls == 1
    assert result.data["status"] == "provider_unavailable"
    assert result.data["rows"] == [], "an outage must not serve invented weather rows"
    assert result.data["history"] == []
    assert result.data["risk_flags"] == []
    assert result.data["source_mode"] != "seasonal_model"
    assert result.sources == []
    assert result.data["reason"]


def test_wetr_r1_no_provider_wired_returns_no_synthetic_rows() -> None:
    from showme.engine.functions.commodity._funcs import WETRFunction

    result = asyncio.run(WETRFunction(FunctionDeps()).execute(location="BRAZIL_SE"))
    assert result.data["status"] == "provider_unavailable"
    assert result.data["rows"] == []
    assert result.sources == []


def test_wetr_reference_opt_in_still_serves_labelled_model_rows() -> None:
    from showme.engine.functions.commodity._funcs import WETRFunction

    class _Never:
        calls = 0

        async def onecall(self, *_a: Any, **_k: Any) -> dict[str, Any]:
            raise AssertionError("reference=true must not query the provider")

    result = asyncio.run(WETRFunction(FunctionDeps(open_meteo=_Never())).execute(reference=True))
    assert result.data["status"] == "reference_model"
    assert result.data["source_mode"] == "seasonal_model"
    assert result.data["rows"], "the explicit reference opt-in keeps its labelled rows"
    assert all(row["source_mode"] == "seasonal_model" for row in result.data["rows"])
    assert result.metadata.get("data_mode") == "modeled"
