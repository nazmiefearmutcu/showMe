"""OVDV#2 residual: a wing cell floored at the minimum vol must not be silent.

The surface builds each wing as ``term + wing`` and floors the result at
0.0001 (0.01 vol points). When the user-quoted risk reversal and butterfly
push a wing at or below that floor, the surface cell shows the floor value
while the headline risk reversal still echoes the quote. The two then disagree
with no caveat. The fix keeps the floor but adds a warning that names the
clamped cells and the mismatch.

No network: ``atm_vol`` is supplied, so no history is fetched.
"""
from __future__ import annotations

import asyncio

from showme.engine.functions.fx import _funcs as fx


def _run(coro):
    return asyncio.run(coro)


def _floor_warnings(result) -> list[str]:
    return [w for w in result.warnings if "floor" in w.lower()]


def test_floored_wing_emits_warning_naming_cell_and_mismatch():
    # 1W: 25C = 0.0288 + (0 + (-0.0768)/2) = -0.0096 -> floored at 0.0001.
    result = _run(
        fx.OVDVFunction().execute(
            pair="USDTRY",
            atm_vol=0.0288,
            risk_reversal_25d=-0.0768,
            butterfly_25d=0.0,
        )
    )

    # The headline RR still echoes the quote (not altered by the floor).
    assert result.data["risk_reversal_25d_pct"] == -7.68

    floor = _floor_warnings(result)
    assert floor, f"floored wing was silent: {result.warnings}"
    joined = " | ".join(floor)
    assert "1W" in joined and "25C" in joined, joined
    assert "risk_reversal" in joined.lower() or "risk reversal" in joined.lower(), joined


def test_no_floor_warning_when_no_wing_is_floored():
    result = _run(
        fx.OVDVFunction().execute(
            pair="EURUSD",
            atm_vol=0.08,
            risk_reversal_25d=0.01,
            butterfly_25d=0.002,
        )
    )

    assert _floor_warnings(result) == [], result.warnings


def test_no_floor_warning_for_unquoted_surface():
    result = _run(fx.OVDVFunction().execute(pair="EURUSD", atm_vol=0.08))

    assert _floor_warnings(result) == [], result.warnings
