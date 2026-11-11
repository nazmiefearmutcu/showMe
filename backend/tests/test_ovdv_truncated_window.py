"""OVDV#4: a tenor whose realized-vol window is longer than the history must say so.

When yfinance returns fewer daily returns than a tenor's window (e.g. 1Y = 252
days), the handler used to compute that tenor over whatever returns existed and
still labelled the whole curve ``live_realized_vol`` with no warning. The
reported 1Y figure then silently covered a shorter period than its label.

Network is patched: ``_close_series`` returns a deterministic close path.
"""
from __future__ import annotations

import asyncio
import math


from showme.engine.functions.fx import _funcs as fx


def _run(coro):
    return asyncio.run(coro)


def _closes(n: int, start: float = 1.10) -> list[float]:
    out = [start]
    for i in range(1, n):
        out.append(out[-1] * math.exp(0.004 * math.sin(i / 7.0) + (0.0005 if i % 3 else -0.0003)))
    return out


def _patch_history(monkeypatch, n: int) -> None:
    async def _fake_close_series(fn, pair, params):  # noqa: ARG001
        return _closes(n)

    monkeypatch.setattr(fx, "_close_series", _fake_close_series)


def test_short_history_flags_tenor_that_used_fewer_returns(monkeypatch):
    # 41 closes -> 40 log returns: the 1Y (252d) and 6M (126d) windows cannot be filled.
    _patch_history(monkeypatch, 41)
    result = _run(fx.OVDVFunction().execute(pair="EURUSD"))

    assert result.data["vol_source"] == "live_realized_vol"
    joined = " | ".join(result.warnings)
    assert "1Y" in joined and "40" in joined and "252" in joined, result.warnings
    assert "6M" in joined and "126" in joined, result.warnings


def test_full_history_has_no_truncation_warning(monkeypatch):
    _patch_history(monkeypatch, 400)
    result = _run(fx.OVDVFunction().execute(pair="EURUSD"))

    assert not any("daily returns requested" in w for w in result.warnings), result.warnings
