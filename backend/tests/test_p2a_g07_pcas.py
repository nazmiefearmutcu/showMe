"""P2A-G07 regression tests: PCAS (#4 multi-factor, #5 string flags)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio import pcas as pcas_mod
from showme.manifest import REGISTRY, load_seeds


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- PCAS helpers


class _FakeBook:
    def __init__(self, symbols):
        self.positions = [
            SimpleNamespace(
                instrument=Instrument(symbol=s, asset_class=AssetClass.EQUITY),
                quantity=10.0 + i,
                avg_cost=100.0 + 5 * i,
            )
            for i, s in enumerate(symbols)
        ]

    def import_legacy_crypto(self):  # pragma: no cover - not exercised
        pass


def _pcas(monkeypatch, symbols=("AAA", "BBB", "CCC", "DDD")):
    monkeypatch.setattr(pcas_mod, "PortfolioState", lambda *a, **k: _FakeBook(symbols))
    return pcas_mod.PCASFunction(FunctionDeps())


def _pcas_run(fn, **params):
    return _run(fn.execute(**params))


# ---------------------------------------------------------------- PCAS #5


def test_pcas_live_false_string_is_an_input_error_not_a_provider_outage(monkeypatch):
    res = _pcas_run(_pcas(monkeypatch), live="false")
    assert res.data["status"] == "input_error"
    assert "live" in res.data["reason"]


def test_pcas_live_prices_false_string_does_not_fetch_live_history(monkeypatch):
    fn = _pcas(monkeypatch)
    res = _pcas_run(fn, live="true", live_prices="false")
    # "false" must not be truthy: the template path is used, labelled as such.
    assert res.sources == ["portfolio_state_template_returns"]


# ---------------------------------------------------------------- PCAS #4


def test_pcas_multi_factor_returns_components_and_aggregate(monkeypatch):
    res = _pcas_run(_pcas(monkeypatch), live="true", n_factors=3, k_sigma=2.0)
    d = res.data
    for key in ("components", "shock_impacts", "aggregate_impact",
                "explained_variance", "data_mode", "as_of", "n_factors"):
        assert key in d, key
    assert d["n_factors"] == 3
    assert len(d["components"]) == 3
    assert [c["pc_index"] for c in d["components"]] == [0, 1, 2]
    total_pnl = sum(c["impact_value"] for c in d["shock_impacts"])
    assert d["aggregate_impact"] == pytest.approx(total_pnl, rel=1e-9, abs=1e-6)
    # Retained factors explain at most all of the variance.
    assert 0.0 <= d["explained_variance"] <= 1.0


def test_pcas_shock_set_applies_per_component_sigma(monkeypatch):
    res = _pcas_run(_pcas(monkeypatch), live="true", n_factors=2,
                    shock_set=[1.0, 2.0])
    sigmas = [c["shock_sigma"] for c in res.data["components"]]
    assert sigmas == [1.0, 2.0]


def test_pcas_shock_set_length_mismatch_is_an_input_error(monkeypatch):
    res = _pcas_run(_pcas(monkeypatch), live="true", n_factors=3, shock_set=[1.0])
    assert res.data["status"] == "input_error"
    assert "shock_set" in res.data["reason"]


def test_pcas_lookback_window_sets_history_length(monkeypatch):
    short = _pcas_run(_pcas(monkeypatch), live="true", lookback_window="90d")
    default = _pcas_run(_pcas(monkeypatch), live="true")
    assert short.data["lookback_days"] == 90
    assert short.data["samples"] < default.data["samples"]


def test_pcas_unimplemented_frequency_is_an_honest_input_error(monkeypatch):
    res = _pcas_run(_pcas(monkeypatch), live="true", frequency="1wk")
    assert res.data["status"] == "input_error"
    assert "frequency" in res.data["reason"]


def test_pcas_seed_frequency_offers_only_implemented_cadence():
    load_seeds()
    spec = REGISTRY.get("PCAS")
    freq = next(i for i in spec.inputs if i.name == "frequency")
    assert list(freq.options or []) == ["1d"]
