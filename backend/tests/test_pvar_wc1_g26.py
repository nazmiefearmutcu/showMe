"""PVAR honesty regressions (wc1-g26: PVAR#2..#6).

Network is patched: PortfolioState and the yfinance download are replaced, so
every case is deterministic and offline.
"""
from __future__ import annotations

import asyncio

import numpy as np
import pandas as pd
import pytest

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio import pvar as pvar_mod


class _Pos:
    def __init__(self, symbol: str, quantity: float, avg_cost: float, asset_class=AssetClass.EQUITY) -> None:
        self.instrument = Instrument(symbol=symbol, asset_class=asset_class)
        self.quantity = quantity
        self.avg_cost = avg_cost
        self.account = "main"
        self.currency = "USD"


class _Book:
    def __init__(self, *_args, **_kwargs) -> None:
        self.positions = [
            _Pos("AAPL", 10.0, 100.0),
            _Pos("MSFT", 20.0, 100.0),
            _Pos("GME", 5.0, 20.0),
        ]

    def import_legacy_crypto(self) -> int:
        return 0


def _returns(n: int, seed: float) -> pd.Series:
    idx = pd.date_range(end="2026-09-20", periods=n, freq="D")
    vals = [0.001 * ((i * 7 + int(seed)) % 11 - 5) + 0.0002 * ((i % 3) - 1) for i in range(n)]
    return pd.Series(vals, index=idx)


def _fake_download(symbol, days, timeout):
    return _returns(80, len(symbol)), 105.0


def _run(coro):
    return asyncio.run(coro)


# ── PVAR#2: default confidence must match the manifest default (0.99) ─────


def test_default_confidence_matches_manifest_default(monkeypatch) -> None:
    monkeypatch.setattr(pvar_mod, "PortfolioState", _Book)
    monkeypatch.setattr(pvar_mod, "_download_returns", _fake_download)
    res = _run(pvar_mod.PVARFunction().execute())
    # Red today: the handler silently uses 0.95 while the seed default is 0.99.
    assert res.data["confidence_level"] == pytest.approx(0.99), res.data["confidence_level"]


def test_out_of_range_confidence_is_an_input_error_not_a_silent_default(monkeypatch) -> None:
    monkeypatch.setattr(pvar_mod, "PortfolioState", _Book)
    monkeypatch.setattr(pvar_mod, "_download_returns", _fake_download)
    res = _run(pvar_mod.PVARFunction().execute(confidence=1.5))
    # Red today: status is "ok" with the confidence silently replaced by 0.95.
    assert res.data["status"] == "input_error", res.data["status"]
    assert res.data["var"] is None
    assert "confidence" in str(res.data.get("reason", "")).lower()


# ── PVAR#3: an unsupported method is an input error, not a silent swap ────


def test_monte_carlo_request_is_not_silently_replaced_by_historical(monkeypatch) -> None:
    monkeypatch.setattr(pvar_mod, "PortfolioState", _Book)
    monkeypatch.setattr(pvar_mod, "_download_returns", _fake_download)
    res = _run(pvar_mod.PVARFunction().execute(method="monte_carlo", confidence=0.99))
    # Red today: status is "ok" and method silently reads "historical".
    assert res.data["status"] == "input_error", res.data["status"]
    assert "monte_carlo" in str(res.data.get("reason", ""))
    assert res.data["var"] is None
