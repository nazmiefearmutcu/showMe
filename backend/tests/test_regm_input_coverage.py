"""REGM#3 — the regime 'confidence' is input coverage, not a probability.

``regime_classifier._confidence`` returns resolved inputs / 4. That number
is coverage of the four components, so it is exposed as ``input_coverage``
and no longer as ``confidence``, which the seed defines as the probability
of the chosen regime.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np
import pytest

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from showme.engine.functions._fred_csv import reset_fred_csv_cache  # noqa: E402
from showme.engine.services import regime_classifier as rgm  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_caches():
    reset_fred_csv_cache()
    yield
    reset_fred_csv_cache()


class _BoomClient:
    async def get(self, url, timeout=None):  # noqa: ANN001 - fake seam
        raise RuntimeError("network down")


class _FakeYFinance:
    """Deterministic benchmark fixture (seeded random walk), not live data."""

    async def fetch(self, request):  # noqa: ANN001 - fake seam
        import pandas as pd

        rng = np.random.default_rng(7)
        close = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, size=300)))
        idx = pd.date_range(end="2026-09-20", periods=300, freq="D")
        return pd.DataFrame({"close": close}, index=idx)


def test_classify_reports_input_coverage_not_confidence() -> None:
    rng = np.random.default_rng(7)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, size=300)))
    out = rgm.classify(close, spread_2s10s_bp=None)

    assert "confidence" not in out, sorted(out)
    # trend, vol, drawdown resolved; curve unknown -> 3 of 4 inputs.
    assert out["input_coverage"] == pytest.approx(0.75)


def test_regm_payload_reports_input_coverage_not_confidence() -> None:
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.macro.regm import REGMFunction

    fn = REGMFunction(FunctionDeps(yfinance=_FakeYFinance()))
    fn._http_client = _BoomClient()
    out = asyncio.run(fn.execute(symbol="SPY", allow_model=True))

    assert "confidence" not in out.data, sorted(out.data)
    assert "confidence" not in out.data["current"], sorted(out.data["current"])
    assert out.data["input_coverage"] == pytest.approx(0.75)
    assert out.data["current"]["input_coverage"] == pytest.approx(0.75)
