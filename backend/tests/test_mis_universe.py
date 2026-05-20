"""MIS universe quality contract.

The user requirement (2026-05-15): MIS must scan ≥1000 unique symbols
across all markets, and the crypto market must contain only USDT-quoted
pairs whose base is NOT a stablecoin.

These tests pin the contract so future refactors can't silently shrink
the universe or leak ``USDCUSDT`` / ``BTCBUSD``-style pairs back in.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from showme.mis import (  # noqa: E402
    MARKET_TF_WEIGHTS,
    MIS_MARKETS,
    MIS_UNIVERSES,
    STABLECOIN_BASES,
    _BASE_TF_WEIGHTS,
    _RESAMPLE_RULES,
    _filter_crypto_universe,
    _resample_ohlcv,
    _resolve_universe,
    load_mis_config,
    save_mis_config,
)


# ── Total breadth ────────────────────────────────────────────────────────

def test_total_unique_symbols_at_least_2500():
    seen: set[str] = set()
    for market in MIS_MARKETS:
        seen.update(MIS_UNIVERSES[market])
    assert len(seen) >= 2500, (
        f"MIS quality bar: ≥2500 unique symbols required, got {len(seen)}"
    )


def test_every_supported_market_has_a_universe():
    for market in MIS_MARKETS:
        universe = MIS_UNIVERSES.get(market)
        assert universe, f"{market} universe must be non-empty"
        assert all(isinstance(s, str) for s in universe)


# ── Crypto rules ─────────────────────────────────────────────────────────

def test_crypto_universe_is_only_usdt_quoted():
    bad = [s for s in MIS_UNIVERSES["CRYPTO"] if not s.endswith("USDT")]
    assert not bad, f"non-USDT pairs leaked into CRYPTO: {bad[:10]}"


def test_crypto_universe_has_no_stablecoin_bases():
    crypto = MIS_UNIVERSES["CRYPTO"]
    bad = [s for s in crypto if s.endswith("USDT") and s[:-4] in STABLECOIN_BASES]
    assert not bad, f"stablecoin-base pairs leaked into CRYPTO: {bad}"


def test_crypto_universe_is_deduplicated():
    crypto = MIS_UNIVERSES["CRYPTO"]
    assert len(crypto) == len(set(crypto)), "CRYPTO universe contains duplicates"


@pytest.mark.parametrize("sample", [
    "USDCUSDT", "BUSDUSDT", "DAIUSDT", "FDUSDUSDT", "TUSDUSDT",
    "USDPUSDT", "FRAXUSDT",
])
def test_filter_rejects_stablecoin_pairs(sample: str):
    assert _filter_crypto_universe([sample]) == []


@pytest.mark.parametrize("sample", [
    "BTCBUSD", "ETHBTC", "SOLEUR", "BNBETH", "ADABNB", "DOGEBNB",
])
def test_filter_rejects_non_usdt_pairs(sample: str):
    assert _filter_crypto_universe([sample]) == []


def test_filter_keeps_valid_usdt_pairs_in_order():
    raw = ["btcusdt", " ETHUSDT ", "solusdt", "btcusdt", "DOGEUSDT"]
    out = _filter_crypto_universe(raw)
    assert out == ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"]


# ── Per-market sizing ────────────────────────────────────────────────────

@pytest.mark.parametrize("market,floor", [
    ("CRYPTO", 300),
    ("EQUITY", 1500),
    ("ETF", 300),
    ("FX", 50),
    ("COMMODITY", 20),
    ("BOND", 10),
])
def test_each_market_meets_minimum_size(market: str, floor: int):
    size = len(MIS_UNIVERSES[market])
    assert size >= floor, f"{market} only has {size} symbols, need ≥{floor}"


# ── _resolve_universe override path ──────────────────────────────────────

def test_resolve_universe_filters_crypto_override(tmp_path, monkeypatch):
    # Empty config → defaults
    cfg = {
        "version": 1,
        "markets": {
            "CRYPTO": {
                "universe_override": [
                    "BTCUSDT", "USDCUSDT", "BTCBUSD", "ETHUSDT",
                    "DAIUSDT", "  solusdt  ", "ETHUSDT",
                ]
            }
        },
    }
    resolved = _resolve_universe("CRYPTO", cfg)
    assert resolved == ["BTCUSDT", "ETHUSDT", "SOLUSDT"], resolved


def test_resolve_universe_dedupes_non_crypto_override():
    cfg = {
        "version": 1,
        "markets": {
            "EQUITY": {
                "universe_override": ["aapl", "AAPL", " msft ", "TSLA", "MSFT"]
            }
        },
    }
    resolved = _resolve_universe("EQUITY", cfg)
    assert resolved == ["AAPL", "MSFT", "TSLA"]


def test_resolve_universe_empty_override_falls_back_to_default():
    cfg = {"version": 1, "markets": {"BOND": {"universe_override": []}}}
    assert _resolve_universe("BOND", cfg) == list(MIS_UNIVERSES["BOND"])


# ── save_mis_config round-trip ───────────────────────────────────────────

# ── Timeframe parity (the v3 fairness fix) ──────────────────────────────

EXPECTED_TF_SET: frozenset[str] = frozenset({
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "8h",
    "12h", "1d",
})


def test_every_market_runs_the_same_12_timeframes():
    """Cross-market scoring is only fair when every market has the same
    TF set + the same ZAK weights. Without parity, raw weighted_score
    naturally inflates for whichever market ships more TFs.
    """
    for market in MIS_MARKETS:
        weights = MARKET_TF_WEIGHTS[market]
        tf_set = frozenset(weights.keys())
        assert tf_set == EXPECTED_TF_SET, (
            f"{market} TF set {tf_set ^ EXPECTED_TF_SET} differs from CRYPTO"
        )
        # Weights must match the canonical _BASE_TF_WEIGHTS verbatim — no
        # market gets to silently rebalance the ZAK on its own.
        assert weights == _BASE_TF_WEIGHTS, (
            f"{market} weights diverge from _BASE_TF_WEIGHTS: "
            f"{set(weights.items()) ^ set(_BASE_TF_WEIGHTS.items())}"
        )


def test_resample_rules_cover_every_non_native_tf():
    """yfinance natively supports {1m, 2m, 5m, 15m, 30m, 60m=1h, 1d,
    1wk, 1mo}. Everything else in the 12-TF ZAK matrix has to be
    resampled in-process. This test pins the bridge so we never
    silently drop a TF for non-crypto markets.
    """
    yfinance_native = {"1m", "5m", "15m", "30m", "1h", "1d"}
    missing = EXPECTED_TF_SET - yfinance_native
    for tf in missing:
        assert tf in _RESAMPLE_RULES, (
            f"{tf} is in the ZAK matrix but has no resample rule"
        )
        source, rule = _RESAMPLE_RULES[tf]
        assert source in yfinance_native, (
            f"{tf} resample source {source} isn't yfinance-native"
        )


def test_resample_ohlcv_aggregates_correctly():
    """Verify the resampler uses canonical OHLC aggregation (open=first,
    high=max, low=min, close=last, volume=sum)."""
    pd = pytest.importorskip("pandas")
    np = pytest.importorskip("numpy")
    idx = pd.date_range("2026-01-01", periods=12, freq="1h", tz="UTC")
    df = pd.DataFrame(
        {
            "open": np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], dtype=float),
            "high": np.array([2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13], dtype=float),
            "low":  np.array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11], dtype=float),
            "close":np.array([1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5], dtype=float),
            "volume": np.full(12, 100.0),
        },
        index=idx,
    )
    out = _resample_ohlcv(df, "4h")
    assert out is not None and len(out) >= 2
    # Pick the middle bin (fully populated) to assert OHLC math.
    # With label='right' closed='right', the bin "2026-01-01 04:00" contains
    # bars indexed 01:00, 02:00, 03:00, 04:00 → opens=[2,3,4,5], so
    # open=2, high=max(3..6)=6, low=min(1..4)=1, close=5.5, volume=400.
    bar = out.loc["2026-01-01 04:00:00+00:00"]
    assert bar["open"] == 2.0
    assert bar["high"] == 6.0
    assert bar["low"] == 1.0
    assert bar["close"] == 5.5
    assert bar["volume"] == 400.0


def test_resample_handles_empty_input():
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame()
    assert _resample_ohlcv(df, "4h") is None
    assert _resample_ohlcv(None, "4h") is None


# ── Live scan progress (drives the progress bar in MIS pane) ─────────────

def test_progress_snapshot_carries_percent_when_running():
    """``percent`` is computed by the backend so the UI polling loop
    never has to redo the divide-by-zero guard."""
    from showme.mis import _progress_update, get_scan_progress
    _progress_update(
        status="running", total=200, completed=50, in_flight=12,
        skipped=0, markets=["CRYPTO"], started_at="",
        elapsed_ms=0.0, current_symbol="BTCUSDT", current_market="CRYPTO",
    )
    snap = get_scan_progress()
    assert snap["status"] == "running"
    assert snap["percent"] == 25.0
    assert snap["completed"] == 50
    assert snap["total"] == 200
    assert snap["current_symbol"] == "BTCUSDT"


def test_progress_snapshot_zero_total_does_not_divide_by_zero():
    """Idle state has total=0 — percent must be a safe 0, not NaN/error."""
    from showme.mis import _progress_update, get_scan_progress
    _progress_update(status="idle", total=0, completed=0)
    snap = get_scan_progress()
    assert snap["percent"] == 0.0
    assert snap["status"] == "idle"


def test_progress_snapshot_done_state_carries_elapsed_ms():
    """After ``done`` the UI's last poll should see the final elapsed
    time so the panel can render a clean wrap-up note."""
    from showme.mis import _progress_update, get_scan_progress
    _progress_update(
        status="done", total=10, completed=10, in_flight=0,
        elapsed_ms=4321.5,
    )
    snap = get_scan_progress()
    assert snap["status"] == "done"
    assert snap["percent"] == 100.0
    assert snap["elapsed_ms"] == 4321.5


def test_save_mis_config_persists_dedupe(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "showme.mis.cache_path",
        lambda name: tmp_path / name,
    )
    payload = {
        "version": 1,
        "markets": {
            m: {} for m in MIS_MARKETS
        },
    }
    payload["markets"]["EQUITY"]["universe_override"] = [
        "AAPL", "aapl", "TSLA ", "MSFT", "AAPL"
    ]
    saved = save_mis_config(payload)
    assert saved["markets"]["EQUITY"]["universe_override"] == ["AAPL", "TSLA", "MSFT"]

    loaded = load_mis_config()
    assert loaded["markets"]["EQUITY"]["universe_override"] == ["AAPL", "TSLA", "MSFT"]
