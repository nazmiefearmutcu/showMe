"""TECH — Multi-indicator technical analysis.

Plan §15.1: pandas-ta'nın 100+ indikatör katalogu, çoklu pane.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument


def _ema(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(span=period, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = -delta.clip(upper=0).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.where(
        ~(loss == 0.0),
        np.where(gain > 0.0, 100.0, 50.0)
    )


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    fast_e = _ema(close, fast)
    slow_e = _ema(close, slow)
    macd = fast_e - slow_e
    sig = _ema(macd, signal)
    return pd.DataFrame({"macd": macd, "macd_signal": sig, "macd_hist": macd - sig})


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def _bollinger(close: pd.Series, period: int = 20, std: float = 2.0) -> pd.DataFrame:
    mid = close.rolling(period).mean()
    sd = close.rolling(period).std(ddof=0)
    return pd.DataFrame({"bb_mid": mid, "bb_upper": mid + std * sd,
                          "bb_lower": mid - std * sd})


def _stoch(df: pd.DataFrame, k: int = 14, d: int = 3) -> pd.DataFrame:
    low_min = df["low"].rolling(k).min()
    high_max = df["high"].rolling(k).max()
    pk = 100 * (df["close"] - low_min) / (high_max - low_min)
    return pd.DataFrame({"stoch_k": pk, "stoch_d": pk.rolling(d).mean()})


def _adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    h, l, _c = df["high"], df["low"], df["close"]
    up = h.diff()
    down = -l.diff()
    # Wilder's directional-movement rule: on each bar only the LARGER of the
    # two positive movements counts; the other side is zeroed. Clipping each
    # side independently double-counted outside bars and inflated both DIs.
    plus_dm = up.clip(lower=0).where(up > down, 0.0)
    minus_dm = down.clip(lower=0).where(down > up, 0.0)
    tr = _atr(df, period)
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / tr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / tr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return pd.DataFrame({"adx": dx.ewm(alpha=1 / period, adjust=False).mean(),
                          "plus_di": plus_di, "minus_di": minus_di})


def _obv(df: pd.DataFrame) -> pd.Series:
    direction = df["close"].diff().fillna(0)
    sign = direction.where(direction == 0, np.sign(direction))
    return (sign * df["volume"]).cumsum()


def _ichimoku(df: pd.DataFrame) -> pd.DataFrame:
    high9 = df["high"].rolling(9).max()
    low9 = df["low"].rolling(9).min()
    tenkan = (high9 + low9) / 2
    high26 = df["high"].rolling(26).max()
    low26 = df["low"].rolling(26).min()
    kijun = (high26 + low26) / 2
    senkou_a = ((tenkan + kijun) / 2).shift(26)
    high52 = df["high"].rolling(52).max()
    low52 = df["low"].rolling(52).min()
    senkou_b = ((high52 + low52) / 2).shift(26)
    chikou = df["close"].shift(-26)
    return pd.DataFrame({"tenkan": tenkan, "kijun": kijun,
                          "senkou_a": senkou_a, "senkou_b": senkou_b,
                          "chikou": chikou})


_INDICATOR_FUNCS = {
    "rsi": _rsi, "macd": _macd, "atr": _atr, "bbands": _bollinger,
    "stoch": _stoch, "adx": _adx, "obv": _obv, "ichimoku": _ichimoku,
}


def _clean_float(value: Any) -> float | None:
    try:
        number = float(value)
    except Exception:
        return None
    return number if np.isfinite(number) else None


def _time_label(value: Any) -> str:
    try:
        ts = pd.Timestamp(value)
        return ts.isoformat()
    except Exception:
        return str(value)


def _points(series: pd.Series, digits: int = 4) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, value in series.dropna().items():
        number = _clean_float(value)
        if number is None:
            continue
        out.append({"time": _time_label(idx), "value": round(number, digits)})
    return out


def _ohlcv_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        close = _clean_float(row.get("close"))
        if close is None:
            continue
        rows.append({
            "date": _time_label(idx),
            "open": _clean_float(row.get("open")),
            "high": _clean_float(row.get("high")),
            "low": _clean_float(row.get("low")),
            "close": close,
            "volume": _clean_float(row.get("volume")),
        })
    return rows


@FunctionRegistry.register
class TECHFunction(BaseFunction):
    code = "TECH"
    name = "Technical Indicators"
    asset_classes = (AssetClass.EQUITY, AssetClass.CRYPTO, AssetClass.ETF,
                      AssetClass.FX, AssetClass.COMMODITY, AssetClass.INDEX)
    category = "chart"
    description = "30+ technical indicators (RSI/MACD/ATR/Bollinger/Stochastic/ADX/OBV/Ichimoku/...)"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("TECH requires instrument")
        if not self.deps.yfinance:
            return FunctionResult(code=self.code, instrument=instrument, data={},
                                  warnings=["no yfinance"])
        # wc1-g33 (TECH#5): studies selects the families that are computed and
        # returned; interval is validated against the supported list before any
        # provider call (an unknown value used to reach yfinance unchecked).
        try:
            wanted = _requested_families(params.get("studies"))
        except ValueError as exc:
            return _input_error(instrument, str(exc))
        # Case-sensitive on purpose: '1M' must not be lowercased into '1m'
        # (minute bars). Anything outside the list is rejected, never mapped.
        interval = str(params.get("interval", "1d") or "1d").strip()
        if interval not in _SUPPORTED_INTERVALS:
            return _input_error(
                instrument,
                f"interval {interval!r} is not supported; choose one of "
                f"{', '.join(_SUPPORTED_INTERVALS)}",
            )
        days = _bounded_int(params.get("days", 365), default=365, low=7, high=3650)
        tail = _bounded_int(
            params.get("tail", params.get("bars", params.get("limit", 1000))),
            default=1000,
            low=60,
            high=5000,
        )
        rsi_period = int(params.get("rsi_period", 14))
        atr_period = int(params.get("atr_period", 14))
        adx_period = int(params.get("adx_period", 14))
        sma_fast = int(params.get("sma_fast", params.get("sma_period", 20)))
        sma_slow = int(params.get("sma_slow", 50))
        ema_period = int(params.get("ema_period", 20))
        bb_period = int(params.get("bb_period", 20))
        bb_std = float(params.get("bb_std", 2.0))
        macd_fast = int(params.get("macd_fast", 12))
        macd_slow = int(params.get("macd_slow", 26))
        macd_signal = int(params.get("macd_signal", 9))
        try:
            df = await self.deps.yfinance.fetch(DataRequest(
                kind=DataKind.OHLCV, instrument=instrument,
                start=datetime.now(timezone.utc) - timedelta(days=days),
                interval=interval,
            ))
        except Exception as exc:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "provider_unavailable",
                    "rows": [],
                    "ohlcv": [],
                    "summary": {"symbol": instrument.symbol, "days": days},
                    "reason": f"yfinance fetch failed: {exc}",
                    "next_actions": [
                        "Try again later or check symbol support.",
                    ],
                },
                warnings=[f"yfinance: {exc}"],
                sources=["yfinance"],
            )
        if df.empty:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={
                    "status": "no_price_history",
                    "rows": [],
                    "ohlcv": [],
                    "summary": {"symbol": instrument.symbol, "days": days},
                    # CHGS/TECH panes branch on `status` for the honest outage
                    # state; a reason string keeps that branch informative.
                    "reason": (
                        f"provider returned no price history for {instrument.symbol} "
                        f"({days}d, interval {params.get('interval', '1d')})"
                    ),
                    "next_actions": [
                        "Try another supported listed symbol.",
                        "Reduce the range or use an interval supported by the quote provider.",
                    ],
                },
                warnings=["no price history"],
                sources=["yfinance"],
                # wc1-g33 (TECH#3): an empty frame proves nothing live. The
                # explicit live=False veto keeps the sanitizer from pinning
                # data_state=live on an empty body (the yfinance source name
                # alone would).
                metadata={"live": False, "data_mode": "empty"},
            )

        df = df.sort_index()
        close = df["close"].astype(float)
        rsi = _rsi(close, rsi_period)
        macd_df = _macd(close, macd_fast, macd_slow, macd_signal)
        bb = _bollinger(close, bb_period, bb_std)
        atr = _atr(df, atr_period)
        adx = _adx(df, adx_period)
        sma_fast_s = close.rolling(sma_fast).mean()
        sma_slow_s = close.rolling(sma_slow).mean()
        ema = _ema(close, ema_period)
        # Wire Stochastic, OBV and Ichimoku — the helpers existed since the
        # initial commit but only the four canonical indicators above used
        # to be enriched into rows / surfaced via `indicators`, even though
        # the function description promised them. Without them the panel
        # silently dropped a third of its advertised surface.
        stoch_k_period = int(params.get("stoch_k", 14))
        stoch_d_period = int(params.get("stoch_d", 3))
        stoch_df = _stoch(df, stoch_k_period, stoch_d_period)
        obv = _obv(df) if "volume" in df.columns else None
        ichi = _ichimoku(df)

        ohlcv = _ohlcv_rows(df)
        # wc1-g33 (TECH#5): only the requested families reach the output. The
        # wanted=None default (no studies sent) keeps every family, as before.
        def _has(family: str) -> bool:
            return wanted is None or family in wanted

        enriched_rows: list[dict[str, Any]] = []
        for base in ohlcv:
            idx = pd.Timestamp(base["date"])
            row: dict[str, Any] = dict(base)
            if _has("SMA"):
                row["sma_fast"] = _clean_float(sma_fast_s.get(idx))
                row["sma_slow"] = _clean_float(sma_slow_s.get(idx))
            if _has("EMA"):
                row["ema"] = _clean_float(ema.get(idx))
            if _has("RSI"):
                row["rsi"] = _clean_float(rsi.get(idx))
            if _has("MACD"):
                row["macd"] = _clean_float(macd_df["macd"].get(idx))
                row["macd_signal"] = _clean_float(macd_df["macd_signal"].get(idx))
                row["macd_hist"] = _clean_float(macd_df["macd_hist"].get(idx))
            if _has("ATR"):
                row["atr"] = _clean_float(atr.get(idx))
            if _has("ADX"):
                row["adx"] = _clean_float(adx["adx"].get(idx))
            if _has("Stochastic"):
                row["stoch_k"] = _clean_float(stoch_df["stoch_k"].get(idx))
                row["stoch_d"] = _clean_float(stoch_df["stoch_d"].get(idx))
            if _has("Ichimoku"):
                row["tenkan"] = _clean_float(ichi["tenkan"].get(idx))
                row["kijun"] = _clean_float(ichi["kijun"].get(idx))
                row["senkou_a"] = _clean_float(ichi["senkou_a"].get(idx))
                row["senkou_b"] = _clean_float(ichi["senkou_b"].get(idx))
            if obv is not None and _has("OBV"):
                row["obv"] = _clean_float(obv.get(idx))
            enriched_rows.append(row)

        summary: dict[str, Any] = {"last_price": float(df["close"].iloc[-1])}
        if _has("RSI"):
            summary["rsi"] = _clean_float(rsi.iloc[-1])
        if _has("ATR"):
            summary["atr"] = _clean_float(atr.iloc[-1])
        if _has("ADX"):
            summary["adx"] = _clean_float(adx["adx"].iloc[-1])
        if _has("MACD"):
            summary["macd"] = _clean_float(macd_df["macd"].iloc[-1])
            summary["macd_signal"] = _clean_float(macd_df["macd_signal"].iloc[-1])
        if _has("Stochastic"):
            summary["stoch_k"] = _clean_float(stoch_df["stoch_k"].iloc[-1])
            summary["stoch_d"] = _clean_float(stoch_df["stoch_d"].iloc[-1])
        if _has("OBV") and obv is not None:
            summary["obv"] = _clean_float(obv.iloc[-1])
        if _has("Ichimoku"):
            summary["tenkan"] = _clean_float(ichi["tenkan"].iloc[-1])
            summary["kijun"] = _clean_float(ichi["kijun"].iloc[-1])
        summary["samples"] = len(ohlcv)
        results: dict[str, Any] = {
            "model": "builtin",
            "ohlcv": ohlcv[-tail:],
            "bars": ohlcv[-tail:],
            "rows": enriched_rows[-tail:],
            "indicators": {
                **({f"sma_{sma_fast}": _points(sma_fast_s.tail(tail), 4),
                    f"sma_{sma_slow}": _points(sma_slow_s.tail(tail), 4)} if _has("SMA") else {}),
                **({f"ema_{ema_period}": _points(ema.tail(tail), 4)} if _has("EMA") else {}),
                **({"bb_upper": _points(bb["bb_upper"].tail(tail), 4),
                    "bb_mid": _points(bb["bb_mid"].tail(tail), 4),
                    "bb_lower": _points(bb["bb_lower"].tail(tail), 4)} if _has("BB") else {}),
                **({"stoch_k": _points(stoch_df["stoch_k"].tail(tail), 4),
                    "stoch_d": _points(stoch_df["stoch_d"].tail(tail), 4)} if _has("Stochastic") else {}),
                **({"tenkan": _points(ichi["tenkan"].tail(tail), 4),
                    "kijun": _points(ichi["kijun"].tail(tail), 4),
                    "senkou_a": _points(ichi["senkou_a"].tail(tail), 4),
                    "senkou_b": _points(ichi["senkou_b"].tail(tail), 4)} if _has("Ichimoku") else {}),
                **({"obv": _points(obv.tail(tail), 2)} if obv is not None and _has("OBV") else {}),
            },
            "indicator_rows": [
                family_row for family, family_row in (
                    ("RSI", {"indicator": "RSI", "value": summary.get("rsi"), "period": rsi_period, "formula": "100 - 100 / (1 + average_gain / average_loss)"}),
                    ("MACD", {"indicator": "MACD", "value": summary.get("macd"), "period": f"{macd_fast}/{macd_slow}/{macd_signal}", "formula": "EMA(fast) - EMA(slow); signal = EMA(MACD)"}),
                    ("ATR", {"indicator": "ATR", "value": summary.get("atr"), "period": atr_period, "formula": "EMA(true range)"}),
                    ("ADX", {"indicator": "ADX", "value": summary.get("adx"), "period": adx_period, "formula": "EMA(DX) from +DI and -DI"}),
                    ("Stochastic", {"indicator": "Stochastic %K", "value": summary.get("stoch_k"), "period": f"{stoch_k_period}/{stoch_d_period}", "formula": "100 * (close - low_k) / (high_k - low_k); %D = SMA(%K)"}),
                    ("OBV", {"indicator": "OBV", "value": summary.get("obv"), "period": "cumulative", "formula": "sum(sign(close.diff) * volume)"}),
                    ("Ichimoku", {"indicator": "Ichimoku tenkan", "value": summary.get("tenkan"), "period": "9", "formula": "(rolling_max(high,9) + rolling_min(low,9)) / 2"}),
                    ("Ichimoku", {"indicator": "Ichimoku kijun", "value": summary.get("kijun"), "period": "26", "formula": "(rolling_max(high,26) + rolling_min(low,26)) / 2"}),
                ) if _has(family)
            ],
            "summary": summary,
            "bar_count": min(len(ohlcv), tail),
            "resolution": interval,
            # wc1-g33 (TECH#6): depth of the fetched history, not the number of
            # bars the caller asked to see (tail is only a display window).
            "deep_history": len(ohlcv) > 120,
            "indicator_params": {
                "rsi_period": rsi_period,
                "sma_fast": sma_fast,
                "sma_slow": sma_slow,
                "ema_period": ema_period,
                "bb_period": bb_period,
                "bb_std": bb_std,
                "macd_fast": macd_fast,
                "macd_slow": macd_slow,
                "macd_signal": macd_signal,
                "atr_period": atr_period,
                "adx_period": adx_period,
                "stoch_k": stoch_k_period,
                "stoch_d": stoch_d_period,
            },
            "methodology": (
                "TECH computes indicators from yfinance OHLCV history. RSI uses Wilder-style exponentially "
                "weighted average gains/losses; MACD is EMA(fast) minus EMA(slow) with an EMA signal; ATR is "
                "exponentially weighted true range; Bollinger bands are rolling mean +/- standard deviations; "
                "Stochastic %K is the close's position inside the K-period high/low range with %D = SMA(%K); "
                "OBV cumulates signed volume from close-to-close direction; Ichimoku tenkan/kijun are "
                "9/26-period midpoint averages and senkou_a/_b are projected 26 periods forward."
            ),
            "field_dictionary": {
                "ohlcv": "Price candles used for the chart.",
                "sma_fast": "Fast simple moving average.",
                "sma_slow": "Slow simple moving average.",
                "rsi": "Relative Strength Index.",
                "macd": "Moving Average Convergence Divergence.",
                "atr": "Average True Range.",
                "adx": "Average Directional Index.",
                "stoch_k": "Stochastic %K (raw oscillator).",
                "stoch_d": "Stochastic %D (smoothed %K).",
                "obv": "On-Balance Volume (cumulative signed volume).",
                "tenkan": "Ichimoku conversion line (9-period midpoint).",
                "kijun": "Ichimoku base line (26-period midpoint).",
                "senkou_a": "Ichimoku leading span A, projected forward 26 periods.",
                "senkou_b": "Ichimoku leading span B, projected forward 26 periods.",
            },
            "status": "ok",
        }
        return FunctionResult(
            code=self.code, instrument=instrument,
            data=results, sources=["yfinance"],
            metadata={"live": True, "data_mode": "live_yfinance",
                      "interval": interval, "days": days, "tail": tail},
        )


def _bounded_int(value: Any, *, default: int, low: int, high: int) -> int:
    try:
        parsed = int(float(value))
    except Exception:
        parsed = default
    return max(low, min(high, parsed))


# wc1-g33 (TECH#5): the intervals the pane offers (the seed's `interval`
# options). Every one maps through the yfinance adapter's interval table.
_SUPPORTED_INTERVALS: tuple[str, ...] = ("1m", "5m", "15m", "30m", "1h", "4h", "1d", "1wk", "1mo")

# Canonical family names, keyed by upper-case alias. These are the seed's
# `studies` options.
_STUDY_FAMILIES: dict[str, str] = {
    name.upper(): name
    for name in ("SMA", "EMA", "BB", "Ichimoku", "RSI", "MACD", "ATR", "ADX", "Stochastic", "OBV")
}


def _requested_families(raw: Any) -> frozenset[str] | None:
    """Return the study families the caller asked for.

    ``None`` means no studies were sent, so every family is returned (the
    pane's default view). An unknown family name raises ValueError rather than
    being dropped silently.
    """
    if raw is None:
        return None
    items = raw if isinstance(raw, (list, tuple, set)) else str(raw).split(",")
    names = [str(item).strip() for item in items if str(item).strip()]
    if not names:
        return None
    unknown = [name for name in names if name.upper() not in _STUDY_FAMILIES]
    if unknown:
        raise ValueError(
            f"unknown studies: {', '.join(unknown)}; choose from "
            f"{', '.join(_STUDY_FAMILIES.values())}"
        )
    return frozenset(_STUDY_FAMILIES[name.upper()] for name in names)


def _input_error(instrument: Instrument | None, reason: str) -> FunctionResult:
    """Honest input-rejection envelope: no provider call, no fabricated rows."""
    return FunctionResult(
        code="TECH",
        instrument=instrument,
        data={
            "status": "input_error",
            "rows": [],
            "ohlcv": [],
            "summary": {"symbol": instrument.symbol if instrument else None},
            "reason": reason,
            "next_actions": ["Pick a supported interval and study families, then rerun."],
        },
        warnings=[reason],
        sources=[],
    )
