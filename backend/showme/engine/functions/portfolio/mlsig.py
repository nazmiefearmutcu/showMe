"""MLSIG — ML-based next-day direction classifier."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.services.ml_signals import fit_predict, make_features


@FunctionRegistry.register
class MLSIGFunction(BaseFunction):
    code = "MLSIG"
    name = "ML Signal Classifier"
    asset_classes = (
        AssetClass.EQUITY,
        AssetClass.CRYPTO,
        AssetClass.ETF,
        AssetClass.FX,
        AssetClass.COMMODITY,
        AssetClass.INDEX,
    )
    category = "portfolio"
    description = "Train a classifier on technical features → predict next N-day direction."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            instrument = Instrument(
                symbol=str(params.get("symbol") or "BTCUSDT"),
                asset_class=AssetClass(str(params.get("asset_class") or "CRYPTO").upper()),
            )
        days = int(params.get("days", 365 * 5))
        horizon = _label_horizon(params)
        live = _truthy(params.get("live_ml") or params.get("live_returns") or params.get("live"))
        if not live:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_no_measured_result(
                    instrument.symbol,
                    instrument.asset_class.value,
                    days,
                    horizon,
                    status="needs_input",
                    reason="No live model run was requested, so no measured accuracy, Sharpe or signal exists yet.",
                    next_actions=["Pass live_ml=true to train the classifier on live OHLCV."],
                ),
                sources=[],
                metadata={"days": days, "horizon": horizon, "rows": 0, "live": False, "fallback": False},
            )
        interval = params.get("interval", "1d")
        try:
            if not self.deps.yfinance:
                raise RuntimeError("no yfinance")
            df = await asyncio.wait_for(
                self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.OHLCV, instrument=instrument,
                    start=datetime.now(timezone.utc) - timedelta(days=days),
                    interval=interval,
                )),
                timeout=float(params.get("quote_timeout", 8)),
            )
            sources = ["yfinance"]
        except Exception:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_no_measured_result(
                    instrument.symbol,
                    instrument.asset_class.value,
                    days,
                    horizon,
                    status="provider_unavailable",
                    reason="Live OHLCV provider unavailable; no model was trained, so no metrics are reported.",
                    next_actions=["Retry when the OHLCV provider is reachable, or choose a symbol it covers."],
                ),
                sources=[],
                metadata={"days": days, "horizon": horizon, "rows": 0, "live": False, "fallback": True},
            )
        if df.empty or len(df) < 200:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_no_measured_result(
                    instrument.symbol,
                    instrument.asset_class.value,
                    days,
                    horizon,
                    status="empty",
                    reason=f"Need at least 200 OHLCV rows; provider returned {len(df)}.",
                    next_actions=["Increase Range, choose a liquid symbol, or retry the live provider."],
                ),
                sources=["yfinance"],
                metadata={"days": days, "horizon": horizon, "rows": int(len(df)), "live": False, "fallback": True},
            )
        features = make_features(df, horizon=horizon)
        labelled_rows = int(features["target"].notna().sum())
        report = fit_predict(features)
        report = _enrich_report(
            report,
            symbol=instrument.symbol,
            asset_class=instrument.asset_class.value,
            days=days,
            horizon=horizon,
            source_mode="live_yfinance",
            samples=labelled_rows,
        )
        report["ignored_options"] = _ignored_options(params, report, interval)
        return FunctionResult(
            code=self.code, instrument=instrument,
            data=report, sources=sources,
            metadata={"days": days, "horizon": horizon, "rows": labelled_rows, "live": live},
        )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _present(value: Any) -> bool:
    return value is not None and value != "" and value != []


def _label_horizon(params: dict[str, Any]) -> int:
    """Label horizon in bars: the seed's ``label_horizon`` input, else legacy ``horizon``.

    Clamped to the declared 1..60 range; an unparseable value falls back to 1.
    """
    raw = params.get("label_horizon")
    if not _present(raw):
        raw = params.get("horizon", 1)
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        value = 1
    return max(1, min(60, value))


def _ignored_options(params: dict[str, Any], report: dict[str, Any], interval: Any) -> list[dict[str, Any]]:
    """Declared inputs the caller sent that the run did not honour, with what ran instead.

    The backend chain is LightGBM, XGBoost, then a NumPy linear-probability fit.
    Only the sign-of-return label and a fixed built-in feature set are implemented.
    """
    rows: list[dict[str, Any]] = []
    backend = report.get("backend")
    family = params.get("model_family")
    if _present(family) and str(family).strip() != backend:
        rows.append({
            "option": "model_family",
            "requested": str(family).strip(),
            "used": backend,
            "reason": "The requested model family did not run; the backend shown is the model that ran.",
        })
    label_type = params.get("label_type")
    if _present(label_type) and str(label_type).strip() != "binary_updown":
        rows.append({
            "option": "label_type",
            "requested": str(label_type).strip(),
            "used": "binary_updown",
            "reason": "Only the sign-of-forward-return label is implemented.",
        })
    if _present(params.get("feature_set")):
        rows.append({
            "option": "feature_set",
            "requested": params.get("feature_set"),
            "used": "fixed built-in feature set",
            "reason": "Per-run feature selection is not implemented; the built-in feature set was used.",
        })
    train_pct = params.get("train_pct")
    if _present(train_pct):
        try:
            requested_pct = float(train_pct)
        except (TypeError, ValueError):
            requested_pct = None
        if requested_pct is None or abs(requested_pct - 0.7) > 1e-9:
            rows.append({
                "option": "train_pct",
                "requested": train_pct,
                "used": 0.7,
                "reason": "The train/test split is fixed at 70/30.",
            })
    frequency = params.get("frequency")
    if _present(frequency) and str(frequency).strip() != str(interval):
        rows.append({
            "option": "frequency",
            "requested": str(frequency).strip(),
            "used": str(interval),
            "reason": "The bar size used is the interval input.",
        })
    return rows


def _feature_rows(feature_importance: dict[str, Any]) -> list[dict[str, Any]]:
    meanings = {
        "ret_1": "One-day return momentum.",
        "ret_3": "Three-day return momentum.",
        "ret_5": "Five-day return momentum.",
        "ret_10": "Ten-day return momentum.",
        "ret_20": "Twenty-day return momentum.",
        "rsi_14": "14-period relative strength index.",
        "macd_line": "MACD fast minus slow moving average.",
        "macd_signal": "MACD signal line.",
        "macd_hist": "MACD histogram.",
        "atr_14": "14-period average true range.",
        "bb_pct": "Bollinger band percent position.",
        "vol_z": "Volume z-score versus its recent average.",
        "volume_z": "Volume z-score versus its recent average.",
        "asset_class_bias": "Reference-model asset-class prior.",
    }
    rows: list[dict[str, Any]] = []
    for feature, value in sorted(feature_importance.items(), key=lambda item: -float(item[1] or 0)):
        rows.append({
            "feature": feature,
            "importance": float(value or 0),
            "meaning": meanings.get(feature, "Model feature contribution."),
        })
    return rows


def _enrich_report(
    report: dict[str, Any],
    *,
    symbol: str,
    asset_class: str,
    days: int,
    horizon: int,
    source_mode: str,
    samples: int,
    reason: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    feature_importance = report.get("feature_importance") if isinstance(report.get("feature_importance"), dict) else {}
    rows = _feature_rows(feature_importance)
    accuracy = report.get("test_accuracy")
    sharpe = report.get("strategy_sharpe")
    # The signal comes only from a live latest-bar prediction (fit_predict);
    # test accuracy is reported separately and never sets the label.
    signal = report.get("signal")
    status = status or ("ok" if source_mode.startswith("live") else "needs_input")
    if report.get("error"):
        status = "input_error"
        signal = None
        reason = reason or str(report["error"])
    enriched = {
        "status": status,
        **report,
        "signal": signal,
        "symbol": symbol,
        "asset_class": asset_class,
        "horizon_days": horizon,
        "lookback_days": days,
        "samples": samples,
        "source_mode": source_mode,
        "rows": rows,
        "summary": {
            "test_accuracy": accuracy,
            "strategy_sharpe": sharpe,
            "signal": signal,
            "backend": report.get("backend"),
            "source_mode": source_mode,
        },
        "methodology": (
            "Classifier target = sign of the forward N-day close return. Features include lagged returns, RSI, MACD, ATR, "
            "Bollinger percent, volume z-score, and day-of-week where available. The last 30% of samples are used as the test split."
        ),
        "field_dictionary": {
            "test_accuracy": "Share of non-zero test labels where predicted direction matched realized direction.",
            "strategy_sharpe": (
                "Annualized Sharpe of out-of-sample model positions (test split only) times the realised "
                "next-bar return. In-sample fitted values are never used."
            ),
            "importance": "Relative contribution reported by the selected model backend.",
            "latest_prediction": (
                "Direction (up / down / flat) the model predicts for the most recent bar. Null when no live "
                "prediction was made."
            ),
            "signal": (
                "long_bias when the latest prediction is up, short_bias when down, neutral when flat. Null "
                "unless a live latest-bar prediction exists; test accuracy never sets it."
            ),
            "horizon_days": "Forward return horizon used to build the target label.",
        },
    }
    if reason:
        enriched["reason"] = reason
        enriched["next_actions"] = ["Increase Range, choose a liquid symbol, or retry the live provider."]
    return enriched


def _no_measured_result(
    symbol: str,
    asset_class: str,
    days: int,
    horizon: int,
    *,
    status: str,
    reason: str,
    next_actions: list[str],
) -> dict[str, Any]:
    """Explicit missing-data state: every measured field is null and nothing is invented.

    There is deliberately no per-asset-class reference profile. A fabricated
    accuracy, Sharpe, feature importance or signal would read as a measurement.
    """
    report = {
        "backend": None,
        "test_accuracy": None,
        "test_samples": 0,
        "feature_importance": {},
        "strategy_sharpe": None,
        "latest_prediction": None,
        "latest_prediction_value": None,
        "latest_bar": None,
        "signal": None,
        "labelled_samples": 0,
        "coverage": {"symbol": symbol, "asset_class": asset_class, "mode": "unavailable"},
    }
    enriched = _enrich_report(
        report,
        symbol=symbol,
        asset_class=asset_class,
        days=days,
        horizon=horizon,
        source_mode="unavailable",
        samples=0,
        reason=reason,
        status=status,
    )
    enriched["next_actions"] = list(next_actions)
    return enriched
