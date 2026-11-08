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


def test_default_method_matches_manifest_default(monkeypatch) -> None:
    # pvar_seed defaults method="historical"; the handler must not pick another
    # estimator silently when the caller omits method.
    monkeypatch.setattr(pvar_mod, "PortfolioState", _Book)
    monkeypatch.setattr(pvar_mod, "_download_returns", _fake_download)
    res = _run(pvar_mod.PVARFunction().execute())
    assert res.data["method"] == "historical", res.data["method"]
    assert res.data["cards"]["method"] == "historical"


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


# ── PVAR#4: equity + crypto must share one return calendar ────────────────


class _MixedBook:
    def __init__(self, *_args, **_kwargs) -> None:
        self.positions = [
            _Pos("AAPL", 10.0, 100.0, AssetClass.EQUITY),
            _Pos("BTCUSDT", 0.5, 50_000.0, AssetClass.CRYPTO),
        ]

    def import_legacy_crypto(self) -> int:
        return 0


_MIXED_SHARES = {"AAPL": 10.0, "BTCUSDT": 0.5}
_MIXED_LAST = 105.0


def _mixed_closes() -> tuple[pd.Series, pd.Series]:
    all_days = pd.date_range(end="2026-09-20", periods=80, freq="D")
    weekdays = all_days[all_days.dayofweek < 5]
    rng = np.random.default_rng(7)
    aapl = pd.Series(100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.01, len(weekdays))), index=weekdays)
    btc = pd.Series(50_000.0 * np.cumprod(1.0 + rng.normal(0.0, 0.03, len(all_days))), index=all_days)
    return aapl, btc


def _mixed_download(symbol, days, timeout):
    aapl, btc = _mixed_closes()
    closes = aapl if symbol == "AAPL" else btc
    # Per-symbol daily returns on that symbol's own trading dates, as the
    # download seam reports them.
    return closes.pct_change().dropna(), _MIXED_LAST


def test_mixed_book_uses_common_return_dates_only(monkeypatch) -> None:
    """Equity and crypto returns must share one calendar.

    Every return on a common date must span the same interval for both
    symbols (Fri->Mon for both on a Monday), so the one-day VaR is not built
    from a 3-day equity return next to a 1-day crypto return. The first
    common date only anchors the price path, so it yields no return.
    """
    monkeypatch.setattr(pvar_mod, "PortfolioState", _MixedBook)
    monkeypatch.setattr(pvar_mod, "_download_returns", _mixed_download)
    res = _run(pvar_mod.PVARFunction().execute(method="historical", confidence=0.99))
    assert res.data["status"] == "ok", res.data.get("reason")

    aapl, btc = _mixed_closes()
    px = pd.concat({"AAPL": aapl, "BTCUSDT": btc}, axis=1, sort=True).dropna(how="any")
    exp = px.pct_change().dropna().iloc[1:]
    notional = {s: _MIXED_SHARES[s] * _MIXED_LAST for s in _MIXED_SHARES}
    total = sum(notional.values())
    w = np.array([notional["AAPL"], notional["BTCUSDT"]]) / total
    port = exp[["AAPL", "BTCUSDT"]].values @ w
    expected_var = float(np.quantile(-port, 0.99)) * total

    assert res.data["samples"] == len(exp), res.data["samples"]
    assert res.data["positions_analyzed"] == 2
    assert res.data["var"] == pytest.approx(expected_var, rel=1e-9), (res.data["var"], expected_var)


def test_too_few_common_dates_is_not_reported_as_var(monkeypatch) -> None:
    class _Short(_MixedBook):
        pass

    def _short_download(symbol, days, timeout):
        idx = pd.date_range(end="2026-09-20", periods=6, freq="D")
        return pd.Series(np.linspace(-0.01, 0.01, len(idx)), index=idx), 105.0

    monkeypatch.setattr(pvar_mod, "PortfolioState", _Short)
    monkeypatch.setattr(pvar_mod, "_download_returns", _short_download)
    res = _run(pvar_mod.PVARFunction().execute(method="historical", confidence=0.99))
    assert res.data["status"] == "provider_unavailable", res.data["status"]
    assert res.data["var"] is None
    assert "common return dates" in str(res.data.get("reason", ""))


# ── PVAR#5: legacy VaR fields use the headline sign (positive = loss) ─────


def test_legacy_daily_var_fields_share_the_headline_sign(monkeypatch) -> None:
    monkeypatch.setattr(pvar_mod, "PortfolioState", _Book)
    monkeypatch.setattr(pvar_mod, "_download_returns", _fake_download)
    res = _run(pvar_mod.PVARFunction().execute(method="parametric", confidence=0.99))
    d = res.data
    assert d["status"] == "ok", d.get("reason")
    assert d["var"] > 0
    assert d["parametric_var_dollar"] > 0
    # Red today: the legacy fields are the negated parametric VaR.
    assert d["portfolio_daily_var_dollar"] == pytest.approx(d["parametric_var_dollar"]), d["portfolio_daily_var_dollar"]
    assert d["portfolio_daily_var_pct"] == pytest.approx(d["parametric_var_dollar"] / d["portfolio_total_notional"])


# ── PVAR#6: a cost-basis notional must be disclosed ───────────────────────


def test_missing_live_close_falls_back_to_cost_with_a_warning(monkeypatch) -> None:
    def _no_close_for_msft(symbol, days, timeout):
        series, last = _fake_download(symbol, days, timeout)
        return series, (None if symbol == "MSFT" else last)

    monkeypatch.setattr(pvar_mod, "PortfolioState", _Book)
    monkeypatch.setattr(pvar_mod, "_download_returns", _no_close_for_msft)
    res = _run(pvar_mod.PVARFunction().execute(method="parametric", confidence=0.99))
    d = res.data
    assert d["status"] == "ok", d.get("reason")
    # Red today: weights use MSFT avg_cost silently (no warning, no field).
    assert d.get("cost_basis_fallback_symbols") == ["MSFT"], d.get("cost_basis_fallback_symbols")
    assert any("MSFT" in w and "cost" in w.lower() for w in res.warnings), res.warnings
