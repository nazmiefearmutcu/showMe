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
    # Tier 3 fix: a textbook RSI with zero average loss (extended rally) is
    # 100 by definition, not NaN. The old ``avg_loss.replace(0, NaN)`` made
    # ``rsi > 70`` rules silently return False during the strongest trends.
    # We branch row-by-row: if avg_loss == 0 and avg_gain > 0 → RSI = 100;
    # if both are 0 (flat) → RSI = 50; otherwise the standard formula.
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    no_loss = (avg_loss == 0) & (avg_gain > 0)
    flat = (avg_loss == 0) & (avg_gain == 0)
    rsi = rsi.where(~no_loss, 100.0)
    rsi = rsi.where(~flat, 50.0)
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
    """C-API-2 fix: accept ``num_std`` *or* ``std_dev`` aliases.

    The shipped template catalog (``templates.yml::bb-squeeze-breakout``)
    uses ``std_dev`` but the compute engine historically only read
    ``num_std``, so a user-customised ``std_dev: 3.0`` was silently
    discarded and BBM stayed at the 2σ default. Templates and rule
    builders sometimes use one name, sometimes the other; both work now.
    Explicit ``num_std`` wins if both are set (more specific).
    """
    if "num_std" in params:
        return float(_param(params, "num_std", 2.0))
    if "std_dev" in params:
        return float(_param(params, "std_dev", 2.0))
    return 2.0


def _compute_bollinger_upper(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    """H-16 fix: upper Bollinger band = SMA + num_std * rolling std."""
    period = int(_param(params, "period", 20))
    num_std = _bb_num_std(params)
    sma = df["close"].rolling(period).mean()
    # ddof=0 matches the most common BB convention (population std).
    std = df["close"].rolling(period).std(ddof=0)
    return (sma + num_std * std).rename("bbu")


def _compute_bollinger_lower(df: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    """H-16 fix: lower Bollinger band = SMA - num_std * rolling std."""
    period = int(_param(params, "period", 20))
    num_std = _bb_num_std(params)
    sma = df["close"].rolling(period).mean()
    std = df["close"].rolling(period).std(ddof=0)
    return (sma - num_std * std).rename("bbl")


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
    high, low, _close = df["high"], df["low"], df["close"]
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
    """On-Balance Volume.

    Tier 3 fix: textbook OBV seeds at the first bar's volume (the first
    bar has no prior close so direction is undefined — convention is to
    take the volume as-is). The old ``.fillna(0)`` discarded that first
    bar's contribution, which left every OBV-based rule comparing against
    a value that was systematically lower than every charting library's
    output for the same window.
    """
    diff = df["close"].diff()
    direction = np.sign(diff)
    # First bar: no prior close → seed direction as +1 so volume[0] flows
    # into the cumulative sum; this matches TradingView / TA-Lib output.
    direction = direction.where(~direction.isna(), 1.0)
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
    """Parabolic SAR (Wilder).

    H-18 fix: the textbook PSAR cap rule needs ``low[i-1]`` AND ``low[i-2]``
    (or ``high[i-1]`` AND ``high[i-2]`` in downtrend). For i==1 those
    look-backs don't exist; the original implementation silently substituted
    ``low[i-1]`` for the missing ``low[i-2]`` which deviates from the
    standard and contaminates the next ~30 bars. We now seed the first two
    bars explicitly: bar 0 starts the uptrend at its low, bar 1 is computed
    from bar 0 only (no cap — there's no i-2 reference yet), and from bar 2
    onward the standard two-bar cap applies.
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

    # H-18 fix: explicit initialization. Assume initial uptrend; SAR seeded
    # at first bar's low, EP at first bar's high. The first iteration step
    # uses only the single-bar cap (low[i-1]) since no i-2 exists yet.
    up = True
    af = af_start
    ep = high[0]
    sar[0] = low[0]

    for i in range(1, n):
        prev_sar = sar[i - 1]
        new_sar = prev_sar + af * (ep - prev_sar)
        if up:
            # H-18: only apply two-bar cap once we actually have two prior bars.
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
    # H-17 fix: separate ids for MACD signal line and histogram so rules
    # can reference them via distinct indicator aliases. Templates that
    # depend on a histogram crossing zero (bb-squeeze-breakout variants)
    # are now expressible.
    "macd_signal": _compute_macd_signal,
    "macd_hist": _compute_macd_hist,
    "ema": _compute_ema,
    "sma": _compute_sma,
    "bollinger_bands": _compute_bollinger_bands,
    # H-16 fix: register upper and lower Bollinger bands as separate ids.
    # The bb-squeeze-breakout template can now reference price crossing
    # ``bollinger_upper`` / ``bollinger_lower`` for entries/exits.
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
