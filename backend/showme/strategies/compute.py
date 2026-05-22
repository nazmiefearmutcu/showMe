"""Indicator computation engine for the 15 F indicators.

Operates on pandas OHLCV DataFrames (lowercase columns). NaN-tolerant
for warm-up bars; never raises on insufficient data.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

import numpy as np
import pandas as pd

from showme.strategies.spec import IndicatorRef

LOG = logging.getLogger("showme.strategies.compute")


def _param(params: dict[str, Any], name: str, default: Any) -> Any:
    return params.get(name, default)


def _compute_rsi(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    period = int(_param(params, "period", 14))
    close = df["close"]
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    return rsi.rename("rsi")


def _compute_ema(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    period = int(_param(params, "period", 20))
    return df["close"].ewm(span=period, adjust=False).mean().rename("ema")


def _compute_sma(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    period = int(_param(params, "period", 20))
    return df["close"].rolling(period).mean().rename("sma")


def _compute_macd(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    fast = int(_param(params, "fast_period", 12))
    slow = int(_param(params, "slow_period", 26))
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    return (ema_fast - ema_slow).rename("macd")


def _compute_bollinger_bands(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    period = int(_param(params, "period", 20))
    return df["close"].rolling(period).mean().rename("bbm")


def _compute_stochastic(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    kp = int(_param(params, "k_period", 14))
    smooth = int(_param(params, "smooth", 3))
    hh = df["high"].rolling(kp).max()
    ll = df["low"].rolling(kp).min()
    raw_k = (df["close"] - ll) / (hh - ll).replace(0, np.nan) * 100
    return raw_k.rolling(smooth).mean().rename("stoch_k")


def _compute_atr(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    period = int(_param(params, "period", 14))
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
                   axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean().rename("atr")


def _compute_adx(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    period = int(_param(params, "period", 14))
    high, low, close = df["high"], df["low"], df["close"]
    up = high.diff()
    dn = -low.diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    atr = _compute_atr(df, {"period": period})
    plus_di = 100 * plus_dm.ewm(alpha=1.0 / period, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1.0 / period, adjust=False).mean() / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1.0 / period, adjust=False).mean().rename("adx")


def _compute_cci(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    period = int(_param(params, "period", 20))
    tp = (df["high"] + df["low"] + df["close"]) / 3
    sma = tp.rolling(period).mean()
    mad = (tp - sma).abs().rolling(period).mean()
    return ((tp - sma) / (0.015 * mad.replace(0, np.nan))).rename("cci")


def _compute_obv(df: pd.DataFrame, _params: dict[str, Any]) -> pd.Series:
    direction = np.sign(df["close"].diff()).fillna(0)
    return (df["volume"] * direction).cumsum().rename("obv")


def _compute_williams_r(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    period = int(_param(params, "period", 14))
    hh = df["high"].rolling(period).max()
    ll = df["low"].rolling(period).min()
    return ((hh - df["close"]) / (hh - ll).replace(0, np.nan) * -100).rename("willr")


def _compute_vwap(df: pd.DataFrame, _params: dict[str, Any]) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    return ((tp * df["volume"]).cumsum() / df["volume"].cumsum().replace(0, np.nan)).rename("vwap")


def _compute_ichimoku(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    p = int(_param(params, "kijun_period", 26))
    hh = df["high"].rolling(p).max()
    ll = df["low"].rolling(p).min()
    return ((hh + ll) / 2).rename("kijun")


def _compute_parabolic_sar(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    af_start = float(_param(params, "af_start", 0.02))
    af_step = float(_param(params, "af_step", 0.02))
    af_max = float(_param(params, "af_max", 0.20))

    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    n = len(df)
    sar = np.full(n, np.nan)
    if n < 2:
        return pd.Series(sar, index=df.index, name="psar")

    up = True
    af = af_start
    ep = high[0]
    sar[0] = low[0]

    for i in range(1, n):
        prev_sar = sar[i - 1]
        new_sar = prev_sar + af * (ep - prev_sar)
        if up:
            new_sar = min(new_sar, low[i - 1], low[i - 2] if i >= 2 else low[i - 1])
            if low[i] < new_sar:
                up = False
                new_sar = ep
                ep = low[i]
                af = af_start
            else:
                if high[i] > ep:
                    ep = high[i]
                    af = min(af + af_step, af_max)
        else:
            new_sar = max(new_sar, high[i - 1], high[i - 2] if i >= 2 else high[i - 1])
            if high[i] > new_sar:
                up = True
                new_sar = ep
                ep = high[i]
                af = af_start
            else:
                if low[i] < ep:
                    ep = low[i]
                    af = min(af + af_step, af_max)
        sar[i] = new_sar
    return pd.Series(sar, index=df.index, name="psar")


def _compute_kdj(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    period = int(_param(params, "period", 9))
    m = int(_param(params, "m", 3))
    hh = df["high"].rolling(period).max()
    ll = df["low"].rolling(period).min()
    raw_k = (df["close"] - ll) / (hh - ll).replace(0, np.nan) * 100
    return raw_k.ewm(com=m - 1, adjust=False).mean().rename("kdj_k")


_FUNCTIONS: dict[str, Callable[[pd.DataFrame, dict[str, Any]], pd.Series]] = {
    "rsi": _compute_rsi,
    "macd": _compute_macd,
    "ema": _compute_ema,
    "sma": _compute_sma,
    "bollinger_bands": _compute_bollinger_bands,
    "stochastic": _compute_stochastic,
    "atr": _compute_atr,
    "adx": _compute_adx,
    "cci": _compute_cci,
    "obv": _compute_obv,
    "williams_r": _compute_williams_r,
    "vwap": _compute_vwap,
    "ichimoku": _compute_ichimoku,
    "parabolic_sar": _compute_parabolic_sar,
    "kdj": _compute_kdj,
}


def compute(
    df: pd.DataFrame,
    indicator_refs: list[IndicatorRef],
) -> dict[str, pd.Series]:
    """Compute primary series for each indicator ref under its alias."""
    out: dict[str, pd.Series] = {}
    for ref in indicator_refs:
        fn = _FUNCTIONS.get(ref.id)
        if fn is None:
            LOG.warning("unknown indicator id: %s", ref.id)
            out[ref.alias] = pd.Series([np.nan] * len(df), index=df.index)
            continue
        try:
            out[ref.alias] = fn(df, ref.params or {})
        except Exception as exc:  # noqa: BLE001
            LOG.warning("compute %s/%s failed: %s", ref.id, ref.alias, exc)
            out[ref.alias] = pd.Series([np.nan] * len(df), index=df.index)
    return out
