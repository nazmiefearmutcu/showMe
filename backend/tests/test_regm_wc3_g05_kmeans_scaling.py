"""REGM#4 (wc3-g05): history clustering standardizes features before k-means.

Raw [MA spread %, realized vol %, drawdown %] let the 0-50 volatility scale
dominate the trend scale. The cluster must report the scaling it used, and its
centers must be in the same units as the features (not standardized units).
Network is patched: a seeded random walk stands in for the benchmark.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.functions.macro.regm import REGMFunction  # noqa: E402
from showme.engine.services import regime_classifier as rgm  # noqa: E402


def test_standardize_features_is_zero_mean_unit_scale_and_reports_scaling() -> None:
    feats = np.array([[0.5, 10.0, -1.0], [6.0, 50.0, -9.0], [-2.0, 30.0, -4.0], [1.0, 20.0, -2.0]])
    scaled, scaling = rgm.standardize_features(feats)
    assert np.allclose(scaled.mean(axis=0), 0.0, atol=1e-9)
    assert np.allclose(scaled.std(axis=0), 1.0, atol=1e-9)
    assert scaling["method"] == "z_score"
    assert np.allclose(scaling["mean"], feats.mean(axis=0))
    assert np.allclose(scaling["std"], feats.std(axis=0))


def test_standardize_features_guards_constant_column() -> None:
    feats = np.array([[1.0, 5.0], [2.0, 5.0], [3.0, 5.0]])
    scaled, scaling = rgm.standardize_features(feats)
    assert np.isfinite(scaled).all()
    assert scaling["std"][1] == 1.0  # constant column is not divided by zero


class _FakeYFinance:
    async def fetch(self, request):  # noqa: ANN001 - fake seam
        import pandas as pd

        rng = np.random.default_rng(7)
        close = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, size=400)))
        idx = pd.date_range(end="2026-09-20", periods=400, freq="D")
        return pd.DataFrame({"close": close}, index=idx)


class _Boom:
    async def get(self, url, timeout=None):  # noqa: ANN001 - fake seam
        raise RuntimeError("network down")


def _history():
    fn = REGMFunction(FunctionDeps(yfinance=_FakeYFinance()))
    fn._http_client = _Boom()
    return asyncio.run(fn.execute(symbol="SPY", action="history", window=60)).data


def test_history_cluster_reports_z_score_scaling() -> None:
    cluster = _history()["cluster"]
    # RED before fix: cluster carried only labels/centers/k, no scaling metadata.
    scaling = cluster["feature_scaling"]
    assert scaling["method"] == "z_score", scaling
    assert scaling["features"] == ["ma50_vs_200_pct", "realized_vol_pct", "drawdown_pct"], scaling
    assert len(scaling["mean"]) == 3 and len(scaling["std"]) == 3


def test_history_cluster_centers_are_in_feature_units() -> None:
    data = _history()
    cluster = data["cluster"]
    assert len(_feature_rows()) == len(data["history"])
    labels = np.array(cluster["labels"])
    feats = np.array([[r["ma50_vs_200_pct"], r["realized_vol_pct"], r["drawdown_pct"]] for r in _feature_rows()])
    for c, center in enumerate(cluster["centers"]):
        members = feats[labels == c]
        if len(members):
            # Centers are means of member features in original units (not z-scores).
            assert np.allclose(center, members.mean(axis=0), atol=1e-6), (c, center, members.mean(axis=0))


def _feature_rows():
    rng = np.random.default_rng(7)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, size=400)))
    rows = []
    for i in range(60, len(close)):
        r = rgm.classify(close[max(i - 252, 0): i + 1], spread_2s10s_bp=None)
        rows.append({"ma50_vs_200_pct": r.get("ma50_vs_200_pct", 0),
                     "realized_vol_pct": r.get("realized_vol_pct", 0),
                     "drawdown_pct": r.get("drawdown_pct", 0)})
    return rows
