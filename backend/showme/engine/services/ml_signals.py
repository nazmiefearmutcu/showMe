"""ML signal classifier — next-N-day direction prediction.

Feature stack: returns lags, RSI, MACD, ATR, Bollinger %B, volume z-score,
day-of-week one-hot. Target: sign of N-day forward return.

Backend chain: LightGBM → XGBoost → sklearn GradientBoosting → logistic.
Falls through gracefully so the function works on any environment.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss = -delta.clip(upper=0).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(close: pd.Series) -> pd.DataFrame:
    fast = close.ewm(span=12, adjust=False).mean()
    slow = close.ewm(span=26, adjust=False).mean()
    line = fast - slow
    sig = line.ewm(span=9, adjust=False).mean()
    return pd.DataFrame({"macd_line": line, "macd_signal": sig,
                          "macd_hist": line - sig})


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()


def _bb_pct(close: pd.Series, period: int = 20, std: float = 2.0) -> pd.Series:
    mid = close.rolling(period).mean()
    sd = close.rolling(period).std(ddof=0)
    upper = mid + std * sd
    lower = mid - std * sd
    return (close - lower) / (upper - lower)


def make_features(df: pd.DataFrame, horizon: int = 1) -> pd.DataFrame:
    f = pd.DataFrame(index=df.index)
    f["ret_1"] = df["close"].pct_change(1)
    f["ret_3"] = df["close"].pct_change(3)
    f["ret_5"] = df["close"].pct_change(5)
    f["ret_10"] = df["close"].pct_change(10)
    f["rsi_14"] = _rsi(df["close"], 14)
    macd = _macd(df["close"])
    f = pd.concat([f, macd], axis=1)
    f["atr_14"] = _atr(df, 14)
    f["bb_pct"] = _bb_pct(df["close"])
    if "volume" in df.columns:
        vol = df["volume"]
        f["vol_z"] = (vol - vol.rolling(20).mean()) / (vol.rolling(20).std(ddof=0) + 1e-9)
    if hasattr(df.index, "dayofweek"):
        f["dow"] = df.index.dayofweek
    # Target: sign of forward N-bar return
    fwd = df["close"].pct_change(horizon).shift(-horizon)
    f["target"] = np.sign(fwd)
    return f.dropna()


def fit_predict(features: pd.DataFrame) -> dict[str, Any]:
    """Train a classifier on features (last 30% as test) and report metrics."""
    y = features["target"]
    X = features.drop(columns="target")
    n = len(features)
    if n < 100:
        return {"error": "need at least 100 rows"}
    split = int(n * 0.7)
    X_train, X_test = X.iloc[:split], X.iloc[split:]
    y_train, y_test = y.iloc[:split], y.iloc[split:]

    pred_test = None
    pred_full = None
    feat_imp: dict[str, float] = {}
    backend = "logistic"
    try:
        import lightgbm as lgb  # type: ignore
        m = lgb.LGBMClassifier(n_estimators=200, max_depth=5, num_leaves=15,
                                 learning_rate=0.05, verbose=-1)
        m.fit(X_train, y_train)
        pred_test = m.predict(X_test)
        pred_full = m.predict(X)
        feat_imp = dict(zip(X.columns, m.feature_importances_.tolist()))
        backend = "lightgbm"
    except Exception:
        pass
    if pred_test is None:
        try:
            import xgboost as xgb  # type: ignore
            m = xgb.XGBClassifier(n_estimators=200, max_depth=5, learning_rate=0.05,
                                    use_label_encoder=False, eval_metric="logloss")
            m.fit(X_train, y_train.replace({-1: 0, 0: 0, 1: 1}))
            pred_test = m.predict(X_test)
            pred_full = m.predict(X)
            feat_imp = dict(zip(X.columns, m.feature_importances_.tolist()))
            backend = "xgboost"
        except Exception:
            pass
    if pred_test is None:
        try:
            from sklearn.ensemble import GradientBoostingClassifier  # type: ignore
            m = GradientBoostingClassifier(n_estimators=200, max_depth=3, learning_rate=0.05)
            m.fit(X_train, y_train.replace({0: 1}))
            pred_test = m.predict(X_test)
            pred_full = m.predict(X)
            feat_imp = dict(zip(X.columns, m.feature_importances_.tolist()))
            backend = "sklearn_gb"
        except Exception:
            pass
    if pred_test is None:
        # Logistic baseline (pure NumPy)
        Xt = X_train.values
        yt = y_train.replace({-1: 0, 0: 0, 1: 1}).values.astype(float)
        Xt = np.column_stack([np.ones(len(Xt)), Xt])
        try:
            beta, *_ = np.linalg.lstsq(Xt, yt, rcond=None)
            Xtest_aug = np.column_stack([np.ones(len(X_test)), X_test.values])
            pred_test = np.sign(Xtest_aug @ beta - 0.5)
            pred_full = np.sign(np.column_stack([np.ones(n), X.values]) @ beta - 0.5)
            feat_imp = dict(zip(X.columns, np.abs(beta[1:]).tolist()))
            backend = "lstsq_logistic"
        except Exception:
            return {"error": "no ML backend available"}

    pred_test = np.asarray(pred_test).astype(int)
    actual = y_test.values
    # Accuracy ignoring zeros
    mask = actual != 0
    acc = float((pred_test[mask] == actual[mask]).mean()) if mask.any() else float("nan")
    # Sharpe of strategy = take pred * next-bar return
    if pred_full is not None:
        sig = pd.Series(pred_full, index=X.index)
        # next-bar realized return
        # Use 1-step return shift
        rets = features["target"].astype(float)
        strat = sig.shift(1) * rets
        sharpe = float(strat.mean() / (strat.std() + 1e-9)) * (252 ** 0.5)
    else:
        sharpe = float("nan")
    return {
        "backend": backend,
        "test_accuracy": acc,
        "test_samples": int(len(actual)),
        "feature_importance": dict(sorted(feat_imp.items(), key=lambda kv: -kv[1])[:15]),
        "strategy_sharpe": sharpe,
    }
