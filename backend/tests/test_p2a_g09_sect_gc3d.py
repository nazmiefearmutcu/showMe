"""P2A-G09 regression tests: SECT missing-price and model-period honesty, GC3D honesty."""

from __future__ import annotations

import asyncio


def _run(coro):
    return asyncio.run(coro)


class _GoodQuote:
    last = 101.0
    close_prev = 100.0
    high_24h = 102.0
    low_24h = 99.0


class _NoLastQuote:
    last = None
    close_prev = 100.0
    high_24h = None
    low_24h = None


class _MixedYf:
    """XLK has a real price; every other sector has a previous close but no last."""

    async def fetch(self, request, *a, **kw):
        return _GoodQuote() if request.instrument.symbol == "XLK" else _NoLastQuote()


def test_sect_missing_last_price_is_not_a_minus_100_live_move() -> None:
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.screen.sect import SECTFunction

    out = _run(SECTFunction(FunctionDeps(yfinance=_MixedYf())).execute(period="1D", live=True))
    assert out.data["status"] == "ok"
    rows = {r["etf"]: r for r in out.data["rows"]}
    assert rows["XLK"]["quote_type"] == "live"
    assert abs(rows["XLK"]["change_pct"] - 1.0) < 1e-6
    lf = rows["XLF"]
    assert lf["last"] is None
    assert lf["change_pct"] is None, lf
    assert lf["quote_type"] == "unavailable", lf
    assert lf["change_pct_period"] is None, lf


def test_sect_model_mtd_has_no_fabricated_period_change() -> None:
    """Model mode only models 1D. MTD/QTD/YTD must not be the 1D value times a constant."""
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.screen.sect import SECTFunction

    out = _run(SECTFunction(FunctionDeps()).execute(period="YTD"))
    assert out.data["status"] == "model"
    assert all(r["change_pct"] is None for r in out.data["rows"]), out.data["rows"][:2]
    one_day = _run(SECTFunction(FunctionDeps()).execute(period="1D"))
    assert all(r["change_pct"] is not None for r in one_day.data["rows"])


# ── GC3D ────────────────────────────────────────────────────────────────

from datetime import datetime, timedelta, timezone  # noqa: E402

import pytest  # noqa: E402


class _CsvClient:
    """Injected FRED CSV client: every series answers with the same 3-day CSV, and records calls."""

    def __init__(self, boom: bool = False):
        self.calls: list[str] = []
        self._boom = boom

    async def get(self, url, timeout=None):
        self.calls.append(url)
        if self._boom:
            raise RuntimeError("offline")
        today = datetime.now(timezone.utc).date()
        text = "observation_date,value\n" + "\n".join(
            f"{today - timedelta(days=d)},4.10" for d in (2, 1, 0)
        )

        class _Resp:
            def __init__(self, t):
                self.text = t

            def raise_for_status(self):
                return None

        return _Resp(text)


@pytest.fixture
def _fresh_fred_cache():
    from showme.engine.functions._fred_csv import reset_fred_csv_cache

    reset_fred_csv_cache()
    yield
    reset_fred_csv_cache()


def _gc3d(client):
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.bond.gc3d import GC3DFunctionLive

    fn = GC3DFunctionLive(FunctionDeps())
    fn._http_client = client
    return fn


def test_gc3d_honours_requested_tenors(_fresh_fred_cache) -> None:
    out = _run(_gc3d(_CsvClient()).execute(tenors=["3M", "30Y"], days=90))
    assert out.data["tenors"] == ["3M", "30Y"]
    assert {p["tenor"] for p in out.data["surface"]} == {"3M", "30Y"}


def test_gc3d_default_tenors_match_seed_default(_fresh_fred_cache) -> None:
    from showme.manifest.seeds.gc3d_seed import gc3d

    seed_default = gc3d.defaults["tenors"]
    out = _run(_gc3d(_CsvClient()).execute())
    assert out.data["tenors"] == seed_default


def test_gc3d_unsupported_country_is_input_error_without_fetch(_fresh_fred_cache) -> None:
    client = _CsvClient()
    out = _run(_gc3d(client).execute(country="DE"))
    assert out.data["status"] == "input_error"
    assert out.sources == []
    assert client.calls == [], "no FRED request may be made for an unsupported country"
    assert "surface" not in out.data


def test_gc3d_template_span_is_reported_truthfully(_fresh_fred_cache) -> None:
    out = _run(_gc3d(_CsvClient()).execute(reference=True, days=365))
    assert out.sources == ["yield_curve_model"]
    assert out.data["summary"]["days"] == 45, out.data["summary"]
    assert any("365-day look-back is not applied" in w for w in out.warnings), out.warnings


def test_gc3d_template_fallback_reports_span_when_live_fails(_fresh_fred_cache) -> None:
    out = _run(_gc3d(_CsvClient(boom=True)).execute(days=365))
    assert out.sources == ["yield_curve_model"]
    assert out.data["summary"]["days"] == 45
    assert any("365-day look-back" in w for w in out.warnings)


def test_gc3d_semantic_tests_use_declared_inputs_only() -> None:
    """The seed's semantic test inputs must name real inputs: a stale key such as
    ``live_curve`` (removed) would silently skip the path the test describes."""
    from showme.manifest.seeds.gc3d_seed import gc3d

    declared = {spec.name for spec in gc3d.inputs}
    for test in gc3d.semantic_tests:
        unknown = set(test.inputs) - declared
        assert not unknown, f"{test.name} uses undeclared inputs {sorted(unknown)}"


def test_gc3d_template_semantic_test_switches_on_reference() -> None:
    from showme.manifest.seeds.gc3d_seed import gc3d

    template = next(t for t in gc3d.semantic_tests if t.name == "gc3d_template_dates_are_rolling")
    assert template.inputs == {"reference": True}


def test_gc3d_seed_does_not_advertise_3d_surface() -> None:
    """GC3D renders a date x tenor grid, not a 3D structure: the seed must not say so."""
    import re

    from showme.manifest.seeds.gc3d_seed import gc3d

    for test in gc3d.semantic_tests:
        assert not re.search(r"\b3d\b", test.name.lower()), test.name
        assert not re.search(r"\b3d\b", test.description.lower()), test.description


class _CsvClientSkipping(_CsvClient):
    """Like _CsvClient, but the listed FRED series ids fail (network error)."""

    def __init__(self, skip_ids: tuple[str, ...]):
        super().__init__()
        self._skip = skip_ids

    async def get(self, url, timeout=None):
        if any(f"id={sid}" in url for sid in self._skip):
            self.calls.append(url)
            raise RuntimeError("series unavailable")
        return await super().get(url, timeout=timeout)


def test_gc3d_reports_requested_tenor_that_fred_did_not_return(_fresh_fred_cache) -> None:
    """A selected tenor whose FRED series fails must not vanish silently."""
    out = _run(_gc3d(_CsvClientSkipping(("DGS30",))).execute(tenors=["3M", "30Y"], days=90))
    assert out.sources == ["fred"]
    assert out.data["tenors"] == ["3M"]
    assert {p["tenor"] for p in out.data["surface"]} == {"3M"}
    assert out.data["missing_tenors"] == ["30Y"], out.data
    assert any("30Y" in w for w in out.warnings), out.warnings


def test_gc3d_no_missing_tenors_when_every_requested_series_returns(_fresh_fred_cache) -> None:
    out = _run(_gc3d(_CsvClient()).execute(tenors=["3M", "30Y"], days=90))
    assert out.data["missing_tenors"] == []
    assert not any("no observations" in w for w in out.warnings), out.warnings
