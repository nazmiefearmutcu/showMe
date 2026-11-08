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
    assert result.data["status"] == "input_error"
    assert result.data["error_kind"] == "unsupported_contract"
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


# ─────────────────────────────────────────────────────────────────────────
# WETR#2 — temp_c is the provider's daily mean, not the high/low midpoint
# ─────────────────────────────────────────────────────────────────────────


_OPEN_METEO_DAILY = {
    "time": ["2026-11-08", "2026-11-09"],
    "temperature_2m_mean": [16.5, 15.0],
    "temperature_2m_max": [22.0, 21.0],
    "temperature_2m_min": [14.0, 13.0],
    "precipitation_sum": [0.0, 2.5],
}


def test_wetr2_adapter_uses_provider_daily_mean_not_midpoint() -> None:
    from showme.engine.data_sources.alt.open_meteo_adapter import open_meteo_to_onecall

    out = open_meteo_to_onecall({"daily": _OPEN_METEO_DAILY})
    # midpoint of 22/14 would be 18.0; the provider mean is 16.5
    assert out["daily"][0]["temp"]["day"] == 16.5
    assert out["daily"][1]["temp"]["day"] == 15.0
    assert out["daily"][0]["temp"]["max"] == 22.0
    assert out["daily"][0]["temp"]["min"] == 14.0


def test_wetr2_adapter_requests_the_daily_mean_variable() -> None:
    from showme.engine.data_sources.alt.open_meteo_adapter import OpenMeteoAdapter

    seen: dict[str, Any] = {}

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"daily": _OPEN_METEO_DAILY}

    class _Client:
        async def get(self, url: str, params: dict[str, Any]) -> _Resp:
            seen.update(params)
            return _Resp()

    adapter = OpenMeteoAdapter()

    async def _client_() -> _Client:
        return _Client()

    adapter._client_ = _client_  # type: ignore[method-assign]
    out = asyncio.run(adapter.onecall(40.7, -74.0, days=2))
    assert "temperature_2m_mean" in seen["daily"].split(",")
    assert out["daily"][0]["temp"]["day"] == 16.5


def test_wetr2_payload_without_daily_mean_is_rejected_not_midpoint() -> None:
    from showme.engine.core.base_data_source import DataSourceError
    from showme.engine.data_sources.alt.open_meteo_adapter import open_meteo_to_onecall

    no_mean = {k: v for k, v in _OPEN_METEO_DAILY.items() if k != "temperature_2m_mean"}
    with pytest.raises(DataSourceError):
        open_meteo_to_onecall({"daily": no_mean})


def test_wetr2_live_rows_carry_the_provider_mean_as_temp_c() -> None:
    from showme.engine.data_sources.alt.open_meteo_adapter import open_meteo_to_onecall
    from showme.engine.functions.commodity._funcs import WETRFunction

    class _Fake:
        async def onecall(self, lat: float, lon: float, days: int = 10) -> dict[str, Any]:  # noqa: ARG002
            return open_meteo_to_onecall({"daily": _OPEN_METEO_DAILY})

    result = asyncio.run(WETRFunction(FunctionDeps(open_meteo=_Fake())).execute(days=2))
    assert result.data["status"] == "ok"
    assert [row["temp_c"] for row in result.data["rows"]] == [16.5, 15.0]


# ─────────────────────────────────────────────────────────────────────────
# WETR#3 — one risk taxonomy for live and model rows
# ─────────────────────────────────────────────────────────────────────────


def test_wetr3_live_path_flags_hot_dry_day_like_the_model_path() -> None:
    from showme.engine.functions.commodity._funcs import _normalise_weather_rows, _wetr_risk_flag

    # 25C mean with almost no rain: the model path flags dry_heat_watch.
    assert _wetr_risk_flag(25.0, 0.4) == "dry_heat_watch"
    data = {"daily": [{
        "dt": datetime(2026, 11, 8, tzinfo=timezone.utc).timestamp(),
        "temp": {"day": 25.0, "min": 20.0, "max": 30.0},
        "precipitation": 0.4,
    }]}
    rows = _normalise_weather_rows(
        data, 1, 0.0, 0.0, "US_GULF", "corn",
        source_mode="live_open_meteo", allow_model_fallback=False,
    )
    assert rows[0]["risk_flag"] == "dry_heat_watch"


def test_wetr3_model_rows_use_the_same_risk_helper() -> None:
    from showme.engine.functions.commodity._funcs import _weather_model_rows, _wetr_risk_flag

    for row in _weather_model_rows(16, 40.0, -74.0, "US_NORTHEAST", "corn"):
        expected = _wetr_risk_flag(row["temp_c"], row["precip_mm"])
        assert row["risk_flag"] == expected


# ─────────────────────────────────────────────────────────────────────────
# WETR#5 — a keyless model forecast is not labelled as official data
# ─────────────────────────────────────────────────────────────────────────


def test_wetr5_open_meteo_live_rows_do_not_claim_live_official() -> None:
    from showme.engine.functions.commodity._funcs import WETRFunction

    class _Fake:
        async def onecall(self, lat: float, lon: float, days: int = 10) -> dict[str, Any]:  # noqa: ARG002
            return {"daily": [{
                "dt": datetime(2026, 11, 8, tzinfo=timezone.utc).timestamp(),
                "temp": {"day": 12.0, "min": 8.0, "max": 16.0},
                "precipitation": 0.0,
            }]}

    result = asyncio.run(WETRFunction(FunctionDeps(open_meteo=_Fake())).execute())
    assert result.data["status"] == "ok"
    assert result.metadata.get("data_mode") != "live_official"
    # WETR#5: the label names the keyless provider, as live_yfinance does for
    # its keyless feed; "live" alone is not a canonical data_mode value.
    assert result.metadata.get("data_mode") == "live_open_meteo"


# ─────────────────────────────────────────────────────────────────────────
# WETR-R1 catalog — the seed text must describe the no-synthetic-rows outage
# ─────────────────────────────────────────────────────────────────────────


def test_wetr_r1_catalog_does_not_describe_synthetic_outage_rows() -> None:
    from showme.manifest.seeds import wetr_seed

    manifest = wetr_seed.wetr
    docstring = wetr_seed.__doc__ or ""
    methodology = manifest.methodology
    descriptions = " ".join(t.description for t in manifest.semantic_tests)

    # The module docstring and methodology must not promise the seasonal model
    # on an outage; only reference=true serves it.
    assert "outage serves the labelled seasonal-model fallback" not in docstring
    assert "outage downgrades" not in methodology
    assert "status is provider_unavailable" in methodology
    # The outage semantic test describes the empty provider_unavailable state.
    assert "labelled source_mode=seasonal_model" not in descriptions
    assert "returns status=provider_unavailable with no weather rows" in descriptions
    # The risk_flag label lists the real taxonomy (WETR#3), not the old one.
    risk_label = manifest.field_dict["rows[].risk_flag"].description
    assert "severe | hot | cold" not in risk_label
    assert "dry_heat_watch" in risk_label


def test_ngas_catalog_describes_only_henry_hub_units() -> None:
    from showme.manifest.seeds import ngas_seed

    manifest = ngas_seed.ngas
    docstring = ngas_seed.__doc__ or ""
    unit_label = manifest.field_dict["contract_unit"].description

    # NGAS#1: TTF is not served, so the seed text must not present it as a
    # served European cousin or quote its unit as if it were.
    assert "European TTF cousin as a price-action pane" not in docstring
    assert "TTF" not in unit_label
    assert "USD/MMBtu" in unit_label
