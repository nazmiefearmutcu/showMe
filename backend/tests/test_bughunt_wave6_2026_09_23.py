"""Wave-6 bug-hunt fix pins (py-func-macro territory, 2026-09-23).

Regression tests for the fixes shipped in the FIX phase of hunt-06:

* HNT-01  PEOP live search runs off the event loop (asyncio.to_thread)
* HNT-02  REBA live rows without a quote are price_unavailable, not qty=notional
* HNT-03  fred_with_keyless_fallback prefers only a *keyed* adapter
* HNT-04  CORR live mode drops unavailable symbols instead of synthesizing
* HNT-05  PORT fetches position quotes concurrently
* HNT-06  WIRP caps the ^IRX refinement at the remaining function budget
* HNT-07  REGM keyed FRED path reads the returned DataFrame directly
* HNT-08  MGN upsert/delete without a name returns a clean input_error
* HNT-09  NALRT skips the deep gdelt leg once the budget is exhausted
* HNT-10  GMM splits comma-separated country strings; seed drops dead inputs
* HNT-11  REBA seed input names match the handler (targets / min_drift_pct)
* HNT-13  ECO country filter drops countryless rows; no "US" default label
* HNT-14  CalendarRegistry honours exchange_calendars holidays (skip if absent)
* HNT-15  PVAR reports coverage_pct + warning for uncovered positions
* HNT-16  ACCT marks crypto positions with live quotes (PORT pattern)
* HNT-17  PORT_WHATIF uses a unique temp-dir path, never /tmp
* HNT-18  WIRP FOMC calendar exhaustion is honest (rows=[] + warning)
* HNT-20  keyless FRED CSV shim warns when frequency/vintage are ignored
* HNT-21  SOSC crypto base-symbol stripping is suffix-anchored
"""

from __future__ import annotations

import asyncio
import logging
import sys
import tempfile
import threading
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.core.instrument import AssetClass, Instrument  # noqa: E402
from showme.engine.core.quote import Quote, utcnow  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ── HNT-01: PEOP off-loop live search ─────────────────────────────────────


def test_peop_live_search_runs_off_the_event_loop(monkeypatch) -> None:
    from showme.engine.functions.comm import peop as peop_mod
    from showme.engine.services import people_directory as pd
    from showme.engine.services import people_search as ps

    seen_threads: list[threading.Thread] = []

    def _fake_search(query, *, limit=25):
        seen_threads.append(threading.current_thread())
        return {
            "ok": True,
            "items": [{"full_name": "Ada Lovelace", "role": "Mathematician"}],
            "sources": ["wikipedia"],
        }

    monkeypatch.setattr(ps, "search_people", _fake_search)
    monkeypatch.setattr(pd, "search", lambda query, limit=25: [])
    fn = peop_mod.PEOPFunction()
    result = _run(fn.execute(None, action="search", query="ada", limit=5))

    assert result.data["source_mode"] == "wikipedia_live"
    assert result.data["status"] == "ok"
    # The sync (throttled, blocking-HTTP) search must run on a worker
    # thread, never on the event loop thread that serves every pane.
    assert seen_threads, "live search was never invoked"
    assert seen_threads[0] is not threading.main_thread()


# ── HNT-02: REBA price-unavailable rows ───────────────────────────────────


class _RebaPosition:
    def __init__(self, symbol, quantity, avg_cost, asset_class=AssetClass.EQUITY):
        self.instrument = Instrument(symbol=symbol, asset_class=asset_class)
        self.quantity = quantity
        self.avg_cost = avg_cost


class _RebaPortfolio:
    def __init__(self, positions):
        self.positions = positions

    def import_legacy_crypto(self):  # pragma: no cover - not exercised here
        return 0


def test_reba_liquidation_without_quote_is_price_unavailable(monkeypatch) -> None:
    from showme.engine.functions.portfolio import reba as reba_mod

    # FunctionDeps() has no yfinance → every quote is unavailable.
    monkeypatch.setattr(
        reba_mod, "PortfolioState", lambda: _RebaPortfolio([_RebaPosition("BTCUSDT", 0.25, 65_000.0)])
    )
    res = _run(
        reba_mod.REBAFunction(FunctionDeps()).execute(
            targets={"SPY": 1.0}, live_portfolio=True
        )
    )
    liq = res.data["liquidations"]
    assert len(liq) == 1
    row = liq[0]
    # The old `prices.get(sym) or 1` produced SELL 16250 BTC — never again.
    assert row["symbol"] == "BTCUSDT"
    assert row["quantity"] is None
    assert row["price"] is None
    assert row["price_unavailable"] is True
    assert row["notional_delta"] == pytest.approx(-0.25 * 65_000.0)


def test_reba_target_order_without_quote_is_price_unavailable(monkeypatch) -> None:
    from showme.engine.functions.portfolio import reba as reba_mod

    monkeypatch.setattr(
        reba_mod, "PortfolioState", lambda: _RebaPortfolio([_RebaPosition("AAPL", 10.0, 100.0)])
    )
    res = _run(
        reba_mod.REBAFunction(FunctionDeps()).execute(
            targets={"SPY": 1.0}, live_portfolio=True
        )
    )
    orders = [o for o in res.data["orders"] if o["symbol"] == "SPY"]
    assert len(orders) == 1
    order = orders[0]
    # px=0 used to produce a meaningless "SELL 0" row.
    assert order["quantity"] is None
    assert order["price"] is None
    assert order["price_unavailable"] is True
    assert order["action"] == "BUY"  # drift direction is still honest


def test_reba_liquidation_uses_live_crypto_quote(monkeypatch) -> None:
    from showme.engine.functions.portfolio import reba as reba_mod

    class _FakeYf:
        async def fetch(self, request):
            sym = request.instrument.symbol
            if sym == "BTCUSDT":
                assert request.instrument.asset_class == AssetClass.CRYPTO
                return Quote(symbol=sym, timestamp=utcnow(), last=60_000.0)
            return Quote(symbol=sym, timestamp=utcnow(), last=200.0)

    monkeypatch.setattr(
        reba_mod, "PortfolioState", lambda: _RebaPortfolio([_RebaPosition("BTCUSDT", 0.25, 65_000.0)])
    )
    res = _run(
        reba_mod.REBAFunction(FunctionDeps(yfinance=_FakeYf())).execute(
            targets={"SPY": 1.0}, live_portfolio=True
        )
    )
    row = res.data["liquidations"][0]
    # Crypto quotes flow through the yfinance BTC-USD mapping (PORT pattern).
    assert row["quantity"] == pytest.approx(0.25)
    assert row["price"] == pytest.approx(60_000.0)
    assert row["price_unavailable"] is False


# ── HNT-03 / HNT-07 / HNT-20: FRED keyless shim + REGM curve ──────────────


class _FakeResp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class _FakeFredCSVClient:
    """Serves fredgraph.csv payloads keyed off the URL."""

    def __init__(self, dgs10="3.40", dgs2="4.20"):
        self._dgs10 = f"observation_date,value\n2026-09-01,4.00\n2026-09-02,{dgs10}\n"
        self._dgs2 = f"observation_date,value\n2026-09-01,4.00\n2026-09-02,{dgs2}\n"

    async def get(self, url, timeout=None):  # noqa: ANN001 - fake seam
        if "DGS10" in str(url):
            return _FakeResp(self._dgs10)
        if "DGS2" in str(url):
            return _FakeResp(self._dgs2)
        raise AssertionError(f"unexpected FRED series requested: {url}")


class _FakeKeyedFred:
    """FREDAdapter-shaped fake: keyed fetch returns a date-indexed frame."""

    def __init__(self, dgs10, dgs2, api_key="test-key"):
        self.api_key = api_key
        self._data = {"DGS10": dgs10, "DGS2": dgs2}

    async def fetch(self, request):
        if not str(getattr(self, "api_key", "") or "").strip():
            raise RuntimeError("FRED_API_KEY not set")
        sid = request.extra.get("series_id")
        idx = pd.date_range(end="2026-09-20", periods=5, freq="D")
        return pd.DataFrame({"value": self._data[sid]}, index=idx)


def test_regm_keyed_fred_path_computes_curve() -> None:
    """HNT-07: the keyed primary path used `t10.data` (nonexistent) and always
    raised AttributeError; it must read the returned DataFrame directly."""
    from showme.engine.functions.macro.regm import REGMFunction

    fn = REGMFunction(FunctionDeps(fred=_FakeKeyedFred([3.4] * 5, [4.2] * 5)))
    out = _run(fn.execute(symbol="SPY", allow_model=True))
    current = out.data["current"]
    assert current.get("curve") == "INVERTED"
    assert current.get("curve_2s10s_bp") == pytest.approx(-80.0)


def test_regm_keyless_adapter_falls_through_to_csv_shim(monkeypatch) -> None:
    """HNT-03: a wired-but-keyless FRED adapter must not block the CSV shim."""
    from showme.engine.functions._fred_csv import reset_fred_csv_cache
    from showme.engine.functions.macro.regm import REGMFunction

    reset_fred_csv_cache()
    try:
        fn = REGMFunction(FunctionDeps(fred=_FakeKeyedFred([9.9] * 5, [9.9] * 5, api_key="")))
        fn._http_client = _FakeFredCSVClient(dgs10="3.40", dgs2="4.20")
        out = _run(fn.execute(symbol="SPY", allow_model=True))
        current = out.data["current"]
        # The keyed fake would give +570bp; the shim's CSV values give -80bp.
        assert current.get("curve_2s10s_bp") == pytest.approx(-80.0)
        assert current.get("curve") == "INVERTED"
    finally:
        reset_fred_csv_cache()


def test_fred_csv_shim_warns_when_frequency_or_vintage_ignored(caplog) -> None:
    """HNT-20: silently ignoring frequency/vintage breaks the ECST contract."""
    from showme.engine.functions._fred_csv import _KeylessFredCSV, reset_fred_csv_cache

    reset_fred_csv_cache()
    try:
        shim = _KeylessFredCSV(client=_FakeFredCSVClient())
        with caplog.at_level(logging.WARNING, logger="showme.fred_csv"):
            frame = _run(shim.series("DGS10", frequency="monthly", vintage="2020-01-01"))
        assert not frame.empty
        messages = " ".join(rec.getMessage() for rec in caplog.records)
        assert "frequency" in messages and "vintage" in messages
    finally:
        reset_fred_csv_cache()


# ── HNT-04: CORR live honesty ─────────────────────────────────────────────


class _CorrFakeYf:
    def __init__(self, fail=()):
        self._fail = set(fail)

    async def fetch(self, request):
        sym = request.instrument.symbol
        if sym in self._fail:
            raise RuntimeError(f"provider down for {sym}")
        idx = pd.date_range(end="2026-09-20", periods=40, freq="D")
        return pd.DataFrame({"close": [100.0 + i * 0.5 for i in range(40)]}, index=idx)


def test_corr_live_drops_unavailable_symbols_instead_of_synthesizing() -> None:
    from showme.engine.functions.portfolio.corr import CORRFunction

    fn = CORRFunction(FunctionDeps(yfinance=_CorrFakeYf(fail={"QQQ"})))
    res = _run(fn.execute(symbols=["SPY", "QQQ"], live_correlation=True, days=90))

    # The matrix universe shrinks to the symbol with real data...
    assert res.data["symbols"] == ["SPY"]
    assert set(res.data["pearson"]) == {"SPY"}
    # ...and the failed symbol is reported honestly, never fabricated.
    assert res.data["coverage_status"]["QQQ"]["status"] == "dropped_live_unavailable"
    assert res.data["dropped_live_symbols"] == ["QQQ"]
    assert any("live-unavailable" in w for w in res.warnings)


def test_corr_live_total_outage_returns_provider_unavailable_envelope() -> None:
    from showme.engine.functions.portfolio.corr import CORRFunction

    fn = CORRFunction(FunctionDeps(yfinance=_CorrFakeYf(fail={"SPY", "QQQ"})))
    res = _run(fn.execute(symbols=["SPY", "QQQ"], live_correlation=True, days=90))

    assert res.data["status"] == "provider_unavailable"
    assert res.data["rows"] == []
    assert res.data["pearson"] == {}
    assert res.data["next_actions"]
    assert any("no usable price series" in w for w in res.warnings)


def test_corr_model_mode_still_serves_reference_series() -> None:
    from showme.engine.functions.portfolio.corr import CORRFunction

    fn = CORRFunction(FunctionDeps())
    res = _run(fn.execute(symbols=["SPY", "QQQ"], live_correlation=False, days=90))
    assert res.data["symbols"] == ["SPY", "QQQ"]
    assert res.data["impactor"]["options"]["source_mode"] == "computed_reference"


# ── HNT-05: PORT concurrent quotes ────────────────────────────────────────


def test_port_fetches_position_quotes_concurrently(tmp_path) -> None:
    from showme.engine.functions.portfolio.port import PORTFunction
    from showme.engine.portfolio.state import PortfolioPosition, PortfolioState

    portfolio = PortfolioState(tmp_path / "portfolio.json")
    portfolio.positions = [
        PortfolioPosition(Instrument(symbol=s, asset_class=AssetClass.EQUITY), 1.0, 10.0)
        for s in ("AAA", "BBB", "CCC")
    ]

    class _SlowYf:
        async def fetch(self, request):
            await asyncio.sleep(0.3)
            return Quote(symbol=request.instrument.symbol, timestamp=utcnow(), last=100.0)

    fn = PORTFunction(FunctionDeps(yfinance=_SlowYf()))
    started = time.perf_counter()
    result = _run(fn.execute(_portfolio_override=portfolio))
    elapsed = time.perf_counter() - started

    assert all(row["last"] == 100.0 for row in result.data["positions"])
    # Sequential fetching would need >= 3 * 0.3s; the gather must finish well
    # below that (generous margin for CI timer jitter).
    assert elapsed < 0.75, f"quotes were fetched sequentially ({elapsed:.2f}s)"


# ── HNT-06 / HNT-18: WIRP budget + calendar ───────────────────────────────


def _install_wirp_fakes(monkeypatch, fred_values=(4.50, 4.25, 4.33)) -> None:
    import showme.engine.functions.macro.wirp as wirp_mod

    upper, lower, effr = fred_values

    async def _fake_fred(url, timeout=8.0):
        if "DFEDTARU" in url:
            return ("2026-09-10", upper)
        if "DFEDTARL" in url:
            return ("2026-09-10", lower)
        return ("2026-09-10", effr)

    monkeypatch.setattr(wirp_mod, "_fetch_fred_latest", _fake_fred)


def test_wirp_irx_refinement_capped_at_remaining_budget(monkeypatch) -> None:
    import showme.engine.functions.macro.wirp as wirp_mod

    _install_wirp_fakes(monkeypatch)

    async def _slow_irx():
        await asyncio.sleep(2.5)
        return 4.30, "2026-09-10"

    monkeypatch.setattr(wirp_mod, "_fetch_irx_implied_rate", _slow_irx)
    # Fake clock: FRED legs "consumed" 12s of the ~13s budget → IRX gets 1s.
    ticks = iter([1000.0, 1012.0])
    monkeypatch.setattr(
        wirp_mod, "time", types.SimpleNamespace(monotonic=lambda: next(ticks, 1012.0))
    )

    started = time.perf_counter()
    result = _run(wirp_mod.WIRPFunction(FunctionDeps()).execute(central_bank="FED", meetings=2))
    elapsed = time.perf_counter() - started

    # The 2.5s IRX pull must be cancelled at the ~1s remaining budget...
    assert elapsed < 2.2, f"IRX was awaited past the function budget ({elapsed:.2f}s)"
    # ...and WIRP still returns honest FRED-anchored rows.
    assert result.data["rows"], "FRED-anchored rows must survive an IRX timeout"
    assert result.data["source_mode"] == "live_fred_target_no_irx"
    assert any("timed out" in w for w in result.warnings)


def test_wirp_fomc_calendar_exhausted_is_honest(monkeypatch) -> None:
    import showme.engine.functions.macro.wirp as wirp_mod

    _install_wirp_fakes(monkeypatch)
    monkeypatch.setattr(wirp_mod, "_FOMC_CALENDAR_2026", ["2026-01-28", "2026-03-18"])

    result = _run(wirp_mod.WIRPFunction(FunctionDeps()).execute(central_bank="FED", meetings=4))
    assert result.data["rows"] == []
    assert result.data["status"] == "empty"
    # Past dates must not be served as forward meetings — say why instead.
    assert any("calendar exhausted" in w.lower() for w in result.warnings)
    assert any("2026-03-18" in w for w in result.warnings)


# ── HNT-08: MGN input_error ───────────────────────────────────────────────


def test_mgn_upsert_and_delete_require_name() -> None:
    from showme.engine.functions.portfolio.mgn import MGNFunction

    fn = MGNFunction(FunctionDeps())
    upsert = _run(fn.execute(action="upsert", cash=1000))
    assert upsert.data["status"] == "input_error"
    assert upsert.data["missing_fields"] == ["name"]

    delete = _run(fn.execute(action="delete"))
    assert delete.data["status"] == "input_error"
    assert delete.data["missing_fields"] == ["name"]


# ── HNT-09: NALRT budget ──────────────────────────────────────────────────


def test_nalrt_skips_deep_gdelt_once_budget_is_exhausted(monkeypatch) -> None:
    from showme.engine.functions.news import nalrt as nalrt_mod

    class _FakeRss:
        async def fetch(self, request):
            return []

        async def probe_feeds(self, request, timeout=None):
            return []

    class _FakeGdelt:
        def __init__(self):
            self.calls = 0

        async def fetch(self, request):
            self.calls += 1
            return [{"title": "late", "url": "https://x/late"}]

    gdelt = _FakeGdelt()
    # Fake clock: every perf_counter call jumps forward 20s, so `started`
    # lands 20s before the first _remaining() check — the budget reads as
    # exhausted for every stage from the very first one.
    clock = {"t": 100.0}

    def _fake_perf_counter() -> float:
        clock["t"] += 20.0
        return clock["t"]

    monkeypatch.setattr(
        nalrt_mod, "time", types.SimpleNamespace(perf_counter=_fake_perf_counter)
    )
    deps = FunctionDeps(rss=_FakeRss(), gdelt=gdelt)
    fn = nalrt_mod.NewsAlertFunction(deps)
    result = _run(fn.execute(symbol="AAPL", deep=True))

    assert gdelt.calls == 0, "gdelt must not fire once the budget is spent"
    assert any("gdelt: skipped" in w for w in result.warnings)
    assert "gdelt" not in result.sources


# ── HNT-10 / HNT-11: seed ↔ handler contract ──────────────────────────────


def test_gmm_resolves_comma_separated_country_string() -> None:
    from showme.engine.functions.macro.gmm import _resolve_countries

    resolved = _resolve_countries("US,CN")
    assert set(resolved) == {"US", "CN"}
    assert _resolve_countries(" US , cn ") == resolved
    # Single codes and the euro-area proxy keep working.
    assert set(_resolve_countries("EZ")) == {"DE"}


def test_gmm_seed_drops_inputs_the_handler_ignores() -> None:
    from showme.manifest import REGISTRY
    from showme.manifest.seeds import load_seeds

    load_seeds()
    gmm = REGISTRY.get("GMM")
    names = {i.name for i in gmm.inputs}
    assert {"countries", "top_n"} <= names
    assert "window" not in names, "GMM handler never reads `window`"
    assert "categories" not in names, "GMM handler never reads `categories`"
    assert "window" not in gmm.defaults and "categories" not in gmm.defaults


def test_reba_seed_input_names_match_handler() -> None:
    from showme.manifest import REGISTRY
    from showme.manifest.seeds import load_seeds

    load_seeds()
    reba = REGISTRY.get("REBA")
    names = {i.name for i in reba.inputs}
    assert {"targets", "min_drift_pct"} <= names
    assert "target_weights" not in names
    assert "drift_tolerance_pct" not in names
    # The threshold is a fraction in the handler; the default must agree.
    assert reba.defaults["min_drift_pct"] == pytest.approx(0.005)


# ── HNT-13: ECO country filter ────────────────────────────────────────────


def test_eco_country_filter_drops_countryless_rows() -> None:
    from showme.engine.functions.macro import eco as eco_mod

    d1 = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    events = [
        {"country": "US", "event": "CPI YoY", "date": d1, "importance": "high",
         "forecast": "3.1%", "previous": "3.0%"},
        {"country": "", "event": "Mystery Print", "date": d1, "importance": "high"},
    ]
    filtered = eco_mod._normalize_events(events, country="US", importance=None, days=7)
    assert [r["event"] for r in filtered] == ["CPI YoY"]

    unfiltered = eco_mod._normalize_events(events, country=None, importance=None, days=7)
    assert len(unfiltered) == 2
    mystery = next(r for r in unfiltered if r["event"] == "Mystery Print")
    # No fabricated "US" label on a row with no country provenance.
    assert mystery["country"] == ""


# ── HNT-14: calendar holidays ─────────────────────────────────────────────


def test_calendar_registry_respects_exchange_holidays() -> None:
    from showme.engine.reference.calendar_registry import CalendarRegistry

    cal = CalendarRegistry()
    if cal._ec is None:
        pytest.skip("exchange_calendars not installed; weekday-only fallback is pinned elsewhere")

    # 2026-11-26 is Thanksgiving (4th Thursday) — an NYSE holiday on a weekday.
    noon_et = datetime(2026, 11, 26, 17, 0, 0, tzinfo=timezone.utc)
    assert cal.is_open("NYSE", noon_et) is False

    # next_open after Wednesday's close must land on Friday, not the holiday.
    after_wed_close = datetime(2026, 11, 25, 22, 0, 0, tzinfo=timezone.utc)
    nxt = cal.next_open("NYSE", after_wed_close)
    assert nxt is not None
    assert nxt.date().isoformat() == "2026-11-27"


# ── HNT-15: PVAR coverage ─────────────────────────────────────────────────


class _PvarPosition:
    def __init__(self, symbol, quantity, avg_cost):
        self.instrument = Instrument(symbol=symbol, asset_class=AssetClass.EQUITY)
        self.quantity = quantity
        self.avg_cost = avg_cost
        self.account = "main"
        self.currency = "USD"


class _PvarPortfolio:
    def __init__(self, *_args, **_kwargs):
        self.positions = [
            _PvarPosition("AAPL", 10.0, 100.0),
            _PvarPosition("GME", 5.0, 20.0),
        ]

    def import_legacy_crypto(self):
        return 0


def test_pvar_reports_coverage_when_history_missing(monkeypatch) -> None:
    from showme.engine.functions.portfolio import pvar as pvar_mod

    monkeypatch.setattr(pvar_mod, "PortfolioState", _PvarPortfolio)

    def _fake_download(symbol, days, timeout):
        if symbol == "GME":
            return pd.Series(dtype=float), None
        idx = pd.date_range(end="2026-09-20", periods=80, freq="D")
        returns = pd.Series([0.001 * ((i % 7) - 3) for i in range(80)], index=idx)
        return returns, 105.0

    monkeypatch.setattr(pvar_mod, "_download_returns", _fake_download)
    res = _run(pvar_mod.PVARFunction().execute())

    assert res.data["status"] == "ok"
    # VaR dollars cover only the AAPL half of the book — say so.
    assert res.data["coverage_pct"] == pytest.approx(0.5)
    assert res.data["summary"]["coverage_pct"] == pytest.approx(0.5)
    assert any("GME" in w for w in res.warnings)
    assert res.data["positions_analyzed"] == 1


# ── HNT-16: ACCT crypto live quote ────────────────────────────────────────


class _AcctFakeYf:
    def __init__(self, last):
        self._last = last
        self.requested: list[Instrument] = []

    async def fetch(self, request):
        self.requested.append(request.instrument)
        return Quote(symbol=request.instrument.symbol, timestamp=utcnow(), last=self._last)


def test_acct_crypto_position_gets_live_quote(monkeypatch) -> None:
    from showme.engine.functions.portfolio import acct as acct_mod

    class _Portfolio:
        def __init__(self, *_args, **_kwargs):
            self.positions = [
                _PvarPosition("BTCUSDT", 2.0, 50_000.0)
            ]
            for pos in self.positions:
                pos.instrument = Instrument(symbol="BTCUSDT", asset_class=AssetClass.CRYPTO)

        def import_legacy_crypto(self):
            return 0

    monkeypatch.setattr(acct_mod, "PortfolioState", _Portfolio)
    fake = _AcctFakeYf(61_000.0)
    fn = acct_mod.ACCTFunction(FunctionDeps(yfinance=fake))
    res = _run(fn.execute())

    row = res.data["accounts"][0]["positions"][0]
    # The live mark (61k) must win over the stale avg_cost (50k) — same
    # pricing policy as the PORT pane.
    assert row["last"] == 61_000.0
    assert row["market_value"] == 122_000.0
    assert any(i.asset_class == AssetClass.CRYPTO for i in fake.requested)


# ── HNT-17: PORT_WHATIF temp path ─────────────────────────────────────────


def test_port_whatif_uses_unique_temp_path(monkeypatch, tmp_path) -> None:
    from showme.engine.functions.portfolio import _more as more_mod

    captured: list[str] = []

    class _State:
        def __init__(self, path="runtime/portfolio.json"):
            captured.append(str(path))
            self.positions = []
            self.cash = {}

        def import_legacy_crypto(self):
            return 0

    monkeypatch.setattr(more_mod, "PortfolioState", _State)
    fn = more_mod.PORTWhatIfFunction(FunctionDeps())
    instrument = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    _run(fn.execute(instrument=instrument, quantity=1.0, cost=100.0))
    _run(fn.execute(instrument=instrument, quantity=2.0, cost=100.0))

    whatif_paths = [p for p in captured if "_showme_whatif_" in p]
    assert len(whatif_paths) == 2
    # Unique per call (no shared fixed file)...
    assert whatif_paths[0] != whatif_paths[1]
    # ...and rooted in the real temp dir, never a literal /tmp or C:\tmp.
    temp_root = str(Path(tempfile.gettempdir())).lower()
    for path in whatif_paths:
        assert path.lower().startswith(temp_root)
        assert "\\tmp\\_showme_whatif.json" not in path.lower()


# ── HNT-21: SOSC base symbol ──────────────────────────────────────────────


def test_sosc_base_symbol_stripping_is_suffix_anchored(monkeypatch) -> None:
    import httpx

    from showme.engine.data_sources.awareness import AwarenessClient
    from showme.engine.functions.news import sosc as sosc_mod

    captured: list[str] = []

    def _capture(request: httpx.Request) -> httpx.Response:
        if "/sentiment/entity/" in request.url.path:
            captured.append(request.url.path.rsplit("/", 1)[-1])
        raise httpx.ConnectError("offline", request=request)

    fn = sosc_mod.SOSCFunction()
    fn._awareness = AwarenessClient("http://aw.test", transport=httpx.MockTransport(_capture), autostart=False)
    for sym, asset_class in (
        ("BTCUSDT", AssetClass.CRYPTO),
        ("BTC-USD", AssetClass.CRYPTO),
        ("USDJPY", AssetClass.FX),
    ):
        _run(fn.execute(instrument=Instrument(symbol=sym, asset_class=asset_class)))

    # Crypto quote suffixes strip; the FX pair is left intact (the old
    # `.replace("USD", "")` mangled USDJPY into "JPY").
    assert captured == ["BTC", "BTC", "USDJPY"]
