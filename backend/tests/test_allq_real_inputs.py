"""ALLQ real-input regression tests (wc1-g05).

Offline: every network dependency is an injected fake or a patched client.

* ALLQ#1 — the FiscalData average coupon must never be used as a yield.
* ALLQ#2 — the tenor must drive the reference price (no 10Y fallback).
* ALLQ#3 — the keyless Treasury curve is requested from the year-scoped
  CSV endpoint (the bare ``/all`` form returns HTTP 404 upstream).
* ALLQ#4 — ladder rows are modeled from one anchor: never live_official,
  quote_time is the observation date, sources carry a model marker.
* ALLQ#5 — an explicit operator ``mid`` is honoured as a labelled override.
* ALLQ#6 — methodology text and manifest semantic tests match the code.
* ALLQ#7 — non-sovereign BOND symbols never take a share price as a mid.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument

_CONFIG_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/all"
)

_CURVE_CSV = (
    "Date,\"1 Mo\",\"2 Mo\",\"3 Mo\",\"6 Mo\",\"1 Yr\",\"2 Yr\",\"3 Yr\",\"5 Yr\",\"7 Yr\",\"10 Yr\",\"20 Yr\",\"30 Yr\"\n"
    "11/05/2026,4.00,4.10,4.17,4.20,4.30,4.49,4.57,4.62,4.72,4.84,5.27,5.24\n"
    "11/06/2026,4.02,4.15,4.19,4.23,4.33,4.51,4.59,4.64,4.74,4.86,5.29,5.26\n"
)


def _ref_price(yield_pct: float, years: float, coupon_pct: float = 4.0) -> float:
    """Independent reference: exact cash-flow price of a semi-annual bond."""
    if years <= 1.0:
        return 100.0 / (1.0 + yield_pct / 100.0 * years)
    freq = 2
    n = round(years * freq)
    r = yield_pct / 100.0 / freq
    c = coupon_pct / freq
    return c * (1.0 - (1.0 + r) ** -n) / r + 100.0 * (1.0 + r) ** -n


class _FakeCurve:
    """ustreasury-shaped adapter with a date-indexed par-yield frame."""

    def __init__(self, frame: pd.DataFrame | None = None, boom: bool = False):
        self.frame = frame if frame is not None else pd.DataFrame(
            [{"2 Yr": 4.51, "10 Yr": 4.86}], index=pd.to_datetime(["2026-11-06"])
        )
        self.boom = boom
        self.calls = 0

    async def yield_curve(self) -> pd.DataFrame:
        self.calls += 1
        if self.boom:
            raise RuntimeError("treasury csv down")
        return self.frame


class _FakeYF:
    def __init__(self, price: float):
        self.price = price
        self.calls = 0

    async def fetch_quote(self, symbol: str) -> dict[str, Any]:
        self.calls += 1
        return {"last_price": self.price}


class _FakeResp:
    def __init__(self, text: str, status: int = 200):
        self.text = text
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        import json

        return json.loads(self.text)


class _RecordingHttp:
    def __init__(self, responses: dict[str, _FakeResp] | None = None, default: _FakeResp | None = None):
        self.responses = responses or {}
        self.default = default
        self.urls: list[str] = []

    async def get(self, url: str, params: dict[str, Any] | None = None) -> _FakeResp:
        self.urls.append(url)
        if url in self.responses:
            return self.responses[url]
        if self.default is None:
            raise RuntimeError(f"unexpected request {url}")
        return self.default


def _bond(symbol: str) -> Instrument:
    return Instrument(symbol=symbol, asset_class=AssetClass.BOND)


def _allq(deps: FunctionDeps | None = None):
    from showme.engine.functions.bond._stubs import ALLQFunction

    return ALLQFunction(deps) if deps is not None else ALLQFunction()


# ─────────────────────────────────────────────────────────────────────────
# ALLQ#3 — keyless Treasury adapter requests the year-scoped CSV
# ─────────────────────────────────────────────────────────────────────────


def test_allq3_ustreasury_adapter_requests_year_scoped_csv() -> None:
    from showme.engine.data_sources.bond.ustreasury_adapter import USTreasuryAdapter

    adapter = USTreasuryAdapter({"base_url": _CONFIG_URL})
    http = _RecordingHttp(default=_FakeResp(_CURVE_CSV))

    async def _client() -> _RecordingHttp:
        return http

    adapter._client_ = _client  # type: ignore[method-assign]
    frame = asyncio.run(adapter.yield_curve())

    year = datetime.now(timezone.utc).year
    assert http.urls[0].endswith(f"/daily-treasury-rates.csv/{year}/all")
    assert float(frame["10 Yr"].iloc[-1]) == 4.86


def test_allq3_ustreasury_adapter_falls_back_to_previous_year_when_empty() -> None:
    from showme.engine.data_sources.bond.ustreasury_adapter import USTreasuryAdapter

    year = datetime.now(timezone.utc).year
    adapter = USTreasuryAdapter({"base_url": _CONFIG_URL})
    root = _CONFIG_URL[: -len("/all")]
    http = _RecordingHttp(
        responses={
            f"{root}/{year}/all": _FakeResp("Date,\"10 Yr\"\n"),
            f"{root}/{year - 1}/all": _FakeResp(_CURVE_CSV),
        }
    )

    async def _client() -> _RecordingHttp:
        return http

    adapter._client_ = _client  # type: ignore[method-assign]
    frame = asyncio.run(adapter.yield_curve())

    assert http.urls == [f"{root}/{year}/all", f"{root}/{year - 1}/all"]
    assert float(frame["10 Yr"].iloc[-1]) == 4.86


# ─────────────────────────────────────────────────────────────────────────
# ALLQ#1 / ALLQ#2 — FiscalData average coupon is never a yield
# ─────────────────────────────────────────────────────────────────────────


def test_allq1_fiscaldata_average_coupon_is_not_priced_as_yield(monkeypatch) -> None:
    """The FiscalData type average (3.399% coupon) must not become a mid.

    Red on the old code: the handler returned status ok with mid 105.78
    derived from treating the average coupon as a yield.
    """
    from showme.engine.functions.bond import _stubs

    payload = {
        "data": [
            {"security_desc": "Treasury Notes", "avg_interest_rate_amt": "3.399", "record_date": "2026-10-31"},
        ]
    }

    async def _fake_client() -> _RecordingHttp:
        return _RecordingHttp(default=_FakeResp(__import__("json").dumps(payload)))

    monkeypatch.setattr(_stubs, "get_client", _fake_client)
    res = asyncio.run(_allq().execute(instrument=_bond("US10Y")))

    assert res.data["status"] == "provider_unavailable"
    assert res.data["rows"] == []
    assert "treasury_fiscaldata" not in res.sources


def test_allq2_tenor_drives_the_reference_price() -> None:
    """US2Y and US10Y must price differently, using the tenor's own years.

    Expected mid is the exact cash-flow price of a semi-annual reference
    bond with a labelled 4% coupon, discounted at the tenor's par yield.
    Red on the old code: US10Y priced 91.73 by a linear approximation.
    """
    curve = _FakeCurve()
    fn = _allq(FunctionDeps(ustreasury=curve))
    two = asyncio.run(fn.execute(instrument=_bond("US2Y")))
    ten = asyncio.run(fn.execute(instrument=_bond("US10Y")))

    assert two.data["status"] == "ok" and ten.data["status"] == "ok"
    assert two.data["summary"]["mid"] != ten.data["summary"]["mid"]
    assert abs(ten.data["summary"]["mid"] - round(_ref_price(4.86, 10.0), 6)) < 0.01
    assert abs(two.data["summary"]["mid"] - round(_ref_price(4.51, 2.0), 6)) < 0.01


def test_allq2_unmapped_sovereign_tenor_is_not_substituted_with_us_average(monkeypatch) -> None:
    """DE10Y has no keyless curve here; it must not be priced off a US type average."""
    from showme.engine.functions.bond import _stubs

    called = {"n": 0}

    async def _boom_client() -> _RecordingHttp:
        called["n"] += 1
        return _RecordingHttp(default=_FakeResp("{}"))

    monkeypatch.setattr(_stubs, "get_client", _boom_client)
    res = asyncio.run(_allq(FunctionDeps(ustreasury=_FakeCurve())).execute(instrument=_bond("DE10Y")))

    assert res.data["status"] == "provider_unavailable"
    assert called["n"] == 0


# ─────────────────────────────────────────────────────────────────────────
# ALLQ#4 — modeled ladder is labelled as modeled, dated to the observation
# ─────────────────────────────────────────────────────────────────────────


def test_allq4_ladder_is_modeled_and_dated_to_the_observation() -> None:
    from showme import server

    res = asyncio.run(_allq(FunctionDeps(ustreasury=_FakeCurve())).execute(instrument=_bond("US10Y")))
    rows = res.data["rows"]
    assert len(rows) == 3
    # Red on the old code: data_mode was live_official and quote_time was server now.
    assert res.metadata["data_mode"] == "modeled"
    assert all(r["quote_time"] == "2026-11-06T00:00:00+00:00" for r in rows)
    assert res.data["summary"]["as_of"] == "2026-11-06"
    assert res.metadata["as_of"] == "2026-11-06"
    assert "allq_ladder_model" in res.sources
    body = server.enforce_live_or_label_synthetic("ALLQ", {}, res.to_dict())
    assert body["data_state"] == "model"


# ─────────────────────────────────────────────────────────────────────────
# ALLQ#5 — an explicit operator mid is honoured as a labelled override
# ─────────────────────────────────────────────────────────────────────────


def test_allq5_explicit_mid_overrides_live_anchor() -> None:
    res = asyncio.run(
        _allq(FunctionDeps(ustreasury=_FakeCurve())).execute(instrument=_bond("US10Y"), mid=99.5)
    )
    # Red on the old code: the live anchor (91.73) silently won over mid=99.5.
    assert res.data["summary"]["mid"] == 99.5
    assert res.sources[0] == "user_input"
    assert res.metadata["data_mode"] == "user_input"
    assert any("overrides" in w for w in res.warnings)


# ─────────────────────────────────────────────────────────────────────────
# ALLQ#6 — methodology and manifest contract match the implementation
# ─────────────────────────────────────────────────────────────────────────


def test_allq6_methodology_matches_implemented_formula() -> None:
    from showme.engine.functions.bond._stubs import ALLQFunction

    text = ALLQFunction._METHODOLOGY
    assert "1/(1+y)" not in text  # the old help text described a formula the code did not use
    assert "4% coupon" in text
    assert "exact semi-annual cash flows" in text


def test_allq6_manifest_semantic_tests_match_emitted_source_mode() -> None:
    from showme.manifest.seeds.allq_seed import allq

    assertions = [a for t in allq.semantic_tests for a in t.assertions]
    assert "source_mode_equals_trace_proxy_model" not in assertions
    assert "source_mode_equals_indicative_anchored_to_real_reference" in assertions
    assert "trace_proxy_model" not in allq.methodology
    assert "mid" not in allq.defaults  # a 99.75 placeholder default would silently override the live anchor


# ─────────────────────────────────────────────────────────────────────────
# ALLQ#7 — non-Treasury BOND symbols never take a share price as a mid
# ─────────────────────────────────────────────────────────────────────────


def test_allq7_non_treasury_bond_symbol_never_uses_share_price() -> None:
    yf = _FakeYF(81.92)
    res = asyncio.run(_allq(FunctionDeps(yfinance=yf)).execute(instrument=_bond("TLT")))
    # Red on the old code: the yfinance last price (81.92) became the bond mid.
    assert res.data["status"] == "provider_unavailable"
    assert yf.calls == 0
    assert res.sources == []
    assert res.data["rows"] == []


# ─────────────────────────────────────────────────────────────────────────
# ALLQ#1 (labelling) — bill tenors are not priced off a 4% coupon
# ─────────────────────────────────────────────────────────────────────────


def test_allq1_bill_tenor_reference_is_zero_coupon_not_4pct_coupon() -> None:
    """US1M prices by zero-coupon simple discount, so no coupon is used.

    The summary and the row reference must not claim a 4% coupon reference bond,
    and reference_coupon_pct must be null for bill tenors.
    Red on the old code: summary said 4% coupon for every tenor.
    """
    frame = pd.DataFrame([{"1 Mo": 4.02, "10 Yr": 4.86}], index=pd.to_datetime(["2026-11-06"]))
    res = asyncio.run(_allq(FunctionDeps(ustreasury=_FakeCurve(frame))).execute(instrument=_bond("US1M")))

    assert res.data["status"] == "ok"
    summary = res.data["summary"]
    assert summary["reference_coupon_pct"] is None
    assert "zero-coupon simple discount" in summary["reference"]
    assert "4% coupon" not in summary["reference"]
    assert all("4% coupon" not in r["reference"] for r in res.data["rows"])
    assert all("zero-coupon simple discount" in r["reference"] for r in res.data["rows"])
    assert abs(summary["mid"] - round(_ref_price(4.02, 1 / 12), 4)) < 0.01


def test_allq1_coupon_tenor_reference_still_discloses_4pct_coupon() -> None:
    res = asyncio.run(_allq(FunctionDeps(ustreasury=_FakeCurve())).execute(instrument=_bond("US10Y")))

    assert res.data["summary"]["reference_coupon_pct"] == 4.0
    assert "4% coupon" in res.data["summary"]["reference"]
    assert "zero-coupon" not in res.data["summary"]["reference"]
