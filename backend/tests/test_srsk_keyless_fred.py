"""SRSK#5: the keyless FRED DGS10 path refines the spread, with same-month legs.

The factory wires a FREDAdapter without a key, so the old ``if self.deps.fred``
check never used the keyless CSV and the yield refinement was off by default.
OECD IRLTLT01 sovereign yields are monthly averages while DGS10 is daily, so
the UST leg is the DGS10 average over the sovereign's observation month.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd
import pytest

import showme.engine.functions.bond.srsk as srsk_mod
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.bond.srsk import SRSKFunction


class _NoWorldBank:
    async def indicator(self, iso3: str, indicator: str) -> Any:  # noqa: ARG002
        return [{"page": 1, "total": 0}, None]


class _UnkeyedAdapter:
    """What production wires when FRED_API_KEY is unset."""

    api_key = ""

    async def series(self, series_id: str):  # noqa: ARG002
        raise AssertionError("an unkeyed adapter must not be called")


class _KeylessCSV:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def series(self, series_id: str):
        self.calls.append(series_id)
        if series_id == "DGS10":
            aug = pd.date_range("2026-08-03", "2026-08-31", freq="B")
            sep = pd.date_range("2026-09-01", "2026-09-30", freq="B")
            octo = pd.date_range("2026-10-01", "2026-10-30", freq="B")
            idx = aug.append(sep).append(octo)
            values = [3.0] * len(aug) + [4.0] * len(sep) + [5.0] * len(octo)
            return pd.DataFrame({"value": values}, index=idx)
        # Monthly sovereign series, last observation September.
        return pd.DataFrame({"value": [6.0, 6.5]}, index=pd.DatetimeIndex(["2026-08-01", "2026-09-01"]))


@pytest.fixture(autouse=True)
def no_network(monkeypatch) -> None:
    """World Bank legs go through the shared HTTP client; keep them offline."""
    import showme.providers._http as http_mod

    class _Dead:
        def get(self, *a: Any, **k: Any) -> Any:
            raise OSError("network disabled in tests")

    monkeypatch.setattr(http_mod, "get_client", lambda: _Dead(), raising=False)


@pytest.fixture
def keyless(monkeypatch) -> _KeylessCSV:
    fake = _KeylessCSV()
    seen: list[Any] = []

    def _fallback(fred, client=None):  # noqa: ARG001
        seen.append(fred)
        if fred and str(getattr(fred, "api_key", "") or "").strip():
            return fred
        return fake

    monkeypatch.setattr(srsk_mod, "fred_with_keyless_fallback", _fallback)
    fake.seen = seen  # type: ignore[attr-defined]
    return fake


def test_unkeyed_adapter_uses_the_keyless_csv(keyless: _KeylessCSV) -> None:
    fn = SRSKFunction(FunctionDeps(worldbank=_NoWorldBank(), fred=_UnkeyedAdapter()))
    out = asyncio.run(fn.execute(countries="DE"))
    assert "DGS10" in keyless.calls
    assert out.metadata["ust_10y_pct"] == pytest.approx(5.0)  # latest daily print
    assert out.metadata["ust_10y_as_of"] == "2026-10-30"


def test_differential_uses_the_same_month_ust_average(keyless: _KeylessCSV) -> None:
    fn = SRSKFunction(FunctionDeps(worldbank=_NoWorldBank(), fred=_UnkeyedAdapter()))
    out = asyncio.run(fn.execute(countries="DE"))
    row = {r["country"]: r for r in out.data["rows"]}["DE"]
    # September sovereign 6.5 minus the September DGS10 average 4.0, not today's 5.0.
    assert row["proxy_spread_pct"] == pytest.approx(2.5)
    assert row["fred_10y_pct"] == pytest.approx(6.5)
    assert row["ust_10y_same_month_pct"] == pytest.approx(4.0)
    assert row["fred_as_of"] == "2026-09-01"


def test_month_without_ust_data_gives_no_differential(monkeypatch) -> None:
    class _GapCSV(_KeylessCSV):
        async def series(self, series_id: str):
            if series_id == "DGS10":
                idx = pd.date_range("2026-10-01", "2026-10-30", freq="B")
                return pd.DataFrame({"value": [5.0] * len(idx)}, index=idx)
            return pd.DataFrame({"value": [6.5]}, index=pd.DatetimeIndex(["2026-09-01"]))

    monkeypatch.setattr(srsk_mod, "fred_with_keyless_fallback", lambda fred, client=None: _GapCSV())
    fn = SRSKFunction(FunctionDeps(worldbank=_NoWorldBank(), fred=_UnkeyedAdapter()))
    out = asyncio.run(fn.execute(countries="DE"))
    # No World Bank macro and no same-month UST leg: nothing is priced.
    assert all(r.get("proxy_spread_pct") is None for r in out.data["rows"])
    assert out.data["status"] in {"empty", "provider_unavailable"}
    assert any("no DGS10 observations" in w for w in out.warnings)


def test_yield_below_ust_is_not_a_credit_spread(monkeypatch) -> None:
    """A sovereign yielding less than the same-month UST (DE, JP) must not give a
    negative spread or a negative default probability."""
    class _LowCSV(_KeylessCSV):
        async def series(self, series_id: str):
            if series_id == "DGS10":
                idx = pd.date_range("2026-09-01", "2026-09-30", freq="B")
                return pd.DataFrame({"value": [5.0] * len(idx)}, index=idx)
            return pd.DataFrame({"value": [3.5]}, index=pd.DatetimeIndex(["2026-09-01"]))

    monkeypatch.setattr(srsk_mod, "fred_with_keyless_fallback", lambda fred, client=None: _LowCSV())
    out = asyncio.run(SRSKFunction(FunctionDeps(worldbank=_NoWorldBank(), fred=_UnkeyedAdapter())).execute(countries="DE"))
    for row in out.data["rows"]:
        assert row.get("pd_1y_pct") is None or row["pd_1y_pct"] >= 0
        assert row.get("proxy_spread_pct") is None or row["proxy_spread_pct"] >= 0
    assert any("not used as a credit spread" in w for w in out.warnings)
