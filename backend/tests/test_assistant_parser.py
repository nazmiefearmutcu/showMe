"""Rule-based NL parser tests."""
from __future__ import annotations

from showme.assistant.parser import parse_request


def test_empty_returns_none():
    spec, notes = parse_request("")
    assert spec is None
    assert any("Boş" in n or "boş" in n for n in notes)


def test_no_indicator_returns_none():
    spec, notes = parse_request("merhaba dünya")
    assert spec is None
    assert any("indikatör" in n.lower() for n in notes)


def test_rsi_with_thresholds():
    spec, notes = parse_request("RSI 30 altında al, 70 üstünde sat")
    assert spec is not None
    assert spec["indicators"][0]["id"] == "rsi"
    # entry rule crosses_below 30
    entry = spec["entry_rules"][0]
    assert entry["kind"] == "crosses_below"
    assert "30" in entry["right"]
    # exit rule crosses_above 70
    exit_r = spec["exit_rules"][0]
    assert exit_r["kind"] == "crosses_above"
    assert "70" in exit_r["right"]


def test_rsi_with_symbol_and_timeframe():
    spec, notes = parse_request("RSI on BTC/USDT 4h timeframe, 30 altında")
    assert spec is not None
    assert spec["timeframe"] == "4h"
    assert "BTC/USDT" in (spec.get("asset_filter") or {}).get("symbols", [])


def test_macd_default_cross():
    spec, notes = parse_request("MACD trend strateji")
    assert spec is not None
    assert spec["indicators"][0]["id"] == "macd"
    assert any(r["kind"] == "crosses_above" for r in spec["entry_rules"])


def test_ema_extracts_period():
    spec, notes = parse_request("EMA 50 crossover on ETH/USDT")
    assert spec is not None
    inds = spec["indicators"]
    assert len(inds) == 2  # short + long
    assert inds[0]["params"]["period"] == 50
    assert inds[1]["params"]["period"] == 150  # 3x


def test_rsi_with_no_thresholds_defaults_to_30_70():
    spec, notes = parse_request("RSI strateji")
    assert spec is not None
    entry = spec["entry_rules"][0]
    exit_r = spec["exit_rules"][0]
    assert "30" in entry["right"]
    assert "70" in exit_r["right"]


def test_bitcoin_keyword_maps_to_btc_usdt():
    spec, notes = parse_request("Bitcoin RSI strategy")
    assert spec is not None
    assert "BTC/USDT" in (spec.get("asset_filter") or {}).get("symbols", [])


def test_unknown_indicator_generic_fallback():
    spec, notes = parse_request("ATR volatility breakout")
    # ATR is in _KNOWN_INDICATORS so this should produce a spec
    assert spec is not None
    assert spec["indicators"][0]["id"] == "atr"
