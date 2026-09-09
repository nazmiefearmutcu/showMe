"""KAOS parity tests — the vendored strategy vs the REAL Entropy engine.

Quality guarantee for the vendored pure strategy layer
(``showme/bots/kaos/``): over identical deterministic fixture bars, the
vendored port and Entropy's ``ConsensusStrategy`` must produce IDENTICAL
signals bar-by-bar — same action (side), same reason string (which embeds
the score, regime label and all four vote chars), confidence within 1e-9
and sigma within 1e-9 relative.

Why the comparison is field-level rather than bit-exact floats:
``strength``/``sigma`` cross a polars boundary (Entropy evaluates its
indicators through crocodile/polars; the vendored layer is pure Python).
EMA/RSI/MACD are verified BIT-EXACT separately; the Bollinger rolling
kernel differs from pure Python by ~1e-15 RELATIVE (polars' internal SIMD
summation order — unfixable in stdlib Python). Any real logic drift
(thresholds, constants, state machine, reason formats) explodes into
different sides/reasons and fails loudly; a 1e-15 indicator wiggle cannot
flip a vote except on a measure-zero razor edge, and the exact reason
string (score at 2dp + regime + votes) is asserted byte-equal.

The Entropy arm is skipped gracefully when the Entropy repo (or its
deps) is not importable on the machine running the tests.
"""
from __future__ import annotations

import math
import os
import random
import sys
from pathlib import Path

import pytest

from showme.bots.kaos.config import KaosConfig
from showme.bots.kaos.costs import CostModel as VendoredCostModel  # noqa: F401
from showme.bots.kaos.indicators import (
    calculate_bollinger_bands as vendored_bb,
)
from showme.bots.kaos.indicators import (
    calculate_ema as vendored_ema,
)
from showme.bots.kaos.indicators import (
    calculate_macd as vendored_macd,
)
from showme.bots.kaos.indicators import (
    calculate_rsi as vendored_rsi,
)
from showme.bots.kaos.strategy import KaosStrategy

# Entropy checkout containing the REAL KAOS engine (override via env).
ENTROPY_ROOT = Path(os.environ.get("KAOS_ENTROPY_ROOT", Path.home() / "Entropy"))
ENTROPY_SRC = ENTROPY_ROOT / "src"
ENTROPY_SITE = ENTROPY_ROOT / ".venv" / "Lib" / "site-packages"

BAR_NS = 900 * 1_000_000_000  # 15-minute bars, like the live runner
SYM = "TEST/USDT:USDT"


def _try_import_entropy() -> bool:
    """Best-effort Entropy import (append-only path setup, never removes)."""
    for p in (ENTROPY_SRC, ENTROPY_SITE):
        sp = str(p)
        if p.exists() and sp not in sys.path:
            sys.path.append(sp)
    try:
        from entropy.bot.costs import CostModel  # noqa: F401
        from entropy.bot.strategies.consensus import (  # noqa: F401
            ConsensusStrategy,
        )
    except Exception:  # noqa: BLE001 — deliberate probe, any failure skips
        return False
    return True


HAS_ENTROPY = _try_import_entropy()

ENTROPY_SKIP = pytest.mark.skipif(
    not HAS_ENTROPY,
    reason="Entropy engine (C:/Users/Kullanıcı/Entropy) not importable on this box",
)


# ---- deterministic fixture bars --------------------------------------------

def fixture_closes(seed: int, n: int = 260) -> list[float]:
    """Multi-regime random walk: flat -> trend up -> chop -> crash."""
    rng = random.Random(seed)
    closes: list[float] = []
    px = 100.0
    for i in range(n):
        if i < 60:
            drift, vol = 0.0, 0.006
        elif i < 140:
            drift, vol = 0.004, 0.008
        elif i < 190:
            drift, vol = 0.0, 0.003
        else:
            drift, vol = -0.006, 0.02
        px *= (1.0 + drift + rng.gauss(0, vol))
        closes.append(px)
    return closes


# ---- engine configs (both sides get identical knobs) -----------------------

S20 = {  # the SHIPPED live config (entropy_live_paper build_cfg)
    "vote_mode": "trend", "normalize": "total", "min_hold": 5,
    "cooldown": 4, "exit_mode": "trail", "max_hold": 192, "dir_bars": 20,
    "confirm": 2, "trail": 0.3, "move_floor": 0.0003, "cost_aware": True,
}
DEFAULTS = {  # the consensus module defaults
    "vote_mode": "adaptive", "normalize": "participating", "min_hold": 3,
    "cooldown": 2, "exit_mode": "score", "max_hold": 0, "dir_bars": 0,
    "confirm": 1, "trail": 0.0, "move_floor": 0.0005, "cost_aware": False,
}


def build_entropy(cfg: dict):
    from entropy.bot.costs import CostModel, MarketClass, MarketCosts
    from entropy.bot.strategies.consensus import ConsensusStrategy

    costs = None
    if cfg["cost_aware"]:
        costs = CostModel(
            flat_fee_bps=1.0, flat_slippage_bps=1.0,
            market={
                MarketClass.EQUITY: MarketCosts(2.0, 2.0),
                MarketClass.CRYPTO_SPOT: MarketCosts(10.0, 3.0),
                MarketClass.CRYPTO_FUTURES: MarketCosts(5.0, 2.0),
            },
        )
    return ConsensusStrategy(
        symbols=None, bar_s=900.0, threshold=0.5, min_bars=35,
        weights={"ema": 0.35, "macd": 0.30, "rsi": 0.20, "bollinger": 0.15},
        move_floor=cfg["move_floor"], trend_er=0.35,
        vote_mode=cfg["vote_mode"], normalize=cfg["normalize"],
        min_participation=0.5,
        min_hold_bars=cfg["min_hold"], cooldown_bars=cfg["cooldown"],
        exit_mode=cfg["exit_mode"], max_hold_bars=cfg["max_hold"],
        long_only=False, regime_window=20, slope_lookback=5,
        direction_bars=cfg["dir_bars"], direction_min_slope=0.00002,
        confirm_bars=cfg["confirm"], trail_pct=cfg["trail"],
        regime_tilt=2.0, costs=costs, cost_edge_mult=1.0,
    )


def build_vendored(cfg: dict) -> KaosStrategy:
    return KaosStrategy(KaosConfig(
        threshold=0.5, min_bars=35,
        w_ema=0.35, w_macd=0.30, w_rsi=0.20, w_bollinger=0.15,
        move_floor=cfg["move_floor"], trend_er=0.35,
        vote_mode=cfg["vote_mode"], normalize=cfg["normalize"],
        min_participation=0.5,
        min_hold_bars=cfg["min_hold"], cooldown_bars=cfg["cooldown"],
        exit_mode=cfg["exit_mode"], max_hold_bars=cfg["max_hold"],
        long_only=False, regime_window=20, slope_lookback=5,
        direction_bars=cfg["dir_bars"], direction_min_slope=0.00002,
        confirm_bars=cfg["confirm"], trail_pct=cfg["trail"],
        regime_tilt=2.0, cost_aware=cfg["cost_aware"], cost_edge_mult=1.0,
    ))


def signals_match(a, b) -> bool:
    """Field-level parity: side + reason byte-equal, confidence/sigma tight."""
    if a.action != b.action:
        return False
    if a.reason != b.reason:
        return False
    if abs(a.strength - b.strength) > 1e-9:
        return False
    if (a.sigma is None) != (b.sigma is None):
        return False
    # SIM103 prefers a single return; the step-wise form documents each
    # parity criterion explicitly, so keep it and silence the rule.
    if a.sigma is not None and abs(a.sigma - b.sigma) > 1e-9 * max(1.0, a.sigma):  # noqa: SIM103
        return False
    return True


# ---- tests -----------------------------------------------------------------


@pytest.mark.parametrize("cfg_label", ["s20", "defaults"])
@ENTROPY_SKIP
def test_strategy_parity_vs_entropy(cfg_label):
    """Bar-by-bar signal parity over 24 seeds per config."""
    cfg = S20 if cfg_label == "s20" else DEFAULTS
    total = 0
    actions_seen: set[str] = set()
    for seed in range(24):
        closes = fixture_closes(seed)
        ref = build_entropy(cfg)
        mine = build_vendored(cfg)
        # Entropy consumes ticks; one tick per bucket end commits the
        # previous bar. A final tick in a NEW bucket flushes the last bar.
        ref_signals = []
        for i, c in enumerate(closes):
            ref_signals += ref.on_tick(SYM, c, (i + 1) * BAR_NS - 1, [])
        ref_signals += ref.on_tick(
            SYM, closes[-1], (len(closes) + 1) * BAR_NS - 1, [],
        )
        mine_signals = []
        for i, c in enumerate(closes):
            mine_signals += mine.on_bar(SYM, c, i * BAR_NS)
        assert len(ref_signals) == len(mine_signals), (
            f"seed {seed}: signal count {len(mine_signals)} != "
            f"{len(ref_signals)}"
        )
        for sig in ref_signals:
            actions_seen.add(sig.action)
        for k, (a, b) in enumerate(zip(ref_signals, mine_signals)):
            assert a.action == b.action, f"seed {seed} sig {k}: side"
            assert a.reason == b.reason, f"seed {seed} sig {k}: reason"
            assert abs(a.strength - b.strength) <= 1e-9
            assert (a.sigma is None) == (b.sigma is None)
            if a.sigma is not None:
                assert abs(a.sigma - b.sigma) <= 1e-9 * max(1.0, a.sigma)
        total += len(ref_signals)
    assert total >= 20, "fixture produced too few signals to be a real test"
    assert "enter_long" in actions_seen or "enter_short" in actions_seen
    assert "exit" in actions_seen


@ENTROPY_SKIP
def test_indicator_parity_vs_crocodile():
    """EMA/RSI/MACD bit-exact; Bollinger within 1e-12 relative."""
    from crocodile.core.analytics import indicators as croc

    rng = random.Random(4242)
    for vol in (0.005, 0.02, 0.06):
        closes: list[float] = []
        px = 34000.0
        for _ in range(220):
            px *= (1.0 + rng.gauss(0, vol))
            closes.append(px)
        for period in (9, 21, 26):
            assert croc.calculate_ema(closes, period) == vendored_ema(closes, period)
        assert croc.calculate_rsi(closes, 14) == vendored_rsi(closes, 14)
        ref_m, _, ref_h = croc.calculate_macd(closes)
        my_m, _, my_h = vendored_macd(closes)
        assert ref_m == my_m and ref_h == my_h
        scale = max(closes) - min(closes)
        for ref, got in zip(
            croc.calculate_bollinger_bands(closes, 20, 2.0),
            vendored_bb(closes, 20, 2.0),
        ):
            for a, b in zip(ref, got):
                if a is None:
                    assert b is None
                else:
                    assert abs(a - b) <= 1e-12 * scale


def test_vendored_strategy_always_runs():
    """Entropy-independent: the vendored layer fires signals and is
    deterministic (this test never skips)."""
    cfg = S20
    runs = []
    for _ in range(2):
        strat = build_vendored(cfg)
        sigs = []
        for i, c in enumerate(fixture_closes(3)):
            sigs += strat.on_bar(SYM, c, i * BAR_NS)
        runs.append([(s.action, s.reason, round(s.strength, 12)) for s in sigs])
    assert runs[0] == runs[1], "vendored strategy must be deterministic"
    actions = {a for a, _, _ in runs[0]}
    assert "enter_long" in actions or "enter_short" in actions
    assert len(runs[0]) >= 1


def test_vendored_config_validation():
    with pytest.raises(ValueError):
        KaosStrategy(KaosConfig(threshold=0.0))
    with pytest.raises(ValueError):
        KaosStrategy(KaosConfig(vote_mode="nope"))
    with pytest.raises(ValueError):
        KaosStrategy(KaosConfig(ema_fast=30, ema_slow=21))
    with pytest.raises(ValueError):
        KaosStrategy(KaosConfig(max_hold_bars=2, min_hold_bars=5))


def test_vendored_sigma_barriers_mapping():
    """20-sigma stop / 4-sigma take-profit — the locked A2 baseline."""
    from showme.bots.kaos.adapter import KaosDecision

    assert S20["cost_aware"] is True  # the shipped config gates on costs
    dec = KaosDecision(
        symbol="X", venue_id="crypto", market="crypto-futures",
        risk_profile="crypto", kind="entry", side="long", price=100.0,
        bar_index=0, bar_time="t", reason="r", strength=0.6, sigma=0.002,
        stop_loss_pct=20 * 0.002 * 100, take_profit_pct=4 * 0.002 * 100,
    )
    assert dec.stop_loss_pct == pytest.approx(4.0)   # 20 sigma = 4% away
    assert dec.take_profit_pct == pytest.approx(0.8)  # 4 sigma = 0.8% away
    assert math.isfinite(dec.strength)
