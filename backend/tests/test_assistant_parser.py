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


# ─── B1 — ignored-concept honesty notes ─────────────────────────────────────
def test_divergence_is_echoed_as_ignored():
    spec, notes = parse_request("RSI divergence strategy")
    assert spec is not None
    assert any("divergence" in n and "yok sayıldı" in n for n in notes)


def test_stop_loss_phrase_is_echoed_as_ignored():
    spec, notes = parse_request("RSI 30 altında al, stop loss %2 koy")
    assert spec is not None
    assert any("stop-loss" in n and "yok sayıldı" in n for n in notes)


def test_risk_sizing_phrase_is_echoed_as_ignored():
    spec, notes = parse_request("MACD strateji, risk yönetimi ile pozisyon büyüklüğü ayarla")
    assert spec is not None
    assert any("boyutlandırma" in n and "yok sayıldı" in n for n in notes)


def test_trailing_phrase_is_echoed_as_ignored():
    spec, notes = parse_request("EMA crossover with trailing stop")
    assert spec is not None
    assert any("trailing" in n.lower() and "yok sayıldı" in n for n in notes)


def test_pattern_word_is_echoed_as_ignored():
    spec, notes = parse_request("RSI engulfing breakout strategy")
    assert spec is not None
    assert any("formasyon" in n and "yok sayıldı" in n for n in notes)


def test_multi_indicator_notes_only_first_used():
    spec, notes = parse_request("RSI ve MACD birlikte kullan")
    assert spec is not None
    # First keyword in the table wins; only one indicator is wired.
    assert spec["indicators"][0]["id"] == "rsi"
    assert any("Yalnızca ilk gösterge" in n and "yok sayıldı" in n for n in notes)
    assert any("macd" in n for n in notes)


# ─── B2 — defaults vs parsed disclosure ─────────────────────────────────────
def test_timeframe_defaulted_note_when_not_specified():
    spec, notes = parse_request("RSI strateji")
    assert spec is not None
    assert any(n == "Timeframe: 1h (varsayılan — belirtilmedi)" for n in notes)


def test_timeframe_parsed_note_when_specified():
    spec, notes = parse_request("RSI 4h strateji")
    assert spec is not None
    assert any(n == "Timeframe: 4h" for n in notes)
    assert not any("varsayılan — belirtilmedi" in n for n in notes)


def test_position_defaults_are_disclosed():
    spec, notes = parse_request("RSI strateji")
    assert spec is not None
    assert any(
        "Varsayılan: pozisyon long" in n
        and "fixed_quote 100" in n
        and "stop-loss %2.0" in n
        and "talep edilmedi" in n
        for n in notes
    )


# ─── B3 — EMA dual-period fix ───────────────────────────────────────────────
def test_ema_two_numbers_use_both_periods():
    spec, notes = parse_request("EMA 20 50 crossover")
    assert spec is not None
    inds = spec["indicators"]
    assert len(inds) == 2
    assert inds[0]["params"]["period"] == 20
    assert inds[1]["params"]["period"] == 50  # NOT 60 (period*3)
    assert any("girişten alındı" in n for n in notes)


def test_ema_single_number_keeps_3x_long():
    spec, notes = parse_request("EMA 20 crossover")
    assert spec is not None
    inds = spec["indicators"]
    assert inds[0]["params"]["period"] == 20
    assert inds[1]["params"]["period"] == 60  # period * 3


def test_ema_no_number_defaults_20_60():
    spec, notes = parse_request("EMA crossover strateji")
    assert spec is not None
    inds = spec["indicators"]
    assert inds[0]["params"]["period"] == 20
    assert inds[1]["params"]["period"] == 60
