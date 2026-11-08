"""BETA honesty pins (P2a-g05): benchmark default, beta_window, methodology
units, and the output fields the manifest promises.

No network: the yfinance adapter is a deterministic in-test stand-in that
serves the same close series for every request shape the handler uses.
"""
from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.beta import BetaFunction
from showme.manifest import REGISTRY, load_seeds


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _series(seed: int, n: int = 600, drift: float = 0.0002, vol: float = 0.01) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 100.0 * np.exp(np.cumsum(rng.normal(drift, vol, n)))


class _RecordingYF:
    """Serves a target series for AAPL and a benchmark series for any other
    symbol, and records every requested symbol."""

    def __init__(self) -> None:
        self.symbols: list[str] = []
        self.target = _series(7)
        self.bench = _series(11)
        self.index = pd.date_range("2024-01-01", periods=len(self.target), freq="D", tz="UTC")

    async def fetch(self, request: Any) -> Any:
        sym = request.instrument.symbol
        self.symbols.append(sym)
        closes = self.target if sym == "AAPL" else self.bench
        return pd.DataFrame(
            {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1.0},
            index=self.index,
        )


def _execute(yf: _RecordingYF, **params: Any) -> Any:
    fn = BetaFunction()
    fn.deps = FunctionDeps(yfinance=yf)
    inst = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    return _run(fn.execute(instrument=inst, **params))


def _simple_returns(prices: np.ndarray) -> np.ndarray:
    return prices[1:] / prices[:-1] - 1.0


# ── BETA#1 — benchmark default and honoured param ───────────────────────────


def test_beta_default_benchmark_matches_manifest_gspc() -> None:
    """Manifest default is ^GSPC; the handler must not silently use SPY."""
    yf = _RecordingYF()
    result = _execute(yf)
    assert result.data["benchmark"] == "^GSPC"
    assert "^GSPC" in yf.symbols
    assert "SPY" not in yf.symbols


def test_beta_benchmark_param_is_used_for_fetch_and_payload() -> None:
    yf = _RecordingYF()
    result = _execute(yf, benchmark="QQQ")
    assert result.data["benchmark"] == "QQQ"
    assert "QQQ" in yf.symbols


# ── BETA#2 — beta_window is honoured ────────────────────────────────────────


def test_beta_window_param_returns_requested_window() -> None:
    yf = _RecordingYF()
    result = _execute(yf, beta_window="126d")
    row = next(r for r in result.data["rows"] if r["window"] == "126d")
    assert row["window_days"] == 126
    tail = _simple_returns(yf.target)[-126:]
    bench_tail = _simple_returns(yf.bench)[-126:]
    expected = np.cov(tail, bench_tail, ddof=1)[0, 1] / np.var(bench_tail, ddof=1)
    assert abs(row["beta"] - expected) < 1e-9
    assert result.data["selected_window"] == "126d"
    assert result.data["assumptions"]["beta_window"] == "126d"


def test_beta_window_matching_standard_window_does_not_duplicate_row() -> None:
    """The manifest default 252d equals the 1Y window; no duplicate row."""
    yf = _RecordingYF()
    result = _execute(yf, beta_window="252d")
    labels = [r["window"] for r in result.data["rows"]]
    assert labels.count("1Y") == 1
    assert "252d" not in labels
    assert result.data["selected_window"] == "1Y"


# ── BETA#4 — promised outputs are present ──────────────────────────────────


def test_beta_rows_carry_alpha_r_squared_and_samples() -> None:
    yf = _RecordingYF()
    result = _execute(yf)
    row = next(r for r in result.data["rows"] if r["window"] == "1Y")
    assert "alpha" in row and "r_squared" in row
    assert abs(row["r_squared"] - row["correlation"] ** 2) < 1e-9
    tail_t = _simple_returns(yf.target)[-252:]
    tail_b = _simple_returns(yf.bench)[-252:]
    beta = np.cov(tail_t, tail_b, ddof=1)[0, 1] / np.var(tail_b, ddof=1)
    alpha = tail_t.mean() - beta * tail_b.mean()
    assert abs(row["alpha"] - alpha) < 1e-9


def test_beta_payload_echoes_assumptions_and_observations() -> None:
    yf = _RecordingYF()
    result = _execute(yf, benchmark="^GSPC", beta_window="252d")
    assumptions = result.data["assumptions"]
    assert assumptions["benchmark"] == "^GSPC"
    assert assumptions["beta_window"] == "252d"
    assert assumptions["return_method"] == "simple"
    assert result.data["n_observations"] == len(yf.target) - 1


def test_beta_manifest_output_contract_names_top_level_payload_keys() -> None:
    """must_have lists payload keys; per-row fields (beta, window) do not count."""
    load_seeds()
    manifest = REGISTRY.get("BETA")
    result = _execute(_RecordingYF())
    top_level = set(result.data) | {"symbol"}  # symbol rides on FunctionResult.instrument
    missing = [k for k in manifest.output_contract.must_have if k not in top_level]
    assert missing == []


def test_beta_manifest_table_columns_exist_in_rows() -> None:
    load_seeds()
    manifest = REGISTRY.get("BETA")
    result = _execute(_RecordingYF())
    row = next(r for r in result.data["rows"] if r["window"] == "1Y")
    missing = [c.key for c in manifest.table_schema.columns if c.key not in row]
    assert missing == []


def test_beta_r_squared_is_decimal_not_percent_in_manifest() -> None:
    """r_squared is correlation squared (0..1); the manifest must not label it percent."""
    load_seeds()
    manifest = REGISTRY.get("BETA")
    columns = {c.key: c for c in manifest.table_schema.columns}
    assert columns["r_squared"].kind != "percent"
    slots = {s.key: s for s in manifest.card_schema.slots}
    assert getattr(slots["r_squared"], "unit", None) != "%"


# ── BETA#3 — methodology text matches the computed return type ─────────────


def test_beta_manifest_methodology_states_simple_returns() -> None:
    load_seeds()
    manifest = REGISTRY.get("BETA")
    text = manifest.methodology.lower()
    assert "log return" not in text
    assert "simple" in text
    formula_notes = " ".join((f.notes or "").lower() for f in manifest.formula_dict.values())
    assert "log return" not in formula_notes


def test_beta_handler_declares_simple_returns() -> None:
    yf = _RecordingYF()
    result = _execute(yf)
    assert "simple" in result.data["return_frequency"].lower()
    assert "log" not in result.data["return_frequency"].lower()
