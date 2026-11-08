"""OVDV honesty: the grid is realized vol, and the smile is only shown when quoted.

Defect (OVDV#1): every ATM value is trailing realized vol from yfinance, but the
grid is titled "implied vol" and the 25-delta risk-reversal / butterfly cards
were computed as 0.06*ATM and 0.015*ATM model constants. Without quotes the
non-ATM cells and the RR/BF cards are fabricated and must not be emitted.

Network is patched: ``_close_series`` returns a deterministic synthetic close
path so the live-realized branch runs with no provider call.
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


@pytest.fixture
def live_history(monkeypatch):
    async def _fake_close_series(fn, pair, params):  # noqa: ARG001
        return _closes()

    monkeypatch.setattr(fx, "_close_series", _fake_close_series)


def test_unquoted_surface_has_only_realized_atm_cells(live_history):
    result = _run(fx.OVDVFunction().execute(pair="EURUSD"))
    data = result.data

    assert data["vol_source"] == "live_realized_vol"
    deltas_present = {row["delta"] for row in data["surface"]}
    # No keyless option-quote source: the wings are not quoted, so they must
    # not be emitted as implied vols.
    assert deltas_present == {"ATM"}, f"fabricated smile cells emitted: {deltas_present}"
    assert data["deltas"] == ["ATM"]


def test_unquoted_risk_reversal_and_butterfly_are_null_not_model_constants(live_history):
    result = _run(fx.OVDVFunction().execute(pair="EURUSD"))
    data = result.data

    assert data["risk_reversal_25d_pct"] is None, "RR must not be 0.06*ATM when unquoted"
    assert data["butterfly_25d_pct"] is None, "BF must not be 0.015*ATM when unquoted"
    assert data["cards"]["risk_reversal_25d_pct"] is None
    assert data["cards"]["butterfly_25d_pct"] is None
    assert data["smile_source"] == "not_quoted"
    assert "model:fx_vol_smile" not in result.sources


def test_quoted_smile_is_used_and_labelled_as_user_quotes(live_history):
    result = _run(
        fx.OVDVFunction().execute(
            pair="EURUSD", risk_reversal_25d=0.01, butterfly_25d=0.002
        )
    )
    data = result.data

    assert data["smile_source"] == "user_quotes"
    assert data["risk_reversal_25d_pct"] == pytest.approx(1.0, abs=1e-6)
    assert data["butterfly_25d_pct"] == pytest.approx(0.2, abs=1e-6)
    deltas_present = {row["delta"] for row in data["surface"]}
    assert {"10P", "25P", "ATM", "25C", "10C"} <= deltas_present


def test_explicit_atm_has_no_invented_term_slope():
    result = _run(fx.OVDVFunction().execute(pair="EURUSD", atm_vol=0.11))
    data = result.data

    assert data["vol_source"] == "user_inputs"
    atm = [row["vol"] for row in data["surface"] if row["delta"] == "ATM"]
    assert atm and all(abs(v - 11.0) < 1e-6 for v in atm), atm
