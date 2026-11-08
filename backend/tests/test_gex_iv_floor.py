"""GEX#5 regression: no constant substitutes an observed implied vol.

The chain's per-contract market IV is used as observed. An IV too small to
price safely is excluded and counted in ``excluded.implied_vol`` (disclosed),
never replaced by a floor value such as 0.05.

No network: pure service-level calls.
"""

from __future__ import annotations

import pytest

from showme.engine.services.gamma_exposure import bs_gamma, chain_gex


def _expected_call_gex(spot: float, strike: float, vol: float, T: float, oi: float,
                       rate: float = 0.04, q: float = 0.0) -> float:
    return -bs_gamma(spot, strike, vol, T, rate, q) * oi * 100 * spot ** 2 * 0.01


def test_observed_low_iv_is_priced_at_its_own_value_not_a_floor() -> None:
    # 2% IV is a real observed value; it must not be lifted to 5%.
    out = chain_gex(spot=100.0, calls=[{"strike": 100.0, "openInterest": 10,
                                        "impliedVolatility": 0.02, "T": 0.5}],
                    puts=[])
    assert out["call_gex_total"] == pytest.approx(
        _expected_call_gex(100.0, 100.0, 0.02, 0.5, 10), rel=1e-9)
    assert out["excluded"]["implied_vol"] == 0


def test_iv_below_the_numeric_floor_is_excluded_and_counted() -> None:
    good = {"strike": 105.0, "openInterest": 1000, "impliedVolatility": 0.3, "T": 0.5}
    tiny = {"strike": 100.0, "openInterest": 1000, "impliedVolatility": 1e-12, "T": 0.5}
    with_tiny = chain_gex(spot=100.0, calls=[good, tiny], puts=[])
    only_good = chain_gex(spot=100.0, calls=[good], puts=[])
    assert with_tiny["excluded"]["implied_vol"] == 1
    assert with_tiny["contracts_used"] == 1
    assert with_tiny["call_gex_total"] == pytest.approx(only_good["call_gex_total"], rel=1e-9)
    assert with_tiny["call_gex_total"] == only_good["call_gex_total"]


def test_tiny_iv_never_raises_or_produces_nan() -> None:
    out = chain_gex(spot=100.0, calls=[{"strike": 100.0, "openInterest": 10,
                                        "impliedVolatility": 5e-324, "T": 0.5}],
                    puts=[])
    assert out["contracts_used"] == 0
    assert out["excluded"]["implied_vol"] == 1
    assert out["call_gex_total"] == 0.0
