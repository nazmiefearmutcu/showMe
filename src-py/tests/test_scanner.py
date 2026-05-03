"""Round-17 sidecar Scanner Agent tests."""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from showme.scanner import (  # noqa: E402
    ScanRequest,
    ZAK_MATRIX,
    UNIVERSES,
    consensus_signal,
    list_universes,
    select_universe,
)

def _trend(start: float, n: int, drift: float, noise: float = 0.0,
           seed: int = 0) -> list[float]:
    rng = random.Random(seed)
    out = []
    v = start
    for i in range(n):
        v = start + drift * i + (rng.uniform(-noise, noise) if noise else 0)
        out.append(v)
    return out


def test_zak_matrix_has_every_class_with_descending_weights():
    for ac, table in ZAK_MATRIX.items():
        assert table, f"{ac} ZAK empty"
        weights = list(table.values())
        for a, b in zip(weights, weights[1:]):
            assert a >= b, f"{ac} ZAK weights not monotone"


def test_universes_match_asset_class_prefix():
    listed = list_universes()
    assert {u["key"] for u in listed} == set(UNIVERSES)
    for u in listed:
        assert u["key"].startswith(u["asset_class"] + ":")


@pytest.mark.parametrize(
    "intent, expected_key, expected_ac",
    [
        ("crypto opportunities", "CRYPTO:MAJORS", "CRYPTO"),
        ("EUR/USD overextended", "FX:G10", "FX"),
        ("oil pullback", "COMMODITY:CORE", "COMMODITY"),
        ("ETF rotation", "ETF:US:CORE", "ETF"),
        ("S&P 500 names", "EQUITY:US:LARGE", "EQUITY"),
    ],
)
def test_phase_a_naive_intent_routing(intent, expected_key, expected_ac):
    key, ac, syms = select_universe(ScanRequest(intent=intent))
    assert key == expected_key
    assert ac == expected_ac
    assert len(syms) > 0


def test_phase_a_explicit_universe_overrides_intent():
    key, ac, _ = select_universe(
        ScanRequest(intent="bitcoin", universe="EQUITY:US:LARGE"),
    )
    assert key == "EQUITY:US:LARGE"
    assert ac == "EQUITY"


def test_consensus_signal_uptrend_has_positive_trend_components():
    # MACD and MA-cross both vote +1 on a clean uptrend; RSI may saturate
    # at overbought (mean-reversion bias) but the trend block dominates.
    closes = _trend(100.0, 250, 0.5)
    sig = consensus_signal(closes)
    macd = next(c for c in sig["components"] if c["name"] == "macd")
    ma = next(c for c in sig["components"] if c["name"] == "ma_cross")
    assert macd["score"] == 1
    assert ma["score"] == 1


def test_consensus_signal_downtrend_score_negative():
    closes = _trend(200.0, 250, -0.4)
    sig = consensus_signal(closes)
    assert sig["score"] < 0
    macd = next(c for c in sig["components"] if c["name"] == "macd")
    ma = next(c for c in sig["components"] if c["name"] == "ma_cross")
    assert macd["score"] == -1
    assert ma["score"] == -1


def test_consensus_signal_neutral_on_flat():
    closes = [100.0] * 250
    sig = consensus_signal(closes)
    # Flat → all three components return 0 → score 0 → NEUTRAL.
    assert sig["direction"] == "NEUTRAL"
    assert math.isclose(sig["score"], 0.0, abs_tol=1e-6)


def test_consensus_signal_overbought_rsi_pulls_against_trend():
    # Pure deterministic uptrend saturates RSI at 100 (overbought) — that's
    # a -1 score, which (combined with +0.8 MACD + 0.6 MA) yields ~+0.4 →
    # NEUTRAL by our threshold. This is the documented mean-reversion bias.
    closes = _trend(100.0, 250, 0.5)
    sig = consensus_signal(closes)
    assert sig["direction"] == "NEUTRAL"
    rsi_comp = next(c for c in sig["components"] if c["name"] == "rsi")
    assert rsi_comp["value"] >= 70


def test_consensus_signal_short_series_has_no_macd_or_ma():
    closes = list(range(20))
    sig = consensus_signal([float(c) for c in closes])
    # RSI works at 15 samples but MACD and MA cross need more.
    component_names = {c["name"] for c in sig["components"]}
    assert "rsi" in component_names
    assert "macd" not in component_names


# ── Phase C overextension detector ────────────────────────────────────────

def test_overextension_label_overbought():
    from showme.scanner import _overextension_score

    closes = [100.0] * 29 + [120.0]  # last close ~2σ above the flat baseline
    out = _overextension_score(closes, change_pct=20.0)
    assert out["deviation_label"] == "OVERBOUGHT"
    assert out["overextended"] is True
    assert out["change_pct_today"] == 20.0


def test_overextension_label_oversold():
    from showme.scanner import _overextension_score

    closes = [100.0] * 29 + [70.0]
    out = _overextension_score(closes, change_pct=-30.0)
    assert out["deviation_label"] == "OVERSOLD"
    assert out["overextended"] is True


def test_overextension_label_ok_on_steady_series():
    from showme.scanner import _overextension_score

    # Mild oscillation around 100 → std ~3 → last close +1 is well within 2σ.
    closes = [100.0 + (i % 5 - 2) for i in range(30)]
    out = _overextension_score(closes, change_pct=0.5)
    assert out["deviation_label"] == "OK"
    assert out["overextended"] is False


def test_overextension_returns_empty_when_too_few_closes():
    from showme.scanner import _overextension_score

    out = _overextension_score([1.0, 2.0, 3.0], change_pct=None)
    assert out == {}


def test_overextension_change_pct_alone_can_flag():
    from showme.scanner import _overextension_score

    # Steady series → z within ±2σ → label OK, but a >5% intraday change
    # alone trips the `overextended` flag.
    closes = [100.0 + (i % 5 - 2) for i in range(30)]
    out = _overextension_score(closes, change_pct=8.0)
    assert out["deviation_label"] == "OK"
    assert out["overextended"] is True


# ── ScanRequest phase wiring ──────────────────────────────────────────────

def test_scan_request_phase_default_is_ab():
    req = ScanRequest()
    assert req.phases == "A,B"
    assert req.fine_top_k is None


def test_scan_request_accepts_explicit_phases():
    req = ScanRequest(phases="A,B,C,D", fine_top_k=4)
    assert "C" in req.phases
    assert req.fine_top_k == 4
