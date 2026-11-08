"""OVDV#5: statistically weak realized-vol estimates and managed-currency pairs get caveats.

The 1W ATM is the standard deviation of only 5 daily returns, and a managed or
pegged pair (e.g. USDTRY) has a realized vol that reflects a managed rate path,
not an option-market level. Neither was flagged. The values are unchanged; the
caveats are added to ``warnings``.

Network is patched: ``_close_series`` returns a deterministic close path.
"""
from __future__ import annotations

import asyncio
import math

import pytest

from showme.engine.functions.fx import _funcs as fx


def _run(coro):
    return asyncio.run(coro)


def _closes(n: int = 400, start: float = 1.10) -> list[float]:
    out = [start]
    for i in range(1, n):
        out.append(out[-1] * math.exp(0.004 * math.sin(i / 7.0) + (0.0005 if i % 3 else -0.0003)))
    return out


@pytest.fixture(autouse=True)
def live_history(monkeypatch):
    async def _fake_close_series(fn, pair, params):  # noqa: ARG001
        return _closes()

    monkeypatch.setattr(fx, "_close_series", _fake_close_series)


def test_one_week_tenor_is_flagged_as_small_sample():
    result = _run(fx.OVDVFunction().execute(pair="EURUSD"))

    joined = " | ".join(result.warnings)
    assert "1W" in joined and "5 daily returns" in joined, result.warnings
    assert "statistically weak" in joined, result.warnings
    # The value itself is not altered by the caveat.
    assert result.data["series"][0]["tenor"] == "1W"


def test_managed_currency_pair_gets_a_caveat():
    result = _run(fx.OVDVFunction().execute(pair="USDTRY"))

    joined = " | ".join(result.warnings)
    assert "managed" in joined.lower() and "TRY" in joined, result.warnings


def test_free_floating_pair_has_no_managed_caveat():
    result = _run(fx.OVDVFunction().execute(pair="EURUSD"))

    assert not any("managed" in w.lower() for w in result.warnings), result.warnings


def test_user_quoted_managed_pair_is_not_called_realized():
    # A user-quoted flat ATM is not a realized-vol estimate, so no realized caveat applies.
    result = _run(fx.OVDVFunction().execute(pair="USDTRY", atm_vol=0.2))

    assert result.data["vol_source"] == "user_inputs"
    assert not any("managed" in w.lower() for w in result.warnings), result.warnings
    assert not any("daily returns" in w for w in result.warnings), result.warnings
