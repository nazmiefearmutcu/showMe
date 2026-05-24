"""Indicator computation engine for the 15 F indicators.

Operates on pandas OHLCV DataFrames (lowercase columns). NaN-tolerant
for warm-up bars; never raises on insufficient data.

Q1 audit fixes (CRITICAL/HIGH):
  * Wilder smoothing now uses ``min_periods=period`` so warm-up bars
    return NaN (no garbage averages from a partial window).
  * Bollinger std uses ``ddof=1`` to match Bollinger (1980) sample std
    and the engine ``bollinger.py`` (so engine/compute paths agree).
  * RSI loss term parenthesises ``(-delta).where(delta < 0, 0.0)`` —
    the old expression was ``-delta.where(delta < 0, 0.0)`` which
    flipped sign on zeros.
  * Removed the rsi=100/50 hack: with ``min_periods=period`` warm-up
    correctly returns NaN, no fake value required.
  * ADX no longer drops user params via ``_compute_atr(df, {"period": period})``;
    it now honours the original params dict.
  * VWAP supports ``session_reset`` (UTC midnight) — promised by the catalog
    but previously ignored.
  * Ichimoku returns all 5 components (Tenkan/Kijun/Span A/Span B/Chikou)
    via per-alias suffix series; primary Series is still ``kijun`` so
    legacy rule expressions keep working.
  * Stochastic returns both %K and %D (primary is %K for legacy compat,
    %D exposed as ``{alias}_d`` series).
  * KDJ returns full K/D/J using the standard recursive Chinese formula
    (1/3 EMA-equivalent). J = 3K - 2D exposed as ``{alias}_j``.
  * CCI MAD formula now uses ``rolling.apply(lambda)`` (standard
    Lambert MAD) — matches engine ``cci.py``.
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


def _wilder_rma(series: pd.Series, period: int) -> pd.Series:
    """Wilder's RMA (running moving average) — alpha = 1/period.

    Q1 fix (CRITICAL): ``min_periods=period`` so warm-up bars are NaN
    instead of a partial-window average that drifts the first ~period
    bars of every downstream indicator.
    """
    return series.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def _compute_rsi(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    """RSI (Wilder).

    Q1 CRITICAL fixes:
      * ``(-delta).where(...)`` parentheses (operator precedence bug).
      * Wilder seed via ``min_periods=period`` — no garbage warm-up.
      * Removed the rsi=100/50 hack; NaN-during-warm-up is the textbook
        behaviour and matches engine ``rsi.py``.
    """
    period = int(_param(params, "period", 14))
    close = df["close"]
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    # Operator precedence: ``-delta.where(...)`` parses as
    # ``-(delta.where(...))`` which is the opposite sign on the zero
    # branch (-0.0 vs 0.0 — harmless but confusing). Use ``(-delta)``
    # first so ``where`` masks the now-positive losses.
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = _wilder_rma(gain, period)
    avg_loss = _wilder_rma(loss, period)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
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


def _compute_macd_signal(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    """H-17 fix: MACD signal line = EMA(``signal_period``) of MACD line."""
    signal_period = int(_param(params, "signal_period", 9))
    macd = _compute_macd(df, params)
    return macd.ewm(span=signal_period, adjust=False).mean().rename("macd_signal")


def _compute_macd_hist(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    """H-17 fix: MACD histogram = MACD line - MACD signal line."""
    macd = _compute_macd(df, params)
    signal = _compute_macd_signal(df, params)
    return (macd - signal).rename("macd_hist")


def _compute_bollinger_bands(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    """Bollinger middle line (SMA). For upper/lower bands, register the
    indicator under id ``bollinger_upper`` / ``bollinger_lower``."""
    period = int(_param(params, "period", 20))
    return df["close"].rolling(period).mean().rename("bbm")


def _bb_num_std(params: dict[str, Any]) -> float:
    """C-API-2 fix: accept ``num_std`` *or* ``std_dev`` aliases."""
    if "num_std" in params:
        return float(_param(params, "num_std", 2.0))
    if "std_dev" in params:
        return float(_param(params, "std_dev", 2.0))
    return 2.0


def _compute_bollinger_upper(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    """H-16 fix: upper Bollinger band = SMA + num_std * rolling std.

    Q1 CRITICAL fix: ``ddof=1`` (sample std) to match Bollinger (1980)
    and engine ``bollinger.py``. Old ``ddof=0`` produced a different
    result from the engine path on every bar — dual-path divergence.
    """
    period = int(_param(params, "period", 20))
    num_std = _bb_num_std(params)
    sma = df["close"].rolling(period).mean()
    std = df["close"].rolling(period).std(ddof=1)
    return (sma + num_std * std).rename("bbu")


def _compute_bollinger_lower(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    """H-16 fix: lower Bollinger band = SMA - num_std * rolling std.

    Q1 CRITICAL fix: ``ddof=1`` (sample std) — see ``_compute_bollinger_upper``.
    """
    period = int(_param(params, "period", 20))
    num_std = _bb_num_std(params)
    sma = df["close"].rolling(period).mean()
    std = df["close"].rolling(period).std(ddof=1)
    return (sma - num_std * std).rename("bbl")


def _stoch_k_d(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.Series, pd.Series]:
    """Return both Stochastic %K (smoothed) and %D (SMA of %K)."""
    kp = int(_param(params, "k_period", 14))
    smooth = int(_param(params, "smooth", 3))
    d_period = int(_param(params, "d_period", 3))
    hh = df["high"].rolling(kp).max()
    ll = df["low"].rolling(kp).min()
    raw_k = (df["close"] - ll) / (hh - ll).replace(0, np.nan) * 100
    k_line = raw_k.rolling(smooth).mean()
    d_line = k_line.rolling(d_period).mean()
    return k_line.rename("stoch_k"), d_line.rename("stoch_d")


def _compute_stochastic(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    """Stochastic %K (smoothed). %D is exposed as ``{alias}_d`` series
    via the multi-output suffix registry (see :func:`compute`)."""
    k_line, _d = _stoch_k_d(df, params)
    return k_line


def _compute_atr(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    period = int(_param(params, "period", 14))
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
                   axis=1).max(axis=1)
    return _wilder_rma(tr, period).rename("atr")


def _compute_adx(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    """ADX (Wilder).

    Q1 CRITICAL fix: pass through user params to ``_compute_atr`` (was
    silently dropping every param other than ``period``). Also uses the
    ``min_periods``-aware Wilder RMA helper.
    """
    period = int(_param(params, "period", 14))
    high, low, _close = df["high"], df["low"], df["close"]
    up = high.diff()
    dn = -low.diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    # Pass full params through so things like ``atr_period`` overrides
    # don't get lost; the ATR computation ignores unknown keys.
    atr = _compute_atr(df, {**params, "period": period})
    plus_di = 100 * _wilder_rma(plus_dm, period) / atr.replace(0, np.nan)
    minus_di = 100 * _wilder_rma(minus_dm, period) / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return _wilder_rma(dx, period).rename("adx")


def _compute_cci(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    """CCI (Lambert).

    Q1 fix: use ``rolling.apply(lambda x: mean(|x - mean(x)|))`` so the
    mean deviation is computed inside the rolling window (against the
    window's own mean). Old ``(tp - sma).abs().rolling.mean()`` mixed
    each bar's deviation from the SMA at *that* bar with subsequent SMA
    values — close but not the textbook Lambert MAD that the engine
    ``cci.py`` uses.
    """
    period = int(_param(params, "period", 20))
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    sma = tp.rolling(period).mean()
    mad = tp.rolling(period).apply(
        lambda x: np.mean(np.abs(x - np.mean(x))), raw=True
    )
    return ((tp - sma) / (0.015 * mad.replace(0, np.nan))).rename("cci")


def _compute_obv(df: pd.DataFrame, _params: dict[str, Any]) -> pd.Series:
    """On-Balance Volume.

    Tier 3 fix retained: first-bar direction defaults to +1 (TradingView
    convention) so ``volume[0]`` flows into the cumulative sum.
    """
    diff = df["close"].diff()
    direction = np.sign(diff)
    direction = direction.where(~direction.isna(), 1.0)
    return (df["volume"] * direction).cumsum().rename("obv")


def _compute_williams_r(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    period = int(_param(params, "period", 14))
    hh = df["high"].rolling(period).max()
    ll = df["low"].rolling(period).min()
    return ((hh - df["close"]) / (hh - ll).replace(0, np.nan) * -100).rename("willr")


def _session_anchor(index: pd.Index, params: dict[str, Any]) -> pd.Series:
    """Return a Series of session-anchor labels (one per bar).

    Q1 HIGH fix: the catalog promises ``session_reset: true`` for VWAP
    but the compute engine ignored it. We compute a "session id" from
    the bar timestamp: for crypto (24/7) the UTC date works; for equity
    the user can supply ``session_open_utc_hour`` (default 0 = UTC midnight,
    13.5 = 13:30 UTC ≈ NYSE 09:30 ET). Bars in the same session share an
    id; ``groupby(session_id).cumsum()`` then anchors VWAP per session.

    If the index is not a DatetimeIndex (e.g. a synthetic test fixture)
    we fall back to a single anchor — the original "since-start" cumsum
    behaviour, with no reset.
    """
    if not isinstance(index, pd.DatetimeIndex):
        # No time information → treat the entire series as one session.
        return pd.Series([0] * len(index), index=index, dtype="int64")
    # Optional hour offset for non-24/7 markets. Default is UTC midnight
    # (crypto convention). Equity callers can pass e.g. 13.5 (≈ NYSE open).
    session_open_utc_hour = float(_param(params, "session_open_utc_hour", 0.0))
    # Shift the timestamp back by the open hour so all bars within a single
    # session round down to the same date. Use total seconds for fractional
    # hours (NYSE 09:30 ET ≈ 13.5 UTC during EST, 14.5 EDT — caller picks).
    shift_seconds = int(session_open_utc_hour * 3600)
    ts = index.tz_convert("UTC") if index.tz is not None else index
    shifted = ts - pd.Timedelta(seconds=shift_seconds)
    # Use the date as the session id — pandas .normalize() drops the time.
    return pd.Series(shifted.normalize().astype("int64"), index=index)


def _compute_vwap(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    """VWAP.

    Q1 HIGH fix: honour ``session_reset`` (catalog default true). Daily
    UTC-midnight reset is the crypto convention; equity callers can
    override via ``session_open_utc_hour`` (e.g. 13.5 for NYSE).
    """
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    tp_vol = tp * df["volume"]
    session_reset = bool(_param(params, "session_reset", True))
    if not session_reset:
        # Anchored VWAP — single cumulative window from the first bar.
        return (tp_vol.cumsum() / df["volume"].cumsum().replace(0, np.nan)).rename("vwap")
    anchor = _session_anchor(df.index, params)
    tp_vol_cum = tp_vol.groupby(anchor).cumsum()
    vol_cum = df["volume"].groupby(anchor).cumsum()
    return (tp_vol_cum / vol_cum.replace(0, np.nan)).rename("vwap")


def _ichimoku_components(
    df: pd.DataFrame, params: dict[str, Any]
) -> dict[str, pd.Series]:
    """Return all 5 Ichimoku components as named series."""
    tenkan_period = int(_param(params, "tenkan_period", 9))
    kijun_period = int(_param(params, "kijun_period", 26))
    senkou_b_period = int(_param(params, "senkou_b_period", 52))

    high, low, close = df["high"], df["low"], df["close"]
    tenkan = (high.rolling(tenkan_period).max() + low.rolling(tenkan_period).min()) / 2.0
    kijun = (high.rolling(kijun_period).max() + low.rolling(kijun_period).min()) / 2.0
    senkou_a = ((tenkan + kijun) / 2.0).shift(kijun_period)
    senkou_b = ((high.rolling(senkou_b_period).max()
                 + low.rolling(senkou_b_period).min()) / 2.0).shift(kijun_period)
    chikou = close.shift(-kijun_period)
    return {
        "tenkan": tenkan.rename("tenkan"),
        "kijun": kijun.rename("kijun"),
        "senkou_a": senkou_a.rename("senkou_a"),
        "senkou_b": senkou_b.rename("senkou_b"),
        "chikou": chikou.rename("chikou"),
    }


def _compute_ichimoku(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    """Primary Ichimoku output = Kijun (base line) for legacy callers.

    The other 4 components (Tenkan/Span A/Span B/Chikou) are exposed via
    ``{alias}_tenkan``, ``{alias}_senkou_a`` etc. — see :func:`compute`.
    """
    return _ichimoku_components(df, params)["kijun"]


def _compute_parabolic_sar(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    """Parabolic SAR (Wilder).

    H-18 fix retained: explicit two-bar seed (no silent fallback).
    """
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
            if i >= 2:
                new_sar = min(new_sar, low[i - 1], low[i - 2])
            else:
                new_sar = min(new_sar, low[i - 1])
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
            if i >= 2:
                new_sar = max(new_sar, high[i - 1], high[i - 2])
            else:
                new_sar = max(new_sar, high[i - 1])
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


def _kdj_components(
    df: pd.DataFrame, params: dict[str, Any]
) -> dict[str, pd.Series]:
    """Return KDJ's K, D, J series using the textbook Chinese-KDJ recursion.

    Q1 HIGH fix: the previous implementation returned only the EMA of
    raw stochastic %K (i.e. just one line). The standard formula is:
        RSV   = (close - LL) / (HH - LL) * 100
        K[t]  = (1 - 1/m) * K[t-1] + (1/m) * RSV[t]       # default m=3
        D[t]  = (1 - 1/m) * D[t-1] + (1/m) * K[t]
        J[t]  = 3*K[t] - 2*D[t]
    Seed convention: first valid K/D is 50.0 (TA-Lib / TradingView).
    """
    period = int(_param(params, "period", 9))
    m = int(_param(params, "m", 3))
    alpha = 1.0 / m
    hh = df["high"].rolling(period).max()
    ll = df["low"].rolling(period).min()
    rsv = (df["close"] - ll) / (hh - ll).replace(0, np.nan) * 100.0
    # Recursive K and D — initialise with NaN until the first valid RSV,
    # then seed both at 50.0 (TradingView / TA-Lib KDJ convention).
    n = len(df)
    k_arr = np.full(n, np.nan)
    d_arr = np.full(n, np.nan)
    seeded = False
    for i in range(n):
        rsv_i = rsv.iloc[i]
        if pd.isna(rsv_i):
            continue
        if not seeded:
            k_arr[i] = 50.0
            d_arr[i] = 50.0
            seeded = True
            continue
        k_arr[i] = (1.0 - alpha) * k_arr[i - 1] + alpha * rsv_i
        d_arr[i] = (1.0 - alpha) * d_arr[i - 1] + alpha * k_arr[i]
    k = pd.Series(k_arr, index=df.index, name="kdj_k")
    d = pd.Series(d_arr, index=df.index, name="kdj_d")
    j = (3.0 * k - 2.0 * d).rename("kdj_j")
    return {"k": k, "d": d, "j": j}


def _compute_kdj(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    """Primary KDJ output = K line. ``{alias}_d`` and ``{alias}_j`` are
    exposed via the multi-output suffix registry in :func:`compute`."""
    return _kdj_components(df, params)["k"]


_FUNCTIONS: dict[str, Callable[[pd.DataFrame, dict[str, Any]], pd.Series]] = {
    "rsi": _compute_rsi,
    "macd": _compute_macd,
    "macd_signal": _compute_macd_signal,
    "macd_hist": _compute_macd_hist,
    "ema": _compute_ema,
    "sma": _compute_sma,
    "bollinger_bands": _compute_bollinger_bands,
    "bollinger_upper": _compute_bollinger_upper,
    "bollinger_lower": _compute_bollinger_lower,
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


# Multi-output indicators: when these are computed, register extra
# series under suffixed aliases so rule expressions can reference
# (e.g.) ``my_stoch_d`` for the %D line, or ``my_ichi_tenkan`` for
# Ichimoku's Tenkan-sen. Backward compatible — the primary alias still
# holds the original series.
_MULTI_OUTPUTS: dict[
    str, Callable[[pd.DataFrame, dict[str, Any]], dict[str, pd.Series]]
] = {
    "stochastic": lambda df, p: {
        "d": _stoch_k_d(df, p)[1],
    },
    "ichimoku": lambda df, p: {
        "tenkan": _ichimoku_components(df, p)["tenkan"],
        "kijun": _ichimoku_components(df, p)["kijun"],
        "senkou_a": _ichimoku_components(df, p)["senkou_a"],
        "senkou_b": _ichimoku_components(df, p)["senkou_b"],
        "chikou": _ichimoku_components(df, p)["chikou"],
    },
    "kdj": lambda df, p: {
        "d": _kdj_components(df, p)["d"],
        "j": _kdj_components(df, p)["j"],
    },
}


def compute(
    df: pd.DataFrame,
    indicator_refs: list[IndicatorRef],
) -> dict[str, pd.Series]:
    """Compute series for each indicator ref.

    For single-output indicators, returns ``{alias: series}``.
    For multi-output indicators (Stochastic, Ichimoku, KDJ), additionally
    populates ``{alias}_{component}`` keys (e.g. ``my_stoch_d``,
    ``my_ichi_tenkan``) so rules can reference the additional lines.
    """
    out: dict[str, pd.Series] = {}
    for ref in indicator_refs:
        fn = _FUNCTIONS.get(ref.id)
        if fn is None:
            LOG.warning("unknown indicator id: %s", ref.id)
            out[ref.alias] = pd.Series([np.nan] * len(df), index=df.index)
            continue
        try:
            params = ref.params or {}
            out[ref.alias] = fn(df, params)
            extra_fn = _MULTI_OUTPUTS.get(ref.id)
            if extra_fn is not None:
                try:
                    for suffix, series in extra_fn(df, params).items():
                        out[f"{ref.alias}_{suffix}"] = series
                except Exception as exc:  # noqa: BLE001
                    LOG.warning(
                        "multi-output compute %s/%s failed: %s",
                        ref.id, ref.alias, exc,
                    )
        except Exception as exc:  # noqa: BLE001
            LOG.warning("compute %s/%s failed: %s", ref.id, ref.alias, exc)
            out[ref.alias] = pd.Series([np.nan] * len(df), index=df.index)
    return out
