"""CORR regression tests for the wc1-g01 correctness group.

Covers CORR#2 (annualization), CORR#5 (no Pearson fallback), CORR#6 (provenance),
CORR#7 (declared inputs honoured, min_overlap enforced), CORR#8 (undefined vol is
null), CORR-R1 (no synthetic reference suggestion on outage) and CORR-R2 (every
symbol is measured on one common calendar). All network calls are faked.
"""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio import corr as corr_mod
from showme.engine.functions.portfolio.corr import CORRFunction

END = "2026-09-18"  # a Friday


def _brute_tau_b(x: Any, y: Any) -> float:
    """Reference Kendall tau-b over all pairs (no scipy needed)."""
    import math

    s = tx = ty = 0.0
    for i in range(len(x)):
        for j in range(i + 1, len(x)):
            a = float(np.sign(x[i] - x[j]))
            b = float(np.sign(y[i] - y[j]))
            s += a * b
            tx += a * a
            ty += b * b
    return s / math.sqrt(tx * ty)


def _run(coro):
    return asyncio.run(coro)


class _CalendarYf:
    """Weekday-only series for equities/FX, every-day series for crypto."""

    _FREQ = {"AAPL": "B", "EURUSD": "B", "BTCUSDT": "D", "BTC-USD": "D"}

    def __init__(self, periods: dict[str, int] | None = None) -> None:
        self._periods = periods or {}

    async def fetch(self, request: Any) -> pd.DataFrame:
        sym = request.instrument.symbol
        freq = self._FREQ.get(sym, "B")
        periods = self._periods.get(sym, 160)
        idx = pd.date_range(end=END, periods=periods, freq=freq)
        seed = sum(ord(ch) for ch in sym)
        rng = np.random.default_rng(seed)
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, len(idx))))
        return pd.DataFrame({"close": close}, index=idx)


class _FailYf:
    async def fetch(self, request: Any) -> pd.DataFrame:
        raise RuntimeError("provider down")


class _CcxtFake:
    """Crypto adapter stand-in; the BTC series comes from ccxt_failover, not yfinance."""

    async def fetch(self, request: Any) -> pd.DataFrame:
        idx = pd.date_range(end=END, periods=160, freq="D")
        rng = np.random.default_rng(7)
        close = 60000.0 * np.exp(np.cumsum(rng.normal(0.0, 0.02, len(idx))))
        return pd.DataFrame({"close": close}, index=idx)


# ── CORR#2: one annualization per symbol, shared by every payload field ──


def test_corr2_annualized_vol_matches_return_summary_on_each_symbols_own_calendar() -> None:
    fn = CORRFunction(FunctionDeps(yfinance=_CalendarYf()))
    res = _run(fn.execute(symbols=["AAPL", "BTCUSDT"], live_correlation=True, days=120))

    summary = {row["symbol"]: row for row in res.data["impactor"]["return_series_summary"]}
    for symbol in ("AAPL", "BTCUSDT"):
        vol = res.data["annualized_vol"][symbol]
        assert vol is not None
        assert abs(vol - summary[symbol]["annualized_volatility"]) < 1e-4, (
            symbol,
            vol,
            summary[symbol]["annualized_volatility"],
        )
    row_vol = {row["symbol"]: row["annualized_vol"] for row in res.data["rows"]}
    assert row_vol == {s: res.data["annualized_vol"][s] for s in ("AAPL", "BTCUSDT")}


# ── CORR#8: an undefined volatility is null, never 0.0 ───────────────────


def test_corr8_undefined_volatility_is_null_in_rows() -> None:
    idx = pd.date_range("2026-01-01", periods=12, freq="B")
    frame = pd.DataFrame(
        {
            "FLAT": [np.nan] * 12,
            "ALIVE": np.linspace(-0.01, 0.01, 12) * (1 + np.arange(12) % 3),
        },
        index=idx,
    )
    payload = corr_mod._correlation_payload(
        symbols=["FLAT", "ALIVE"],
        days=30,
        price_series=[],
        frame=frame,
        return_method="log",
        frequency="daily",
        missing_policy="pairwise",
        live=False,
        sources=["computed_return_model"],
        coverage_status={},
    )
    rows = {row["symbol"]: row for row in payload["rows"]}
    assert payload["annualized_vol"]["FLAT"] is None
    assert rows["FLAT"]["annualized_vol"] is None
    assert rows["ALIVE"]["annualized_vol"] is not None


# ── CORR#5: a missing downside/Spearman cell is null, not the Pearson value ──


def test_corr5_missing_downside_cell_does_not_fall_back_to_pearson() -> None:
    surface = corr_mod._matrix_surface(
        {"A": {"B": 0.5}, "B": {"A": 0.5}},
        {"A": {"B": 0.3}, "B": {"A": 0.3}},
        {},
    )
    row = next(item for item in surface if item["symbol"] == "A" and item["peer"] == "B")
    assert row["pearson"] == 0.5
    assert row["spearman"] == 0.3
    assert row["downside"] is None


# ── CORR#6: sources name the providers that actually served the closes ──


def test_corr6_sources_name_the_real_per_symbol_providers() -> None:
    deps = FunctionDeps(yfinance=_CalendarYf())
    deps.ccxt_failover = _CcxtFake()
    fn = CORRFunction(deps)
    res = _run(fn.execute(symbols=["AAPL", "BTCUSDT"], live_correlation=True, days=120))

    coverage = {row["symbol"]: row for row in res.data["impactor"]["market_coverage"]}
    assert coverage["BTCUSDT"]["source"] == "ccxt_failover"
    assert coverage["AAPL"]["source"] == "yfinance"
    assert "ccxt_failover" in res.sources
    assert "yfinance" in res.sources
    assert "computed_return_model" not in res.sources


# ── CORR#7: declared inputs are read; min_overlap rejects thin pairs ──


def test_corr7_min_overlap_nulls_thin_pair_and_warns() -> None:
    class _ThinYf(_CalendarYf):
        async def fetch(self, request: Any) -> pd.DataFrame:
            sym = request.instrument.symbol
            if sym in ("EURUSD", "EURUSD=X"):  # FX is requested as its provider symbol
                # Only 12 sessions: fewer than the 30 overlapping returns required.
                idx = pd.date_range(end=END, periods=12, freq="B")
                return pd.DataFrame({"close": np.linspace(1.0, 1.2, 12)}, index=idx)
            return await super().fetch(request)

    fn = CORRFunction(FunctionDeps(yfinance=_ThinYf()))
    res = _run(fn.execute(symbols=["AAPL", "EURUSD"], live_correlation=True, days=120))

    assert res.data["pearson"]["AAPL"]["EURUSD"] is None
    assert res.data["pearson"]["EURUSD"]["AAPL"] is None
    rejected = res.data["rejected_pairs"]
    assert rejected and {rejected[0]["left"], rejected[0]["right"]} == {"AAPL", "EURUSD"}
    assert any("overlapping" in w for w in res.warnings)


def test_corr7_declared_universe_window_and_return_type_are_read() -> None:
    fn = CORRFunction(FunctionDeps(yfinance=_CalendarYf()))
    res = _run(
        fn.execute(
            universe=["AAPL", "EURUSD"],
            window="90d",
            return_type="simple",
            live_correlation=True,
        )
    )
    assert res.data["symbols"] == ["AAPL", "EURUSD"]
    assert res.metadata["days"] == 90
    assert res.metadata["return_method"] == "simple"


def test_corr7_unsupported_hourly_frequency_is_an_explicit_input_error() -> None:
    fn = CORRFunction(FunctionDeps())
    res = _run(fn.execute(symbols=["SPY", "QQQ"], frequency="1h"))
    assert res.data["status"] == "input_error"
    assert "rows" not in res.data or res.data.get("rows") in (None, [])


# ── CORR-R1: a live outage never suggests the synthetic reference matrix ──


class _OutageYf:
    async def fetch(self, request: Any) -> pd.DataFrame:
        raise RuntimeError("provider down")


def test_corr_r1_outage_next_actions_do_not_point_to_reference_matrix() -> None:
    fn = CORRFunction(FunctionDeps(yfinance=_OutageYf()))
    res = _run(fn.execute(symbols=["SPY", "QQQ"], live_correlation=True, days=90))
    assert res.data["status"] == "provider_unavailable"
    text = " ".join(res.data["next_actions"]).lower()
    assert "reference" not in text
    assert "live_correlation=false" not in text


# ── CORR-R2: every symbol is measured on the same calendar ──


def test_corr_r2_weekend_crypto_returns_are_not_measured_over_longer_horizons() -> None:
    fn = CORRFunction(FunctionDeps(yfinance=_CalendarYf()))
    res = _run(fn.execute(symbols=["AAPL", "BTCUSDT"], live_correlation=True, days=120))

    summary = {row["symbol"]: row for row in res.data["impactor"]["return_series_summary"]}
    # Both symbols share one set of return dates, so the counts match.
    assert summary["BTCUSDT"]["observations"] == summary["AAPL"]["observations"]
    assert summary["BTCUSDT"]["first_return_date"] == summary["AAPL"]["first_return_date"]
    assert summary["BTCUSDT"]["last_return_date"] == summary["AAPL"]["last_return_date"]


def test_corr7_seed_provider_chain_names_handler_adapters() -> None:
    from showme.manifest.seeds.corr_seed import corr as corr_manifest

    chain = corr_manifest.provider_chain
    names = {chain.primary, *chain.fallbacks}
    assert "binance" not in names
    assert "cached_snapshot" not in names
    assert names <= {"ccxt_failover", "coingecko", "yfinance"}
    assert chain.primary == "yfinance"


# ── CORR#2 residual: the selected pair carries each symbol's own realized vol ──


def test_corr2_selected_pair_reports_per_symbol_annualized_vol_not_nominal_factor() -> None:
    fn = CORRFunction(FunctionDeps(yfinance=_CalendarYf()))
    res = _run(fn.execute(symbols=["AAPL", "BTCUSDT"], live_correlation=True, days=120))

    sel = res.data["impactor"]["selected_pair"]
    assert sel is not None
    assert "annualization_factor" not in sel
    for side in ("left", "right"):
        symbol = sel[side]
        assert abs(sel[f"{side}_annualized_volatility"] - res.data["annualized_vol"][symbol]) < 1e-4


# ── CORR#7 residual: declared method / as_of / provider_mode are honoured or rejected ──


def test_corr7_pair_stats_uses_the_requested_correlation_kernel() -> None:
    rng = np.random.default_rng(3)
    idx = pd.date_range("2026-01-01", periods=60, freq="B")
    x = rng.normal(size=60)
    y = np.exp(x) + rng.normal(scale=0.01, size=60)  # monotone but non-linear
    frame = pd.DataFrame({"X": x, "Y": y}, index=idx)

    kendall = corr_mod._pair_stats(frame, "X", "Y", method="kendall")["correlation"]
    pearson = corr_mod._pair_stats(frame, "X", "Y")["correlation"]
    assert abs(kendall - _brute_tau_b(x, y)) < 1e-9
    assert abs(kendall - pearson) > 1e-6


def test_corr7_kendall_method_is_reported_and_drives_the_headline_matrix() -> None:
    fn = CORRFunction(FunctionDeps(yfinance=_CalendarYf()))
    res = _run(fn.execute(symbols=["AAPL", "BTCUSDT"], live_correlation=True, days=120, method="kendall"))

    assert res.data.get("status") != "input_error"
    assert res.data["correlation_method"] == "kendall"
    assert res.data["impactor"]["options"]["correlation_method"] == "kendall"
    assert any("kendall" in w.lower() for w in res.warnings)


def test_corr7_unknown_method_is_an_explicit_input_error() -> None:
    res = _run(CORRFunction(FunctionDeps()).execute(symbols=["SPY", "QQQ"], method="ward"))
    assert res.data["status"] == "input_error"
    assert "method" in res.data["reason"]


def test_corr7_as_of_before_today_is_an_explicit_input_error() -> None:
    res = _run(CORRFunction(FunctionDeps()).execute(symbols=["SPY", "QQQ"], as_of="2020-01-03"))
    assert res.data["status"] == "input_error"
    assert "as_of" in res.data["reason"]


def test_corr7_unparsable_as_of_is_an_explicit_input_error() -> None:
    res = _run(CORRFunction(FunctionDeps()).execute(symbols=["SPY", "QQQ"], as_of="last tuesday"))
    assert res.data["status"] == "input_error"


def test_corr7_as_of_today_is_accepted() -> None:
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date().isoformat()
    res = _run(CORRFunction(FunctionDeps()).execute(symbols=["SPY", "QQQ"], as_of=today))
    assert res.data.get("status") != "input_error"


def test_corr7_cached_snapshot_mode_is_an_explicit_input_error() -> None:
    from showme.manifest.enums import DataMode

    res = _run(
        CORRFunction(FunctionDeps()).execute(
            symbols=["SPY", "QQQ"], provider_mode=DataMode.CACHED_SNAPSHOT.value
        )
    )
    assert res.data["status"] == "input_error"
    assert "provider_mode" in res.data["reason"]


def test_corr7_seed_options_do_not_advertise_unsupported_values() -> None:
    from showme.manifest.enums import DataMode
    from showme.manifest.seeds.corr_seed import corr as corr_manifest

    specs = {spec.name: spec for spec in corr_manifest.inputs}
    assert "1h" not in specs["frequency"].options
    assert DataMode.CACHED_SNAPSHOT.value not in specs["provider_mode"].options


# ── CORR outage honesty: an empty provider_unavailable envelope is never live ──


def test_corr_outage_envelope_metadata_is_not_live() -> None:
    res = _run(CORRFunction(FunctionDeps(yfinance=_OutageYf())).execute(
        symbols=["SPY", "QQQ"], live_correlation=True, days=90
    ))
    assert res.data["status"] == "provider_unavailable"
    assert res.metadata["live"] is False


# ── CORR-R2 residual: the methodology states the shared calendar ──


def test_corr_r2_methodology_states_the_shared_return_calendar() -> None:
    fn = CORRFunction(FunctionDeps(yfinance=_CalendarYf()))
    res = _run(fn.execute(symbols=["AAPL", "BTCUSDT"], live_correlation=True, days=120))
    assert "shared return calendar" in res.data["methodology"]


# ── CORR#7 review: a future as_of, an unknown provider_mode and an undeclared mode are never silent ──


def test_corr7_as_of_after_today_is_an_explicit_input_error() -> None:
    from datetime import datetime, timedelta, timezone

    future = (datetime.now(timezone.utc).date() + timedelta(days=3)).isoformat()
    res = _run(CORRFunction(FunctionDeps()).execute(symbols=["SPY", "QQQ"], as_of=future))
    assert res.data["status"] == "input_error"
    assert "future" in res.data["reason"]


def test_corr7_unknown_provider_mode_is_an_explicit_input_error() -> None:
    res = _run(CORRFunction(FunctionDeps()).execute(symbols=["SPY", "QQQ"], provider_mode="turbo"))
    assert res.data["status"] == "input_error"
    assert "provider_mode" in res.data["reason"]


def test_corr7_requested_provider_mode_is_reported_as_not_honoured() -> None:
    from showme.manifest.enums import DataMode

    fn = CORRFunction(FunctionDeps(yfinance=_CalendarYf()))
    res = _run(fn.execute(
        symbols=["AAPL", "BTCUSDT"], live_correlation=True, days=120,
        provider_mode=DataMode.LIVE_EXCHANGE.value,
    ))
    assert res.metadata["provider_mode_requested"] == "live_exchange"
    assert res.metadata["provider_mode_honoured"] is False
    assert any("live_exchange" in w for w in res.warnings)


def test_corr7_absent_provider_mode_is_reported_as_none() -> None:
    fn = CORRFunction(FunctionDeps(yfinance=_CalendarYf()))
    res = _run(fn.execute(symbols=["AAPL", "BTCUSDT"], live_correlation=True, days=120))
    assert res.metadata["provider_mode_requested"] is None
    assert res.metadata["provider_mode_honoured"] is None


def test_corr7_seed_methodology_states_the_per_market_provider_order() -> None:
    from showme.manifest.seeds.corr_seed import corr as corr_manifest

    text = corr_manifest.methodology
    assert "Crypto" in text
    assert "ccxt_failover, coingecko, then yfinance" in text
    assert "every other market uses yfinance" in text
