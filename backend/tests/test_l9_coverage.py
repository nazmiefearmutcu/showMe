"""L9 backend coverage wave 2 (2026-09-11 campaign).

Covers the wave-2 backend lane:

* GLCO rows carry REAL daily history as the pane's numeric close series
  (``row.history: number[]``, ascending); history failure leaves rows
  without a fabricated series.
* WCRS computes a real ``change_pct`` from derived USD-leg daily history
  (``leg(quote) / leg(base)``) and emits ``None`` — never a placeholder
  0.0 — when history is unavailable, with the same numeric
  ``row.history`` series for the sparkline.
* FSRC / MOST / WEI default to attempting keyless live quotes; explicit
  falsy ``live`` or ``reference=true`` keeps the labelled reference path;
  a provider miss degrades to a failure-labelled envelope that the
  sanitizer can never stamp live.
* FINRA adapter TTL cache + failure cooldown; DPF degradation stays honest
  (labelled fallback rows, no fabricated ratio).
* ONCH optional keyless companion tiers keep per-row source labels.

All tests are offline: providers are injected fakes.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import httpx
import pandas as pd
import pytest

from showme import server
from showme.engine.core.base_data_source import DataKind, DataSourceError
from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.core.quote import Quote


def _run(coro):
    return asyncio.run(coro)


def _body(result: Any) -> dict[str, Any]:
    return server.enforce_live_or_label_synthetic(result.code, {}, result.to_dict())


# ─────────────────────────────────────────────────────────────────────────
# Shared fakes
# ─────────────────────────────────────────────────────────────────────────


class _FakeQuoteProvider:
    """yfinance-shaped QUOTE provider returning a usable quote per symbol."""

    def __init__(self, empty: bool = False):
        self.empty = empty
        self.calls = 0

    async def fetch(self, request: Any) -> Any:
        self.calls += 1
        if self.empty:
            return None
        symbol = str(getattr(getattr(request, "instrument", None), "symbol", "") or "X")
        return Quote(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            last=100.0,
            close_prev=99.0,
            volume_24h=1_000_000.0,
            high_24h=101.0,
            low_24h=98.0,
        )


class _FakeCommodityQuotes:
    """yfinance-shaped provider for commodity futures QUOTE requests."""

    def __init__(self, last: float = 100.0, close_prev: float = 99.0):
        self.last = last
        self.close_prev = close_prev
        self.calls = 0

    async def fetch(self, request: Any) -> Any:
        self.calls += 1
        return SimpleNamespace(
            last=self.last,
            close_prev=self.close_prev,
            high_24h=self.last * 1.01,
            low_24h=self.last * 0.99,
            open_24h=self.close_prev,
            volume_24h=12_345.0,
            source="yfinance",
            timestamp=datetime.now(timezone.utc),
        )


class _FakeFXHistoryProvider:
    """yfinance-shaped OHLCV provider: raise for unknown pairs."""

    def __init__(self, series: dict[str, list[float]]):
        self.series = series
        self.calls = 0

    async def fetch(self, request: Any) -> Any:
        self.calls += 1
        symbol = str(getattr(getattr(request, "instrument", None), "symbol", "") or "")
        closes = self.series.get(symbol)
        if not closes:
            raise RuntimeError(f"no history for {symbol}")
        index = pd.date_range(end="2026-09-11", periods=len(closes), freq="D", tz="UTC")
        return pd.DataFrame(
            {
                "open": closes,
                "high": closes,
                "low": closes,
                "close": closes,
                "volume": [0.0] * len(closes),
            },
            index=index,
        )


async def _fake_yahoo_history(symbol: str, timeout: float, *, range_: str = "3mo"):
    return [
        {
            "date": f"2026-09-{day:02d}",
            "symbol": symbol,
            "open": 100.0 + day,
            "high": 101.0 + day,
            "low": 99.0 + day,
            "close": 100.5 + day,
            "volume": 1_000.0 * day,
        }
        for day in range(1, 13)
    ]


async def _failed_yahoo_history(symbol: str, timeout: float, *, range_: str = "3mo"):
    raise RuntimeError("yahoo history down")


# ─────────────────────────────────────────────────────────────────────────
# GLCO — real history on live rows
# ─────────────────────────────────────────────────────────────────────────


def test_glco_live_rows_carry_real_daily_history(monkeypatch) -> None:
    from showme.engine.functions.commodity import _funcs as mod

    monkeypatch.setattr(mod, "_yahoo_chart_ohlcv", _fake_yahoo_history)
    fn = mod.GLCOFunction(deps=FunctionDeps(yfinance=_FakeCommodityQuotes()))
    result = _run(fn.execute())
    data = result.data
    assert data["status"] == "ok"
    assert len(data["rows"]) == 14

    live_rows = [row for row in data["rows"] if row.get("history")]
    assert len(live_rows) == 14, "every live row must carry its fetched history"
    for row in live_rows:
        assert row["history_source"] == "yfinance_daily"
        # UI convention: numeric daily close series, ascending.
        assert len(row["history"]) == 12
        assert all(isinstance(value, float) for value in row["history"])
        assert row["history"] == sorted(row["history"])
        assert row["history"][-1] == 112.5  # 100.5 + day 12


def test_glco_history_failure_leaves_rows_without_fabricated_series(monkeypatch) -> None:
    from showme.engine.functions.commodity import _funcs as mod

    monkeypatch.setattr(mod, "_yahoo_chart_ohlcv", _failed_yahoo_history)
    fn = mod.GLCOFunction(deps=FunctionDeps(yfinance=_FakeCommodityQuotes()))
    result = _run(fn.execute())
    data = result.data
    assert data["status"] == "ok"
    assert data["rows"], "quote pass still serves live rows"
    assert all("history" not in row for row in data["rows"])
    assert "history" not in data
    assert any("history" in warning for warning in result.warnings)


def test_glco_model_fallback_rows_have_no_history() -> None:
    from showme.engine.functions.commodity._funcs import GLCOFunction

    result = _run(GLCOFunction(deps=FunctionDeps()).execute())
    data = result.data
    assert data["status"] == "provider_unavailable"
    assert data["source_mode"] == "model"
    assert data["rows"]
    assert all("history" not in row for row in data["rows"])
    assert "history" not in data
    assert data.get("reference_vintage")


# ─────────────────────────────────────────────────────────────────────────
# WCRS — real change % from derived cross history, null when unavailable
# ─────────────────────────────────────────────────────────────────────────


def test_wcrs_change_pct_and_history_derive_from_usd_legs() -> None:
    from showme.engine.functions.fx._funcs import WCRSFunction

    provider = _FakeFXHistoryProvider({"USDEUR": [1.10, 1.11], "USDGBP": [0.80, 0.79]})
    fn = WCRSFunction(deps=FunctionDeps(yfinance=provider))
    result = _run(fn.execute())
    rows = {row["pair"]: row for row in result.data["rows"]}

    # EURGBP = leg(GBP) / leg(EUR): last 0.79/1.11 over prev 0.80/1.10.
    expected = ((0.79 / 1.11) / (0.80 / 1.10) - 1.0) * 100.0
    eurgbp = rows["EURGBP"]
    assert eurgbp["change_pct"] == pytest.approx(expected, abs=1e-3)
    assert eurgbp["change_pct"] != 0.0
    # UI convention: numeric daily cross-close series, ascending.
    assert eurgbp["history"] == pytest.approx([0.80 / 1.10, 0.79 / 1.11], abs=1e-8)
    assert all(isinstance(value, float) for value in eurgbp["history"])
    assert "yfinance" in eurgbp.get("history_source", "")

    # USD base is the constant-1.0 leg: USDGBP change is the GBP leg change.
    usdgbp = rows["USDGBP"]
    assert usdgbp["change_pct"] == pytest.approx((0.79 / 0.80 - 1.0) * 100.0, abs=1e-3)

    # A currency with no usable leg is null — never a placeholder 0.0.
    usdtry = rows["USDTRY"]
    assert usdtry["change_pct"] is None
    assert "history" not in usdtry


def test_wcrs_without_history_emits_null_not_zero() -> None:
    from showme.engine.functions.fx._funcs import WCRSFunction

    result = _run(WCRSFunction(deps=FunctionDeps()).execute())
    rows = result.data["rows"]
    assert rows
    assert all(row["change_pct"] is None for row in rows)
    assert all("history" not in row for row in rows)


def test_wcrs_explicit_live_false_skips_history_and_change() -> None:
    from showme.engine.functions.fx._funcs import WCRSFunction

    provider = _FakeFXHistoryProvider({"USDEUR": [1.10, 1.11], "USDGBP": [0.80, 0.79]})
    fn = WCRSFunction(deps=FunctionDeps(yfinance=provider))
    result = _run(fn.execute(live=False))
    assert provider.calls == 0, "live=false must not fetch history legs"
    assert all(row["change_pct"] is None for row in result.data["rows"])


# ─────────────────────────────────────────────────────────────────────────
# Default-polarity flips — FSRC / MOST / WEI
# ─────────────────────────────────────────────────────────────────────────


def test_fsrc_default_attempts_live_quotes() -> None:
    from showme.engine.functions.screen._funcs import FSRCFunction

    provider = _FakeQuoteProvider()
    result = _run(FSRCFunction(deps=FunctionDeps(yfinance=provider)).execute(
        query="expenseRatio <= 0.001"
    ))
    assert provider.calls > 0, "default polarity must attempt live quotes"
    assert result.data["status"] == "ok"
    assert "yfinance" in result.sources
    assert any(row.get("quote_state") == "live" for row in result.data["rows"])


def test_fsrc_no_provider_keeps_labelled_reference_rows() -> None:
    from showme.engine.functions.screen._funcs import FSRCFunction

    result = _run(FSRCFunction(deps=FunctionDeps()).execute(query="expenseRatio <= 0.001"))
    assert result.data["status"] == "ok"
    assert result.data["rows"]
    assert all(row.get("quote_state") != "live" for row in result.data["rows"])
    assert "yfinance" not in result.sources
    assert _body(result)["data_state"] != "live"


def test_fsrc_reference_true_skips_provider() -> None:
    from showme.engine.functions.screen._funcs import FSRCFunction

    provider = _FakeQuoteProvider()
    result = _run(FSRCFunction(deps=FunctionDeps(yfinance=provider)).execute(
        query="expenseRatio <= 0.001", reference=True
    ))
    assert provider.calls == 0
    assert all(row.get("quote_state") != "live" for row in result.data["rows"])
    assert "yfinance" not in result.sources
    assert _body(result)["data_state"] != "live"


def test_most_default_without_provider_is_failure_labelled() -> None:
    from showme.engine.functions.screen._funcs import MOSTFunction

    result = _run(MOSTFunction(deps=FunctionDeps()).execute())
    assert result.data["status"] == "provider_unavailable"
    assert result.data["rows"] == []
    assert result.metadata.get("live") is False
    assert _body(result)["data_state"] != "live"


def test_most_default_with_provider_is_live() -> None:
    from showme.engine.functions.screen._funcs import MOSTFunction

    provider = _FakeQuoteProvider()
    result = _run(MOSTFunction(deps=FunctionDeps(yfinance=provider)).execute(sort="volume"))
    assert provider.calls > 0
    assert result.data["status"] == "ok"
    assert result.metadata.get("live") is True
    assert all(row.get("quote_state") == "live" for row in result.data["rows"])


def test_most_reference_true_keeps_labelled_reference_rows() -> None:
    from showme.engine.functions.screen._funcs import MOSTFunction

    provider = _FakeQuoteProvider()
    result = _run(MOSTFunction(deps=FunctionDeps(yfinance=provider)).execute(reference=True))
    assert provider.calls == 0
    assert result.data["status"] == "reference"
    assert result.data["live"] is False
    assert all(row.get("quote_state") == "reference" for row in result.data["rows"])


def test_wei_default_without_provider_fails_into_labelled_template() -> None:
    from showme.engine.functions.screen._funcs import WEIFunction

    result = _run(WEIFunction().execute())
    data = result.data
    assert data["status"] == "provider_unavailable"
    assert data["source_mode"] == "world_index_template"
    assert data["rows"] and all(row.get("market_state") == "model" for row in data["rows"])
    assert result.metadata.get("fallback") is True
    assert result.metadata.get("degraded") is True
    assert _body(result)["data_state"] != "live"


def test_wei_default_with_provider_is_live() -> None:
    from showme.engine.functions.screen._funcs import WEIFunction

    provider = _FakeQuoteProvider()
    result = _run(WEIFunction(deps=FunctionDeps(yfinance=provider)).execute())
    assert provider.calls > 0
    assert result.data["status"] == "ok"
    assert result.data["source_mode"] == "yfinance_live"
    assert result.metadata.get("live") is True
    assert result.data["rows"]


def test_wei_reference_true_skips_provider_and_never_claims_live() -> None:
    from showme.engine.functions.screen._funcs import WEIFunction

    provider = _FakeQuoteProvider()
    result = _run(WEIFunction(deps=FunctionDeps(yfinance=provider)).execute(reference=True))
    assert provider.calls == 0
    assert result.data["status"] == "ok"
    assert result.data["source_mode"] == "world_index_template"
    assert result.metadata.get("live") is False
    assert _body(result)["data_state"] != "live"


# ─────────────────────────────────────────────────────────────────────────
# FINRA adapter — anonymous path, TTL cache, failure cooldown
# ─────────────────────────────────────────────────────────────────────────


class _FinraResp:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> list[dict[str, Any]]:
        return self._rows


def _wire_finra(adapter, client: Any) -> None:
    async def _fake_client():
        return client

    async def _fake_auth() -> None:
        return None

    adapter._client_ = _fake_client  # type: ignore[assignment]
    adapter._maybe_auth = _fake_auth  # type: ignore[assignment]


def test_finra_anonymous_pull_cached_and_copy_out(monkeypatch) -> None:
    from showme.engine.data_sources.equity.finra_adapter import FINRAAdapter

    monkeypatch.delenv("FINRA_API_KEY", raising=False)
    monkeypatch.delenv("FINRA_API_SECRET", raising=False)
    posts: list[dict[str, Any]] = []
    sent_headers: list[dict[str, Any]] = []

    class _Client:
        async def post(self, url, json=None, headers=None, **kw):
            posts.append(json or {})
            sent_headers.append(headers or {})
            return _FinraResp([{
                "weekStartDate": "2026-09-07",
                "issueSymbolIdentifier": "AAPL",
                "MPID": "UBSS",
                "totalWeeklyShareQuantity": 1000,
                "totalWeeklyTradeCount": 10,
            }])

    adapter = FINRAAdapter({})
    _wire_finra(adapter, _Client())

    first = _run(adapter.ats_weekly("AAPL", limit=25))
    second = _run(adapter.ats_weekly("AAPL", limit=25))
    assert len(posts) == 1, "second pull inside the TTL must be served from cache"
    assert not first.empty and not second.empty
    assert "Authorization" not in sent_headers[0], "anonymous path must not send auth"

    # Copy-out: mutating a caller's frame must not poison the cache.
    second.loc[0, "weekStartDate"] = "MUTATED"
    third = _run(adapter.ats_weekly("AAPL", limit=25))
    assert third.loc[0, "weekStartDate"] == "2026-09-07"


def test_finra_failure_sets_cooldown_without_refetch(monkeypatch) -> None:
    from showme.engine.data_sources.equity.finra_adapter import FINRAAdapter

    posts: list[Any] = []

    class _BoomClient:
        async def post(self, url, json=None, headers=None, **kw):
            posts.append(json)
            raise httpx.ConnectError("refused")

    adapter = FINRAAdapter({})
    _wire_finra(adapter, _BoomClient())

    with pytest.raises(DataSourceError):
        _run(adapter.ats_weekly("AAPL", limit=25))
    assert len(posts) == 1

    # Inside the cooldown the adapter refuses BEFORE hitting the network.
    with pytest.raises(DataSourceError):
        _run(adapter.ats_weekly("AAPL", limit=25))
    assert len(posts) == 1

    # After the cooldown expires it retries.
    adapter._cooldown_until = 0.0
    with pytest.raises(DataSourceError):
        _run(adapter.ats_weekly("AAPL", limit=25))
    assert len(posts) == 2
    assert adapter.requires_api_key is False


def test_function_factory_wires_keyless_finra() -> None:
    from showme.engine.data_sources.equity.finra_adapter import FINRAAdapter
    from showme.engine.services.function_factory import FunctionFactory

    factory = FunctionFactory()
    assert isinstance(factory.deps.finra, FINRAAdapter)
    assert factory.deps.finra.requires_api_key is False


def test_dpf_degradation_is_labelled_and_ratio_is_null() -> None:
    from showme.engine.functions.equity.dpf import DPFFunction

    class _BoomFinra:
        async def ats_weekly(self, symbol=None, limit=200):
            raise RuntimeError("finra down")

    fn = DPFFunction(deps=FunctionDeps(finra=_BoomFinra()))
    result = _run(fn.execute(instrument=Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)))
    data = result.data
    assert data["status"] == "provider_unavailable"
    assert result.sources == ["dark_pool_model"]
    assert result.metadata.get("provider_errors")
    assert data["rows"], "shape rows keep the table structure"
    assert all(row.get("dark_pool_pct") is None for row in data["rows"])
    assert all(row.get("estimated_total_volume") is None for row in data["rows"])
    assert all(
        row.get("source_mode") in {"labelled_current_shape_model", "finra_ats_weekly_stale"}
        for row in data["rows"]
    )


def test_dpf_timeout_fallback_is_shape_model_not_finra_stale(monkeypatch) -> None:
    """Fabricated shape rows must never claim a real (stale) FINRA feed.

    The timeout path never touched FINRA, so the honest token is
    ``shape_model_timeout``; ``finra_ats_weekly_stale`` is reserved for real
    FINRA rows that aged out.
    """
    from showme.engine.functions.equity import dpf as dpf_mod
    from showme.engine.functions.equity.dpf import DPFFunction

    async def _boom(self, instrument, **params):  # noqa: ANN001
        raise asyncio.TimeoutError("dpf slow")

    monkeypatch.setattr(dpf_mod.DPFFunction, "_execute_inner", _boom)
    result = _run(
        DPFFunction(deps=FunctionDeps()).execute(
            instrument=Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
        )
    )
    data = result.data
    assert data["status"] == "provider_unavailable"
    assert "timed out" in data["reason"]
    assert data["rows"]
    assert all(row.get("source_mode") == "shape_model_timeout" for row in data["rows"])
    assert all(row.get("data_warning") == data["reason"] for row in data["rows"])
    assert all(row.get("dark_pool_pct") is None for row in data["rows"])
    assert all(row.get("estimated_total_volume") is None for row in data["rows"])
    assert not any(
        row.get("source_mode") == "finra_ats_weekly_stale" for row in data["rows"]
    )


# ─────────────────────────────────────────────────────────────────────────
# ONCH optional keyless companion tiers
# ─────────────────────────────────────────────────────────────────────────


def test_onch_row_sources_include_only_contributing_providers() -> None:
    from showme.engine.functions.misc.onch import ONCHFunction

    payload = {
        "rows": [
            {"metric": "Mempool Backlog", "source": "mempool"},
            {"metric": "BTC Dominance", "source": "coingecko"},
            {"metric": "Ethereum TVL", "source": "defillama"},
            {"metric": "ETH Gas (avg)", "source": "blockscout"},
        ]
    }
    sources = ONCHFunction._row_sources(payload)
    assert sources == ["mempool", "coingecko", "defillama", "blockscout"]
    # No companion tier contributed → the base set stays exact.
    assert ONCHFunction._row_sources({"rows": [{"metric": "x", "source": "mempool"}]}) == [
        "mempool", "coingecko",
    ]
