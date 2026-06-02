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
    plus_dm = h.diff().clip(lower=0)
    minus_dm = (-l.diff()).clip(lower=0)
    tr = _atr(df, period)
    plus_di = 100 * plus_dm.ewm(alpha=1 / period).mean() / tr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1 / period).mean() / tr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return pd.DataFrame({"adx": dx.ewm(alpha=1 / period).mean(),
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
        days = int(params.get("days", 365))
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
                interval=params.get("interval", "1d"),
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
                    "next_actions": [
                        "Try another supported listed symbol.",
                        "Reduce the range or use an interval supported by the quote provider.",
                    ],
                },
                warnings=["no price history"],
                sources=["yfinance"],
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
        enriched_rows: list[dict[str, Any]] = []
        for base in ohlcv:
            idx = pd.Timestamp(base["date"])
            row: dict[str, Any] = {
                **base,
                "sma_fast": _clean_float(sma_fast_s.get(idx)),
                "sma_slow": _clean_float(sma_slow_s.get(idx)),
                "ema": _clean_float(ema.get(idx)),
                "rsi": _clean_float(rsi.get(idx)),
                "macd": _clean_float(macd_df["macd"].get(idx)),
                "macd_signal": _clean_float(macd_df["macd_signal"].get(idx)),
                "macd_hist": _clean_float(macd_df["macd_hist"].get(idx)),
                "atr": _clean_float(atr.get(idx)),
                "adx": _clean_float(adx["adx"].get(idx)),
                "stoch_k": _clean_float(stoch_df["stoch_k"].get(idx)),
                "stoch_d": _clean_float(stoch_df["stoch_d"].get(idx)),
                "tenkan": _clean_float(ichi["tenkan"].get(idx)),
                "kijun": _clean_float(ichi["kijun"].get(idx)),
                "senkou_a": _clean_float(ichi["senkou_a"].get(idx)),
                "senkou_b": _clean_float(ichi["senkou_b"].get(idx)),
            }
            if obv is not None:
                row["obv"] = _clean_float(obv.get(idx))
            enriched_rows.append(row)

        summary = {
            "last_price": float(df["close"].iloc[-1]),
            "rsi": _clean_float(rsi.iloc[-1]),
            "atr": _clean_float(atr.iloc[-1]),
            "adx": _clean_float(adx["adx"].iloc[-1]),
            "macd": _clean_float(macd_df["macd"].iloc[-1]),
            "macd_signal": _clean_float(macd_df["macd_signal"].iloc[-1]),
            "stoch_k": _clean_float(stoch_df["stoch_k"].iloc[-1]),
            "stoch_d": _clean_float(stoch_df["stoch_d"].iloc[-1]),
            "obv": _clean_float(obv.iloc[-1]) if obv is not None else None,
            "tenkan": _clean_float(ichi["tenkan"].iloc[-1]),
            "kijun": _clean_float(ichi["kijun"].iloc[-1]),
            "samples": len(ohlcv),
        }
        results: dict[str, Any] = {
            "model": "builtin",
            "ohlcv": ohlcv[-tail:],
            "bars": ohlcv[-tail:],
            "rows": enriched_rows[-tail:],
            "indicators": {
                f"sma_{sma_fast}": _points(sma_fast_s.tail(tail), 4),
                f"sma_{sma_slow}": _points(sma_slow_s.tail(tail), 4),
                f"ema_{ema_period}": _points(ema.tail(tail), 4),
                "bb_upper": _points(bb["bb_upper"].tail(tail), 4),
                "bb_mid": _points(bb["bb_mid"].tail(tail), 4),
                "bb_lower": _points(bb["bb_lower"].tail(tail), 4),
                "stoch_k": _points(stoch_df["stoch_k"].tail(tail), 4),
                "stoch_d": _points(stoch_df["stoch_d"].tail(tail), 4),
                "tenkan": _points(ichi["tenkan"].tail(tail), 4),
                "kijun": _points(ichi["kijun"].tail(tail), 4),
                "senkou_a": _points(ichi["senkou_a"].tail(tail), 4),
                "senkou_b": _points(ichi["senkou_b"].tail(tail), 4),
                **({"obv": _points(obv.tail(tail), 2)} if obv is not None else {}),
            },
            "indicator_rows": [
                {"indicator": "RSI", "value": summary["rsi"], "period": rsi_period, "formula": "100 - 100 / (1 + average_gain / average_loss)"},
                {"indicator": "MACD", "value": summary["macd"], "period": f"{macd_fast}/{macd_slow}/{macd_signal}", "formula": "EMA(fast) - EMA(slow); signal = EMA(MACD)"},
                {"indicator": "ATR", "value": summary["atr"], "period": atr_period, "formula": "EMA(true range)"},
                {"indicator": "ADX", "value": summary["adx"], "period": adx_period, "formula": "EMA(DX) from +DI and -DI"},
                {"indicator": "Stochastic %K", "value": summary["stoch_k"], "period": f"{stoch_k_period}/{stoch_d_period}", "formula": "100 * (close - low_k) / (high_k - low_k); %D = SMA(%K)"},
                {"indicator": "OBV", "value": summary["obv"], "period": "cumulative", "formula": "sum(sign(close.diff) * volume)"},
                {"indicator": "Ichimoku tenkan", "value": summary["tenkan"], "period": "9", "formula": "(rolling_max(high,9) + rolling_min(low,9)) / 2"},
                {"indicator": "Ichimoku kijun", "value": summary["kijun"], "period": "26", "formula": "(rolling_max(high,26) + rolling_min(low,26)) / 2"},
            ],
            "summary": summary,
            "bar_count": min(len(ohlcv), tail),
            "resolution": params.get("interval", "1d"),
            "deep_history": tail > 120,
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
            metadata={"interval": params.get("interval", "1d"), "days": days, "tail": tail},
        )


def _bounded_int(value: Any, *, default: int, low: int, high: int) -> int:
    try:
        parsed = int(float(value))
    except Exception:
        parsed = default
    return max(low, min(high, parsed))
