"""TECH — Multi-indicator technical analysis.

Plan §15.1: pandas-ta'nın 100+ indikatör katalogu, çoklu pane.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


def _ema(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(span=period, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = -delta.clip(upper=0).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


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
    h, l, c = df["high"], df["low"], df["close"]
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
        df = await self.deps.yfinance.fetch(DataRequest(
            kind=DataKind.OHLCV, instrument=instrument,
            start=datetime.utcnow() - timedelta(days=days),
            interval=params.get("interval", "1d"),
        ))
        if df.empty:
            return FunctionResult(code=self.code, instrument=instrument, data={},
                                  warnings=["no price history"])
        # Try pandas-ta if available, else use built-ins.
        results: dict[str, Any] = {}
        try:
            import pandas_ta as ta  # type: ignore
            df.ta.strategy("All")  # generates 100+ columns
            keep = [c for c in df.columns if c not in
                    ("open", "high", "low", "close", "volume", "dividends", "splits")]
            tail = df[keep].tail(int(params.get("tail", 30)))
            results["pandas_ta"] = tail.reset_index().to_dict(orient="records")
            results["columns"] = keep
            results["model"] = "pandas-ta full strategy"
        except Exception:
            # Built-in fallbacks
            results["model"] = "builtin"
            close = df["close"]
            results["rsi_14"] = _rsi(close, 14).tail(60).round(2).to_dict()
            macd_df = _macd(close).tail(60).round(4)
            results["macd"] = macd_df.to_dict()
            results["bollinger"] = _bollinger(close).tail(60).round(2).to_dict()
            results["atr_14"] = _atr(df, 14).tail(60).round(4).to_dict()
            results["stoch"] = _stoch(df).tail(60).round(2).to_dict()
            results["adx"] = _adx(df).tail(60).round(2).to_dict()
            results["obv"] = _obv(df).tail(60).to_dict()
            results["ichimoku"] = _ichimoku(df).tail(60).round(2).to_dict()
        # Latest values summary
        summary = {
            "last_price": float(df["close"].iloc[-1]),
            "rsi_14": float(_rsi(df["close"], 14).iloc[-1]),
            "atr_14": float(_atr(df, 14).iloc[-1]),
            "adx_14": float(_adx(df).iloc[-1, 0]),
        }
        results["summary"] = summary
        return FunctionResult(
            code=self.code, instrument=instrument,
            data=results, sources=["yfinance"],
            metadata={"interval": params.get("interval", "1d"), "days": days},
        )
