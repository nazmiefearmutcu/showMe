"""De-garbage regression tests for SRSK (Sovereign Risk).

SRSK used to return a key-gated ``provider_unavailable`` (FRED) or a flat
identical 3.25% proxy spread for every sovereign.  It now builds a real,
keyless composite from World Bank Open Data fundamentals and a yield-style
CDS proxy.  These tests:

* assert the offline graceful shape (``provider_unavailable`` with honest
  warning + methodology) when the network is mocked down, and
* exercise the live path with a mocked keyless HTTP client so the test is
  fast and deterministic, proving rows carry REAL per-country macro values
  (not the old flat constant) and a Hull-consistent PD.

A best-effort live-network smoke is included but SKIPS cleanly offline.
"""

from __future__ import annotations

import asyncio

import pytest

from showme.engine.functions.bond.srsk import (
    SRSKFunction,
    _latest_wb_value,
    _leg_score,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _make_handler() -> SRSKFunction:
    """Construct the handler, tolerating either zero-arg or deps-arg ctors."""
    try:
        return SRSKFunction()  # type: ignore[call-arg]
    except TypeError:
        class _Deps:
            fred = None
            worldbank = None

        try:
            return SRSKFunction(_Deps())  # type: ignore[call-arg]
        except TypeError:
            h = SRSKFunction.__new__(SRSKFunction)
            h.deps = _Deps()  # type: ignore[attr-defined]
            return h


def _run(coro):
    return asyncio.run(coro)


def _ensure_deps_have_attrs(handler: SRSKFunction) -> None:
    """Guarantee handler.deps exposes the attrs the function reads."""
    deps = getattr(handler, "deps", None)
    if deps is None:
        class _Deps:
            fred = None
            worldbank = None

        handler.deps = _Deps()  # type: ignore[attr-defined]
        return
    if not hasattr(deps, "fred"):
        try:
            deps.fred = None  # type: ignore[attr-defined]
        except Exception:
            pass
    if not hasattr(deps, "worldbank"):
        try:
            deps.worldbank = None  # type: ignore[attr-defined]
        except Exception:
            pass


# ---------------------------------------------------------------------------
# pure-function unit coverage (no network, always runs)
# ---------------------------------------------------------------------------
def test_latest_wb_value_picks_newest_non_null():
    payload = [
        {"page": 1},
        [
            {"value": None, "date": "2024"},
            {"value": "118.7", "date": "2023"},
            {"value": "110.0", "date": "2022"},
        ],
    ]
    val, date = _latest_wb_value(payload)
    assert val == pytest.approx(118.7)
    assert date == "2023"


def test_latest_wb_value_handles_garbage():
    assert _latest_wb_value(None) == (None, None)
    assert _latest_wb_value([{"message": "bad"}]) == (None, None)
    assert _latest_wb_value(["meta", []]) == (None, None)


def test_leg_score_direction_and_clamp():
    # debt/GDP: higher = riskier (not inverted)
    assert _leg_score(160.0, low=20.0, high=160.0, invert=False) == 100.0
    assert _leg_score(20.0, low=20.0, high=160.0, invert=False) == 0.0
    # reserves: higher = safer (inverted)
    assert _leg_score(12.0, low=1.0, high=12.0, invert=True) == 0.0
    assert _leg_score(1.0, low=1.0, high=12.0, invert=True) == 100.0
    # clamps beyond bounds
    assert _leg_score(500.0, low=20.0, high=160.0, invert=False) == 100.0
    assert _leg_score(None, low=0.0, high=1.0, invert=False) is None


# ---------------------------------------------------------------------------
# live path with a mocked keyless HTTP client (fast, deterministic)
# ---------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeClient:
    """Returns distinct macro values per country so rows must differ."""

    # country ISO3 -> {indicator: latest_value}
    _DATA = {
        "TUR": {
            "GC.DOD.TOTL.GD.ZS": 34.0,
            "FI.RES.TOTL.MO": 3.5,
            "BN.CAB.XOKA.GD.ZS": -4.5,
            "FP.CPI.TOTL.ZG": 53.0,
        },
        "USA": {
            "GC.DOD.TOTL.GD.ZS": 121.0,
            "FI.RES.TOTL.MO": 0.6,
            "BN.CAB.XOKA.GD.ZS": -3.0,
            "FP.CPI.TOTL.ZG": 3.4,
        },
        "DEU": {
            "GC.DOD.TOTL.GD.ZS": 64.0,
            "FI.RES.TOTL.MO": 1.8,
            "BN.CAB.XOKA.GD.ZS": 6.0,
            "FP.CPI.TOTL.ZG": 2.3,
        },
    }

    def get(self, url, params=None, timeout=None):  # noqa: ARG002
        iso3 = None
        for code in self._DATA:
            if f"/country/{code}/" in url:
                iso3 = code
                break
        indicator = url.rsplit("/indicator/", 1)[-1]
        val = self._DATA.get(iso3, {}).get(indicator)
        body = [
            {"page": 1, "total": 1},
            [{"value": val, "date": "2023", "countryiso3code": iso3}],
        ]
        return _FakeResponse(body)


def test_srsk_live_path_returns_real_distinct_rows(monkeypatch):
    handler = _make_handler()
    _ensure_deps_have_attrs(handler)
    # No FRED key -> pure World Bank composite path.
    handler.deps.fred = None  # type: ignore[attr-defined]
    handler.deps.worldbank = None  # type: ignore[attr-defined]

    import showme.providers._http as _http_mod

    monkeypatch.setattr(_http_mod, "get_client", lambda: _FakeClient(), raising=False)

    result = _run(handler.execute(countries=["TR", "US", "DE"]))
    data = result.data

    assert data["status"] == "ok"
    assert "worldbank" in result.sources
    assert data["methodology"]
    assert isinstance(data.get("field_dictionary"), dict) and data["field_dictionary"]

    rows = data["rows"]
    assert len(rows) == 3

    # Rows carry REAL per-country macro values, not the old flat 3.25 constant.
    by_country = {r["country"]: r for r in rows}
    assert by_country["TR"]["debt_to_gdp"] == pytest.approx(34.0)
    assert by_country["US"]["debt_to_gdp"] == pytest.approx(121.0)
    assert by_country["DE"]["inflation_pct"] == pytest.approx(2.3)

    # Risk scores must differ across countries (no flat identical signal).
    scores = {r["country"]: r["risk_score"] for r in rows}
    assert len(set(scores.values())) >= 2, scores

    # Proxy spreads are no longer the old flat 3.25 for every row.
    spreads = [r["proxy_spread_pct"] for r in rows]
    assert not all(abs(s - 3.25) < 1e-9 for s in spreads)

    # Hull identity holds: pd_1y_pct == spread / (1 - recovery).
    for r in rows:
        expected = r["proxy_spread_pct"] / (1 - r["recovery"])
        assert r["pd_1y_pct"] == pytest.approx(expected, rel=1e-9, abs=1e-9)

    # Card schema slots present for the panel.
    cards = data["cards"]
    assert cards["highest_pd_country"] in {"TR", "US", "DE"}
    assert cards["highest_pd"] is not None


def test_srsk_live_path_with_async_get_client(monkeypatch):
    """Production ``get_client`` is async; the handler must await it."""
    handler = _make_handler()
    _ensure_deps_have_attrs(handler)
    handler.deps.fred = None  # type: ignore[attr-defined]
    handler.deps.worldbank = None  # type: ignore[attr-defined]

    import showme.providers._http as _http_mod

    async def _async_get_client():
        return _FakeClient()

    monkeypatch.setattr(_http_mod, "get_client", _async_get_client, raising=False)

    result = _run(handler.execute(countries=["TR", "US"]))
    data = result.data
    assert data["status"] == "ok", data
    assert "worldbank" in result.sources
    by_country = {r["country"]: r for r in data["rows"]}
    assert by_country["TR"]["debt_to_gdp"] == pytest.approx(34.0)
    assert by_country["US"]["debt_to_gdp"] == pytest.approx(121.0)


def test_srsk_provider_unavailable_on_network_outage(monkeypatch):
    handler = _make_handler()
    _ensure_deps_have_attrs(handler)
    handler.deps.fred = None  # type: ignore[attr-defined]
    handler.deps.worldbank = None  # type: ignore[attr-defined]

    import showme.providers._http as _http_mod

    class _DeadClient:
        def get(self, *a, **k):  # noqa: ARG002
            raise OSError("network down")

    monkeypatch.setattr(_http_mod, "get_client", lambda: _DeadClient(), raising=False)

    result = _run(handler.execute(countries=["TR", "US"]))
    data = result.data
    assert data["status"] == "provider_unavailable"
    assert data["rows"] == []
    assert data["methodology"]
    assert result.warnings  # honest warning surfaced
    assert any("worldbank" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# best-effort live smoke — SKIPS cleanly offline
# ---------------------------------------------------------------------------
def test_srsk_real_worldbank_smoke():
    handler = _make_handler()
    _ensure_deps_have_attrs(handler)
    handler.deps.fred = None  # type: ignore[attr-defined]
    handler.deps.worldbank = None  # type: ignore[attr-defined]
    try:
        result = _run(handler.execute(countries=["TR", "DE"]))
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"live World Bank fetch failed: {exc}")

    data = result.data
    if data["status"] != "ok":
        # Genuine outage path is acceptable and must be honest.
        assert data["status"] == "provider_unavailable"
        assert data["rows"] == []
        pytest.skip("World Bank unreachable in this environment")

    rows = data["rows"]
    assert rows, "ok status must carry rows"
    # At least one country returned a real (non-None) macro leg.
    assert any(
        r.get("debt_to_gdp") is not None
        or r.get("inflation_pct") is not None
        or r.get("reserves_months") is not None
        for r in rows
    )
    assert data["methodology"]
