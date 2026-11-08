"""REGM data policy: a failed benchmark never becomes a synthetic regime.

When the yfinance benchmark is unavailable, ``allow_model=true`` used to
substitute ``100 + 0.04t + 3 sin(t/14)`` and classify it. The response then
carried a regime label, an input_coverage value and a ``regime_model`` source,
all from invented prices. The function now returns provider_unavailable in
every case and says that ``allow_model`` is ignored.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.functions.macro.regm import REGMFunction  # noqa: E402


class _BoomClient:
    async def get(self, url, timeout=None):  # noqa: ANN001 - fake seam
        raise RuntimeError("network down")


class _BoomYFinance:
    async def fetch(self, request):  # noqa: ANN001 - fake seam
        raise RuntimeError("yfinance down")


def _run(fn: REGMFunction, **params):
    fn._http_client = _BoomClient()
    return asyncio.run(fn.execute(symbol="SPY", **params))


def test_allow_model_never_classifies_a_synthetic_series() -> None:
    out = _run(REGMFunction(FunctionDeps(yfinance=_BoomYFinance())), allow_model=True)

    assert out.data["status"] == "provider_unavailable", out.data
    assert out.data["current"] == {}, out.data["current"]
    assert out.data["rows"] == [], out.data["rows"]
    assert "regime_model" not in out.sources, out.sources
    assert out.data["cards"][0] == {"label": "Regime", "value": "—"}, out.data["cards"]


def test_provider_failure_does_not_claim_yfinance_as_a_source() -> None:
    out = _run(REGMFunction(FunctionDeps(yfinance=_BoomYFinance())))

    assert out.data["status"] == "provider_unavailable", out.data
    assert "yfinance" not in out.sources, out.sources


def test_allow_model_is_reported_as_ignored() -> None:
    out = _run(REGMFunction(FunctionDeps(yfinance=_BoomYFinance())), allow_model=True)

    assert any("allow_model" in w and "ignored" in w for w in out.warnings), out.warnings
