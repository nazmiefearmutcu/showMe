"""WC1-G19 RPAR: risk_target is honoured for both methods, with method stated explicitly.

The handler default is now ERC, so the inverse-vol case must pass method=inverse_vol
explicitly; the pre-existing test in test_rpar_declared_controls.py keeps its
original call and therefore exercises the ERC default.

No network: the market-data adapter is a deterministic fake keyed by symbol.
"""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio.rpar import RPARFunction


class _FakeYfinance:
    async def fetch(self, request: Any, *_args: Any, **_kwargs: Any) -> pd.DataFrame:
        symbol = request.instrument.symbol
        seed = sum(ord(ch) for ch in symbol)
        rng = np.random.default_rng(seed)
        n = 320
        vol = 0.008 + (seed % 7) * 0.003
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.0003, vol, n)))
        idx = pd.bdate_range(end="2026-10-30", periods=n)
        return pd.DataFrame({"close": close}, index=idx)


def _run(**params: Any):
    return asyncio.run(RPARFunction(FunctionDeps(yfinance=_FakeYfinance())).execute(symbols="AAA,BBB,CCC", **params))


def test_explicit_inverse_vol_hits_the_risk_target() -> None:
    out = _run(method="inverse_vol", risk_target=0.07)
    assert out.data["info"]["method"] == "inverse_vol"
    assert out.data["portfolio_vol"] == pytest.approx(0.07, abs=1e-6)


def test_default_method_is_erc_and_hits_the_risk_target() -> None:
    out = _run(risk_target=0.07)
    assert out.data["info"]["method"] == "erc"
    assert out.data["portfolio_vol"] == pytest.approx(0.07, abs=1e-6)
