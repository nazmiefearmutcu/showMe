"""F16 — missed-by-waves regressions for the CHGS/TECH outage envelopes and
the TLH tax-assumption params.

CHGS (audit A9:53 / verify-2 #4): the pane used to render every payload
without `indicators` as "The backend served its synthetic chart template".
A genuine provider outage (`provider_unavailable` / `no_price_history`) must
be distinguishable from the genuine template mode — the failure envelopes
carry an explicit `status` + a human `reason`, and only the `reference=true`
template stamps `status:"reference"` / `data_mode:"modeled"`.

TLH (audit A9:130 / verify-2 #8): the bracket and long-term rate are now
user-controlled; the backend must honour + echo the params it is sent.

All tests are offline (provider adapters are fakes).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pandas as pd

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.core.instrument import AssetClass, Instrument  # noqa: E402
from showme.engine.functions.chart.tech import TECHFunction  # noqa: E402
from showme.engine.functions.portfolio.tlh import TLHFunction  # noqa: E402

EQ = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


def _run(coro):
    return asyncio.run(coro)


class _BoomYfinance:
    async def fetch(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("quote provider down")


class _EmptyYfinance:
    async def fetch(self, *args: Any, **kwargs: Any) -> Any:
        return pd.DataFrame()


# ── TECH / CHGS failure envelopes ────────────────────────────────────────


def test_tech_provider_failure_envelope_carries_status_and_reason():
    """A failed provider fetch must return the outage status + a cause."""
    fn = TECHFunction(FunctionDeps(yfinance=_BoomYfinance()))
    res = _run(fn.execute(instrument=EQ, days=90))
    assert res.data["status"] == "provider_unavailable"
    assert res.data["rows"] == []
    assert isinstance(res.data.get("reason"), str)
    assert "quote provider down" in res.data["reason"]


def test_tech_no_price_history_envelope_carries_reason():
    """An empty OHLCV frame must ALSO name the cause (not a bare status)."""
    fn = TECHFunction(FunctionDeps(yfinance=_EmptyYfinance()))
    res = _run(fn.execute(instrument=EQ, days=90))
    assert res.data["status"] == "no_price_history"
    assert res.data["rows"] == []
    reason = res.data.get("reason")
    assert isinstance(reason, str) and reason.strip()
    assert "AAPL" in reason


def test_chgs_keyless_default_is_not_template_shaped():
    """CHGS with no provider serves the empty live body — never the template
    shape the pane now reserves for `status:"reference"` / `data_mode:"modeled"`.
    """
    from showme.engine.functions.misc._bonus import CHGSFunction

    res = _run(CHGSFunction(FunctionDeps()).execute(instrument=EQ))
    assert res.data.get("status") != "reference"
    assert res.data.get("data_mode") != "modeled"
    # No template OHLC rows and no template scalar fields leak through.
    assert not res.data.get("rows")
    assert res.data.get("last") is None
    assert res.data.get("rsi_14") is None


# ── TLH tax assumptions ──────────────────────────────────────────────────


def test_tlh_model_path_honours_custom_tax_params():
    fn = TLHFunction(FunctionDeps())
    res = _run(
        fn.execute(live_tax=False, tax_bracket=0.32, lt_cap_rate=0.18)
    )
    assert res.data["tax_bracket_used"] == 0.32
    assert res.data["lt_cap_rate_used"] == 0.18
    candidate = res.data["candidates"][0]
    assert candidate["tax_rate_applied"] == 0.18
    assert abs(candidate["estimated_tax_savings"] - 8.0 * 0.18) < 1e-9


def test_tlh_defaults_stay_24_15_when_params_absent():
    fn = TLHFunction(FunctionDeps())
    res = _run(fn.execute(live_tax=False))
    assert res.data["tax_bracket_used"] == 0.24
    assert res.data["lt_cap_rate_used"] == 0.15
