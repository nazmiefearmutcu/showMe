"""CHGS#1 / CHGS#5 regressions (wc1-g50).

CHGS#1: ``reference=true`` served a 10-bar template built from a base of 100
with hard-coded RSI 54.2 and SMA values derived from the last template close.
That is invented data and must become an explicit empty state.

CHGS#5: the manifest output contract and field dictionary named top-level keys
(``symbol``, ``last``, ``data_mode``, ``rsi_14``, ``sma_20``, ``sma_50``) that
the live TECH-alias payload does not carry. The contract must describe the real
payload (``summary.last_price``, ``summary.rsi``, ``indicators.sma_*``).

All tests are offline: the yfinance leg is a synthetic fake frame.
"""

from __future__ import annotations

import asyncio
import math
import random
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "backend"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.core.instrument import AssetClass, Instrument  # noqa: E402
from showme.engine.functions.misc._bonus import CHGSFunction  # noqa: E402
from showme.manifest import REGISTRY, load_seeds  # noqa: E402

EQ = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


def _run(coro):
    return asyncio.run(coro)


def _ohlcv(n: int = 120, seed: int = 11) -> pd.DataFrame:
    rng = random.Random(seed)
    closes = [100.0]
    for _ in range(n - 1):
        closes.append(closes[-1] * (1.0 + rng.gauss(0.0, 0.01)))
    rows = []
    for i, close in enumerate(closes):
        prev = closes[i - 1] if i else close
        opened = prev * (1.0 + rng.gauss(0.0, 0.003))
        high = max(opened, close) * (1.0 + abs(rng.gauss(0.0, 0.006)))
        low = min(opened, close) * (1.0 - abs(rng.gauss(0.0, 0.006)))
        rows.append((opened, high, low, close, 1_000_000.0 + rng.random() * 1e5))
    index = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame(rows, index=index, columns=["open", "high", "low", "close", "volume"])


class _FakeYf:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    async def fetch(self, *args: Any, **kwargs: Any) -> pd.DataFrame:
        return self._frame.copy()


# ── CHGS#1 ──────────────────────────────────────────────────────────────


def test_chgs_reference_serves_no_template_figures() -> None:
    result = _run(CHGSFunction(FunctionDeps()).execute(instrument=EQ, reference=True))
    data = result.data
    assert not data.get("rows"), "reference mode must not serve template candles"
    for key in ("last", "rsi_14", "sma_20", "sma_50"):
        assert data.get(key) is None, f"reference mode must not fabricate {key}"
    assert data.get("status") != "reference"
    assert data.get("data_mode") != "modeled"
    assert result.sources == [], result.sources
    assert result.metadata.get("live") is False
    assert result.warnings, "reference mode must say why there are no figures"


def test_chgs_reference_is_explicit_empty_state_even_with_provider() -> None:
    # The template never used the provider, so a wired provider must not
    # change the reference answer into template figures either.
    result = _run(CHGSFunction(FunctionDeps(yfinance=_FakeYf(_ohlcv()))).execute(instrument=EQ, reference=True))
    assert not result.data.get("rows")
    assert result.data.get("rsi_14") is None
    assert result.data.get("status") == "empty", result.data.get("status")
    assert result.data.get("reason") == "reference_mode_has_no_figures"


# ── CHGS#5 ──────────────────────────────────────────────────────────────


def test_chgs_live_payload_meets_manifest_output_contract() -> None:
    load_seeds()
    manifest = REGISTRY.get("CHGS")
    result = _run(CHGSFunction(FunctionDeps(yfinance=_FakeYf(_ohlcv()))).execute(instrument=EQ))
    assert result.data.get("status") == "ok"
    top_level = set(result.data) | {"symbol"}  # symbol rides on FunctionResult.instrument
    missing = [k for k in manifest.output_contract.must_have if k not in top_level]
    assert missing == [], missing


def test_chgs_manifest_field_dict_names_real_payload_paths() -> None:
    load_seeds()
    manifest = REGISTRY.get("CHGS")
    result = _run(CHGSFunction(FunctionDeps(yfinance=_FakeYf(_ohlcv()))).execute(instrument=EQ))
    data = result.data
    for name in manifest.field_dict:
        if name == "symbol":  # symbol rides on FunctionResult.instrument
            continue
        head = name.split(".")[0]
        assert head in data, f"field_dict names {name!r} but payload has no {head!r}"


def test_chgs_live_summary_carries_last_price_and_rsi() -> None:
    frame = _ohlcv()
    result = _run(CHGSFunction(FunctionDeps(yfinance=_FakeYf(frame))).execute(instrument=EQ))
    summary = result.data["summary"]
    assert math.isclose(summary["last_price"], float(frame["close"].iloc[-1]), rel_tol=1e-9)
    assert isinstance(summary["rsi"], float) and 0.0 <= summary["rsi"] <= 100.0
    assert "sma_20" in result.data["indicators"]
    assert "sma_50" in result.data["indicators"]


def test_chgs_without_price_provider_is_explicit_outage() -> None:
    result = _run(CHGSFunction(FunctionDeps()).execute(instrument=EQ))
    assert result.data.get("status") == "provider_unavailable", result.data
    assert not result.data.get("rows")
    assert result.data.get("reason"), "outage must carry a reason"
    assert result.warnings
    assert (result.metadata or {}).get("alias_of") == "TECH"
