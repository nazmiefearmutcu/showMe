"""P2A-G07 regression tests: PCAS (#4 multi-factor, #5 string flags)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd

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


def test_pcas_live_prices_false_string_is_an_input_error_not_template_data(monkeypatch):
    fn = _pcas(monkeypatch)
    res = _pcas_run(fn, live="true", live_prices="false")
    # "false" must not be truthy, and the modeled template path no longer exists:
    # the request is refused honestly instead of returning synthetic returns.
    assert res.data["status"] == "input_error"
    assert "live_prices" in res.data["reason"]
    assert "portfolio_state_template_returns" not in res.sources
    assert res.data["components"] == []


def test_pcas_never_emits_template_returns_even_when_live_prices_is_omitted(monkeypatch):
    # live=true with no live_prices is the manifest default route: it must run on
    # real history (or report an outage), never on the synthetic template series.
    res = _pcas_run(_pcas(monkeypatch), live="true", n_factors=2)
    assert res.data["status"] == "provider_unavailable"
    assert res.data.get("data_mode") != "modeled"
    assert "portfolio_state_template_returns" not in res.sources
    assert res.data["samples"] == 0


# ---------------------------------------------------------------- PCAS #4


def test_pcas_multi_factor_returns_components_and_aggregate(monkeypatch):
    res = _pcas_run(_pcas_live(monkeypatch), live="true", n_factors=3, k_sigma=2.0)
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
    res = _pcas_run(_pcas_live(monkeypatch), live="true", n_factors=2,
                    shock_set=[1.0, 2.0])
    sigmas = [c["shock_sigma"] for c in res.data["components"]]
    assert sigmas == [1.0, 2.0]


def test_pcas_shock_set_length_mismatch_is_an_input_error(monkeypatch):
    res = _pcas_run(_pcas(monkeypatch), live="true", n_factors=3, shock_set=[1.0])
    assert res.data["status"] == "input_error"
    assert "shock_set" in res.data["reason"]


def test_pcas_lookback_window_sets_history_length(monkeypatch):
    short = _pcas_run(_pcas_live(monkeypatch), live="true", lookback_window="90d")
    default = _pcas_run(_pcas_live(monkeypatch), live="true")
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


# ---------------------------------------------------------------- PCAS #5 (n_factors is input, not provider)


def test_pcas_n_factors_above_available_components_is_an_input_error(monkeypatch):
    # Four assets support at most four principal components: asking for five
    # is a user input error, not a provider outage.
    res = _pcas_run(_pcas_live(monkeypatch), live="true", n_factors=5)
    assert res.data["status"] == "input_error"
    assert "5 principal components" in res.data["reason"]
    assert "history supports" in res.data["reason"]


# ---------------------------------------------------------------- PCAS #4 on real price history


class _FakeYFinance:
    """Deterministic OHLCV fixture per symbol; stands in for the free yfinance adapter."""

    async def fetch(self, req):
        import numpy as np

        now = datetime.now(timezone.utc)
        n = max(2, (now - req.start).days)
        symbol = req.instrument.symbol
        seed = sum(ord(c) for c in symbol)
        rng = np.random.default_rng(seed)
        vol = 0.008 + (seed % 7) * 0.002
        closes = 100.0 * np.exp(np.cumsum(rng.normal(0.0003, vol, size=n)))
        index = pd.date_range(end=now.date(), periods=n, freq="D")
        return pd.DataFrame({"close": closes}, index=index)


def _pcas_live(monkeypatch, symbols=("AAA", "BBB", "CCC", "DDD")):
    monkeypatch.setattr(pcas_mod, "PortfolioState", lambda *a, **k: _FakeBook(symbols))
    return pcas_mod.PCASFunction(FunctionDeps(yfinance=_FakeYFinance()))


def test_pcas_multi_factor_runs_on_live_price_history(monkeypatch):
    res = _pcas_run(_pcas_live(monkeypatch), live="true", live_prices="true",
                    n_factors=3, k_sigma=2.0)
    d = res.data
    assert d["status"] == "ok"
    assert d["data_mode"] == "delayed_reference"
    assert res.sources == ["yfinance"]
    assert [c["component"] for c in d["components"]] == ["PC1", "PC2", "PC3"]
    assert d["aggregate_impact"] == pytest.approx(
        sum(item["impact_value"] for item in d["shock_impacts"]), rel=1e-9, abs=1e-6)
    assert d["samples"] > 100


def test_pcas_shock_set_on_live_history_applies_each_sigma(monkeypatch):
    res = _pcas_run(_pcas_live(monkeypatch), live="true", live_prices="true",
                    n_factors=2, shock_set=[1.5, 3.0])
    assert [c["shock_sigma"] for c in res.data["components"]] == [1.5, 3.0]
    assert res.sources == ["yfinance"]


def test_pcas_lookback_window_on_live_history_sets_real_sample_count(monkeypatch):
    short = _pcas_run(_pcas_live(monkeypatch), live="true", live_prices="true",
                      lookback_window="90d")
    long = _pcas_run(_pcas_live(monkeypatch), live="true", live_prices="true",
                     lookback_window="1Y")
    assert short.data["lookback_days"] == 90 and long.data["lookback_days"] == 365
    assert short.data["samples"] < long.data["samples"]


def test_pcas_live_prices_without_a_provider_is_an_honest_outage_not_modeled(monkeypatch):
    # No yfinance adapter: the live request must not quietly fall back to the
    # modeled template returns.
    monkeypatch.setattr(pcas_mod, "PortfolioState", lambda *a, **k: _FakeBook(("AAA", "BBB", "CCC", "DDD")))
    fn = pcas_mod.PCASFunction(FunctionDeps())
    res = _pcas_run(fn, live="true", live_prices="true", n_factors=2)
    assert res.data["status"] == "provider_unavailable"
    assert res.data.get("data_mode") != "modeled"
    assert "portfolio_state_template_returns" not in res.sources


class _PartialYFinance(_FakeYFinance):
    """Serves history for every symbol except BBB, which the provider cannot price."""

    async def fetch(self, req):
        if req.instrument.symbol == "BBB":
            raise RuntimeError("no history for BBB")
        return await super().fetch(req)


def test_pcas_partial_live_history_is_not_priced_at_avg_cost(monkeypatch):
    # A symbol without live history must not be valued at its cost basis and
    # silently folded into the book: the stress is refused and the gap is named.
    monkeypatch.setattr(pcas_mod, "PortfolioState", lambda *a, **k: _FakeBook(("AAA", "BBB", "CCC", "DDD")))
    fn = pcas_mod.PCASFunction(FunctionDeps(yfinance=_PartialYFinance()))
    res = _pcas_run(fn, live="true", live_prices="true", n_factors=2)
    assert res.data["status"] == "provider_unavailable"
    assert "BBB" in res.data["reason"]
    assert res.data["components"] == []
    assert res.data["aggregate_impact"] is None


# ---------------------------------------------------------------- PCAS seed contract


def test_pcas_seed_declares_no_unread_provider_mode_input():
    # The handler never reads provider_mode; live history is the only data path.
    load_seeds()
    spec = REGISTRY.get("PCAS")
    assert all(i.name != "provider_mode" for i in spec.inputs)
    assert "provider_mode" not in (spec.defaults or {})


def test_pcas_seed_does_not_pick_n_factors_for_the_user():
    # n_factors is a MODEL_ASSUMPTION the user owns: no injected default that
    # would silently turn a single-PC pc_index request into a 3-factor run.
    load_seeds()
    spec = REGISTRY.get("PCAS")
    assert "n_factors" not in (spec.defaults or {})


def test_pcas_pc_index_alone_runs_the_single_component_stress(monkeypatch):
    res = _pcas_run(_pcas_live(monkeypatch), live="true", live_prices="true",
                    pc_index=1, k_sigma=2.0)
    d = res.data
    assert d["status"] == "ok"
    assert d["multi_factor"] is False
    assert d["n_factors"] == 1
    assert [c["component"] for c in d["components"]] == ["PC2"]


# ---------------------------------------------------------------- PCAS#4 follow-up: provenance stamp


class _DatedYFinance:
    """Deterministic OHLCV history that ends on a fixed past bar date."""

    LAST_BAR = "2026-09-14"

    async def fetch(self, req):
        import numpy as np

        n = 200
        symbol = req.instrument.symbol
        seed = sum(ord(c) for c in symbol)
        rng = np.random.default_rng(seed)
        vol = 0.008 + (seed % 7) * 0.002
        closes = 100.0 * np.exp(np.cumsum(rng.normal(0.0003, vol, size=n)))
        index = pd.date_range(end=self.LAST_BAR, periods=n, freq="D")
        return pd.DataFrame({"close": closes}, index=index)


def test_pcas_as_of_is_the_last_price_bar_not_the_request_clock(monkeypatch):
    # PCAS#4 follow-up: as_of labels the vintage of the returns used. The fetch
    # time belongs in fetched_at; as_of must be the last bar date.
    monkeypatch.setattr(pcas_mod, "PortfolioState", lambda *a, **k: _FakeBook(("AAA", "BBB", "CCC", "DDD")))
    fn = pcas_mod.PCASFunction(FunctionDeps(yfinance=_DatedYFinance()))
    res = _pcas_run(fn, live="true", live_prices="true", n_factors=2)
    assert res.data["status"] == "ok", res.data.get("reason")
    assert res.data["as_of"] == _DatedYFinance.LAST_BAR, res.data["as_of"]
    assert res.data.get("fetched_at"), "retrieval time must be labelled fetched_at"


# ---------------------------------------------------------------- PCAS#4 reviewer follow-up: pc_index honoured in multi-factor


def test_pcas_multi_factor_window_starts_at_pc_index(monkeypatch):
    # The multi-factor run shocks N consecutive components starting at pc_index.
    # Every reported field must refer to that same window, not PC1..PCn.
    res = _pcas_run(_pcas_live(monkeypatch), live="true", live_prices="true",
                    n_factors=2, pc_index=1, k_sigma=2.0)
    d = res.data
    assert d["status"] == "ok", d.get("reason")
    assert d["pc_index"] == 1
    assert [c["pc_index"] for c in d["components"]] == [1, 2]
    assert [c["component"] for c in d["components"]] == ["PC2", "PC3"]
    assert [s["pc_index"] for s in d["shock_impacts"]] == [1, 2]
    assert all(row["pc_index"] == 1 for row in d["loadings"])
    assert d["top_loadings"] == d["components"][0]["top_loadings"]


def test_pcas_multi_factor_window_past_available_components_is_an_input_error(monkeypatch):
    # Four assets support four components: a window at PC4 with two factors needs PC5.
    res = _pcas_run(_pcas_live(monkeypatch), live="true", live_prices="true",
                    n_factors=2, pc_index=3)
    assert res.data["status"] == "input_error"
    assert "5 principal components" in res.data["reason"]


def test_pcas_negative_pc_index_is_an_input_error_not_the_last_component(monkeypatch):
    res = _pcas_run(_pcas_live(monkeypatch), live="true", live_prices="true",
                    pc_index=-1, k_sigma=2.0)
    assert res.data["status"] == "input_error"
    assert "pc_index" in res.data["reason"]
