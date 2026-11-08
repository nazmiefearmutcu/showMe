"""DDM#3 follow-up: an explicit caller dividend_ttm=0 must be attributed to the caller.

The non-payer state is not_applicable with a null fair value. When the caller passed
dividend_ttm=0 the provider was never asked, so the reason and warning must not claim
"the provider reports no trailing dividend". No network: no adapter is wired in.
"""

from __future__ import annotations

import asyncio

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.dcf import DDMFunction

AMZN = Instrument(symbol="AMZN", asset_class=AssetClass.EQUITY)


def _run(**params):
    return asyncio.run(DDMFunction(FunctionDeps()).execute(AMZN, **params))


def test_explicit_zero_dividend_is_not_applicable_with_null_value() -> None:
    res = _run(dividend_ttm=0)
    assert res.data["status"] == "not_applicable", res.data
    assert res.data["fair_value_per_share"] is None
    assert res.data["surface"] == []
    assert res.data["rows"] == []


def test_explicit_zero_dividend_reason_credits_the_caller_not_the_provider() -> None:
    res = _run(dividend_ttm=0.0)
    reason = res.data["reason"]
    assert "Provider" not in reason and "provider" not in reason, reason
    assert "dividend_ttm" in reason, reason


def test_explicit_zero_dividend_warning_credits_the_caller_not_the_provider() -> None:
    res = _run(dividend_ttm=0)
    text = " ".join(res.warnings)
    assert "provider returned" not in text.lower(), res.warnings
    assert "dividend_ttm=0" in text or "dividend_ttm was 0" in text, res.warnings
    # The caller already supplied the value, so the warning must not ask for it again.
    assert "Pass dividend_ttm explicitly to override" not in text, res.warnings


def test_explicit_zero_dividend_has_no_provider_sources() -> None:
    res = _run(dividend_ttm=0)
    assert "yfinance" not in res.sources
    assert res.data["dividend_forward_indicated"] is None
