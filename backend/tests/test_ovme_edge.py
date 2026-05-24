"""Bundle C / C2 regression: OVME Black-Scholes guards against bad inputs.

Previously ``math.log(S / K)`` raised ``ValueError: math domain error``
whenever S or K was non-positive, bringing down the entire endpoint.
Now we surface a structured ``error`` marker + NaN result + warnings list.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.functions.derivative.ovme import (  # noqa: E402
    OVMEFunction,
    _bs_price,
)


def test_bs_price_returns_error_marker_when_S_nonpositive() -> None:
    result = _bs_price(S=0.0, K=100.0, T=0.5, r=0.04, sigma=0.2, q=0.0, is_call=True)
    assert "error" in result
    assert math.isnan(result["price"])
    assert math.isnan(result["delta"])


def test_bs_price_returns_error_marker_when_K_nonpositive() -> None:
    result = _bs_price(S=100.0, K=-1.0, T=0.5, r=0.04, sigma=0.2, q=0.0, is_call=False)
    assert "error" in result
    assert math.isnan(result["price"])


def test_bs_price_returns_error_marker_when_both_zero() -> None:
    result = _bs_price(S=0.0, K=0.0, T=0.5, r=0.04, sigma=0.2, q=0.0, is_call=True)
    assert "error" in result


def test_bs_price_valid_inputs_still_work() -> None:
    """Sanity: existing happy path is unchanged."""
    result = _bs_price(S=100.0, K=100.0, T=0.25, r=0.045, sigma=0.20, q=0.0, is_call=True)
    assert "error" not in result
    assert result["price"] > 0
    assert 0 < result["delta"] < 1


async def test_ovme_function_surfaces_warnings_on_invalid_spot() -> None:
    """The full OVMEFunction must produce a structured envelope, not crash."""
    fn = OVMEFunction()
    result = await fn.execute(instrument=None, spot=-50.0, strike=100.0, vol=0.2)
    assert result.data["status"] == "error"
    assert any("invalid_inputs" in w for w in result.warnings)
    assert math.isnan(result.data["price"])
    # No sensitivity curve was generated.
    assert result.data["curve"] == []


async def test_ovme_function_valid_input_returns_ok() -> None:
    fn = OVMEFunction()
    result = await fn.execute(instrument=None, spot=100, strike=100, vol=0.2)
    assert result.data["status"] == "ok"
    assert result.data["price"] > 0
    assert len(result.data["curve"]) == 51
