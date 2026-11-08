"""DDM#5 follow-up: a zero or missing dividend returns an explicit state, not a fake 0.

Offline: the yfinance provider is an injected fake.
"""
from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument


# ─────────────────────────────────────────────────────────────────────────
# DDM#5 — a zero or missing dividend must return an explicit state, not a fake 0
# ─────────────────────────────────────────────────────────────────────────


class _YFinanceZeroDividend:
    async def fetch(self, request: Any) -> Any:
        class _Resp:
            extras = {"raw": {"dividendRate": 0}}

        return _Resp()


def _ddm(deps: FunctionDeps, **params: Any):
    from showme.engine.functions.equity.dcf import DDMFunction

    instr = Instrument(symbol="GOOG", asset_class=AssetClass.EQUITY)
    return asyncio.run(DDMFunction(deps).execute(instrument=instr, **params))


def test_ddm_zero_dividend_returns_needs_input_without_fair_value() -> None:
    res = _ddm(
        FunctionDeps(yfinance=_YFinanceZeroDividend()),
        required_return=0.08,
        growth_rate=0.03,
    )
    assert res.data["status"] == "not_applicable"  # a non-payer: Gordon DDM does not apply (merged DDM fixes)
    assert res.data.get("fair_value_per_share") is None
    assert res.data.get("reason")
    assert res.data.get("next_actions")
    assert any("non-dividend" in w.lower() for w in res.warnings)


def test_ddm_explicit_zero_dividend_is_not_ok() -> None:
    res = _ddm(FunctionDeps(), dividend_ttm=0.0, required_return=0.08, growth_rate=0.03)
    assert res.data["status"] == "not_applicable"
    assert res.data.get("fair_value_per_share") is None
