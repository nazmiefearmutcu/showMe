"""DES honesty fixes (wc1-g46): dividend-yield units, empty reference data, sources."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.core.refdata import ReferenceData
from showme.engine.functions.equity.des import DESFunction, _promote_raw_fields


def _instrument() -> Instrument:
    return Instrument(
        symbol="AAPL",
        asset_class=AssetClass.EQUITY,
        exchange="NMS",
        currency="USD",
        name="Apple Inc.",
    )


class _Provider:
    def __init__(self, payload: Any) -> None:
        self._payload = payload
        self.calls = 0

    async def fetch(self, request: Any) -> Any:  # noqa: ARG002
        self.calls += 1
        return self._payload


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ── DES#3: dividend yield unit comes from the yfinance field name ──────────


def test_dividend_yield_percent_field_without_trailing_key_is_percent() -> None:
    # dividendYield is percent-form (0.15 = 0.15%). It must not be read as a
    # decimal fraction (which would render as 15%).
    data: dict[str, Any] = {}
    _promote_raw_fields(data, {"dividendYield": 0.15})
    assert data["dividendYield"] == pytest.approx(0.0015)


def test_dividend_yield_trailing_key_is_decimal_even_when_small() -> None:
    data: dict[str, Any] = {}
    _promote_raw_fields(data, {"trailingAnnualDividendYield": 0.0015})
    assert data["dividendYield"] == pytest.approx(0.0015)


def test_dividend_yield_trailing_key_wins_over_percent_field() -> None:
    data: dict[str, Any] = {}
    _promote_raw_fields(
        data, {"trailingAnnualDividendYield": 0.0044, "dividendYield": 0.44}
    )
    assert data["dividendYield"] == pytest.approx(0.0044)


# ── T10: an empty yfinance reference payload is not a live answer ──────────


def _empty_refdata() -> ReferenceData:
    # What the yfinance adapter returns when the info call is refused: every
    # profile field is empty and the failure is only recorded in extras.raw.
    return ReferenceData(
        symbol="AAPL",
        name=None,
        asset_class="EQUITY",
        exchange=None,
        currency=None,
        source="yfinance",
        extras={"raw": {"info_error": "Connection refused"}},
    )


def test_des_empty_refdata_is_not_reported_as_live_yfinance() -> None:
    fn = DESFunction()
    yf = _Provider(_empty_refdata())
    fn.deps = FunctionDeps(yfinance=yf)

    result = _run(fn.execute(_instrument()))
    assert result.data["status"] == "provider_unavailable"
    assert result.sources == []
    assert result.metadata.get("fallback") is True
    assert any("Connection refused" in w for w in result.metadata["provider_errors"])


# ── DES#2: an exhausted provider chain lists no sources ────────────────────


def test_des_provider_exhausted_reports_no_sources_but_attempted_list() -> None:
    fn = DESFunction()
    fn.deps = FunctionDeps(yfinance=_Provider(None))

    result = _run(fn.execute(_instrument()))
    assert result.data["status"] == "provider_unavailable"
    assert result.sources == []
    assert result.metadata["attempted_providers"] == ["yfinance"]


def test_bare_dividend_yield_without_field_name_is_not_magnitude_guessed() -> None:
    # A dividendYield already on the record has no yfinance field name to say
    # its unit. A magnitude guess read 0.15 as 15%, so it is dropped instead.
    data: dict[str, Any] = {"dividendYield": 0.15}
    _promote_raw_fields(data, {})
    assert data["dividendYield"] is None


def test_bare_decimal_dividend_yield_is_not_rescaled_by_magnitude() -> None:
    data: dict[str, Any] = {"dividendYield": 0.25}
    _promote_raw_fields(data, {})
    assert data["dividendYield"] is None
