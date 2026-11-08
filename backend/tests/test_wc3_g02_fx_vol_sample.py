"""XCON-11: FX realized vol uses the sample (n-1) stdev, like the rest of the stack.

_annualized_vol used to divide the squared deviations by n (population stdev),
so an FX pair and an equity measured the same path on different estimators.
"""
from __future__ import annotations

import math
import statistics

import pytest

from showme.engine.functions.fx import _funcs as fx


def test_fx_annualized_vol_is_sample_stdev_times_sqrt_252() -> None:
    returns = [0.01, -0.02, 0.015, 0.003, -0.007, 0.012]
    expected = statistics.stdev(returns) * math.sqrt(252.0)  # sample (n-1) estimator
    assert fx._annualized_vol(returns) == pytest.approx(expected, rel=1e-12)


def test_fx_annualized_vol_uses_n_minus_one_on_two_points() -> None:
    returns = [0.01, -0.01]
    expected = math.sqrt(sum(r * r for r in returns) / (len(returns) - 1)) * math.sqrt(252.0)
    assert fx._annualized_vol(returns) == pytest.approx(expected, rel=1e-12)
