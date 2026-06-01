"""De-garbage tests for TCA — Trade Cost Analysis.

Verifies the TCA handler returns REAL contract-conformant data:
- an honest ``empty`` payload (rows == [], summary.fill_count == 0) when no
  fills exist (no synthetic constants),
- real per-fill slippage rows joined against a LIVE VWAP benchmark when fills
  exist in the autonomous bot ledger, signed correctly by side,
- graceful degradation (arrival fallback / provider_unavailable) on a genuine
  benchmark outage.

Fills are seeded through the real ``BotStore`` (JSON BotRecords) with
``app_home`` monkeypatched to a temp dir, so the test exercises the actual
ledger-reading path. The live-network benchmark fetch is stubbed via a fake
``binance`` dep so the suite stays fast and offline-safe; a broken stub proves
the graceful-failure shape.
"""

from __future__ import annotations

import asyncio

import pytest

from showme.bots.record import BotRecord, SignalEntry
from showme.bots.store import BotStore
from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.trade.tca import TCAFunction


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Stub providers so the test is fast + deterministic (no real network needed).
# ---------------------------------------------------------------------------
class _StubBinance:
    """Returns a flat 100.0 VWAP so slippage signs are predictable."""

    async def klines(self, symbol, interval="5m", limit=288):
        return [
            {"high": 100.0, "low": 100.0, "close": 100.0, "volume": 10.0}
            for _ in range(5)
        ]


class _BrokenBinance:
    async def klines(self, symbol, interval="5m", limit=288):
        raise ConnectionError("simulated network outage")


def _make_handler(provider) -> TCAFunction:
    return TCAFunction(deps=FunctionDeps(binance=provider))


def _crypto_instrument(symbol: str) -> Instrument:
    return Instrument(symbol=symbol, asset_class=AssetClass.CRYPTO, exchange="BINANCE")


def _use_temp_home(tmp_path, monkeypatch):
    """Point app_home() (and thus BotStore) at an isolated temp dir."""
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    # order_history.runtime_path also resolves under app_home, but isolate it
    # explicitly so a shared DB cannot leak fills into these assertions.
    monkeypatch.setattr(
        "showme.engine.services.order_history.runtime_path",
        lambda name: tmp_path / "runtime" / name,
    )
    (tmp_path / "runtime").mkdir(parents=True, exist_ok=True)


def _seed_bot(symbol, fills):
    """fills: list of (kind, fill_price, signal_price, qty, order_id)."""
    store = BotStore.fresh()
    log = []
    for i, (kind, fill_px, sig_px, qty, oid) in enumerate(fills):
        log.append(SignalEntry(
            bar_index=i, bar_time=f"2026-06-01T0{i}:00:00Z",
            kind=kind, price=sig_px, action="placed",
            order_id=oid, fill_price=fill_px, qty=qty,
        ))
    rec = BotRecord(
        strategy_id="s1", credential_id="c1", exchange_id="binance",
        symbol=symbol, timeframe="1h", mode="live", enabled=True,
        signal_log=log,
    )
    return store.save(rec)


# ---------------------------------------------------------------------------
# 1) Honest empty when no fills.
# ---------------------------------------------------------------------------
def test_tca_empty_when_no_fills(tmp_path, monkeypatch):
    _use_temp_home(tmp_path, monkeypatch)
    handler = _make_handler(_StubBinance())
    res = _run(handler.execute(symbol="ZZZ_NOPE_USDT"))
    data = res.data
    assert data["status"] == "empty"
    assert data["rows"] == []
    assert data["summary"]["fill_count"] == 0
    assert data["methodology"]
    assert "field_dictionary" in data
    assert data["benchmark"] == "VWAP"


# ---------------------------------------------------------------------------
# 2) Real per-fill slippage rows with a live VWAP benchmark, signed by side.
# ---------------------------------------------------------------------------
def test_tca_real_rows_signed_slippage(tmp_path, monkeypatch):
    _use_temp_home(tmp_path, monkeypatch)
    # entry fill ABOVE 100.0 VWAP -> BUY positive slippage.
    # exit  fill ABOVE 100.0 VWAP -> SELL negative slippage.
    _seed_bot("BTCUSDT", [
        ("entry", 110.0, 105.0, 1.0, "r1"),
        ("exit", 110.0, 105.0, 2.0, "r2"),
    ])

    handler = _make_handler(_StubBinance())
    res = _run(handler.execute(
        instrument=_crypto_instrument("BTCUSDT"),
        symbol="BTCUSDT", benchmark="VWAP",
    ))
    data = res.data
    assert data["status"] == "ok"
    assert len(data["rows"]) == 2

    by_side = {r["side"]: r for r in data["rows"]}
    buy = by_side["BUY"]
    sell = by_side["SELL"]

    # Benchmark must be the LIVE VWAP (100.0) from the stub, not metadata.
    assert buy["benchmark_px"] == pytest.approx(100.0)
    assert buy["benchmark_source"] == "binance"

    # BUY above VWAP -> positive slippage; SELL above VWAP -> negative.
    assert buy["slippage_bps"] is not None and buy["slippage_bps"] > 0
    assert sell["slippage_bps"] is not None and sell["slippage_bps"] < 0

    # Rows carry REAL computed numbers (110 fill vs 105 arrival), not a constant.
    assert buy["avg_fill_px"] == pytest.approx(110.0)
    assert buy["arrival_px"] == pytest.approx(105.0)
    assert buy["is_bps"] is not None and buy["is_bps"] > 0

    # Contract shape.
    assert data["summary"]["benchmark"] == "VWAP"
    assert data["summary"]["fill_count"] == 2
    assert "total_cost_usd" in data["summary"]
    assert len(data["series"]) == 2
    assert "binance" in res.sources
    assert "field_dictionary" in data


# ---------------------------------------------------------------------------
# 3) Graceful degradation when the live benchmark provider fails.
# ---------------------------------------------------------------------------
def test_tca_provider_outage_degrades_gracefully(tmp_path, monkeypatch):
    _use_temp_home(tmp_path, monkeypatch)
    # entry fill HAS an arrival (signal) price -> can fall back to arrival.
    _seed_bot("BTCUSDT", [("entry", 110.0, 105.0, 1.0, "r1")])

    handler = _make_handler(_BrokenBinance())
    res = _run(handler.execute(symbol="BTCUSDT", benchmark="VWAP"))
    data = res.data

    # ok-but-degraded (arrival fallback) OR provider_unavailable — both honest.
    assert data["status"] in {"ok", "provider_unavailable"}
    assert any("benchmark" in w.lower() for w in res.warnings)

    rows = {r["symbol"]: r for r in data["rows"]}
    btc = rows["BTCUSDT"]
    assert btc["benchmark_source"] == "arrival"
    assert btc["benchmark_px"] == pytest.approx(105.0)


# ---------------------------------------------------------------------------
# 4) Read-only: handler exposes no broker-mutating behaviour.
# ---------------------------------------------------------------------------
def test_tca_is_read_only():
    handler = TCAFunction()
    for forbidden in ("place_order", "cancel_order", "submit", "amend"):
        assert not hasattr(handler, forbidden)
