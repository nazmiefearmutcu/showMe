"""Vendored KAOS consensus strategy — pure bar-to-signal layer.

Vendored from KAOS engine (Entropy repo) pure strategy layer,
Entropy HEAD: edfa322 — parity-tested.

Port of ``src/entropy/bot/strategies/consensus.py`` (ConsensusStrategy):
the weighted multi-indicator consensus (EMA cross, MACD histogram, RSI,
Bollinger %B) with regime-aware vote mapping, participation normalization,
confirm/cooldown/min-hold/trail lifecycle and the cost-aware entry gates.
The math, constants, thresholds and reason strings are preserved EXACTLY;
``tests/test_kaos_parity.py`` runs this port and the real Entropy
implementation over identical fixture bars and asserts identical signals.

Differences from upstream (by design, behaviour-preserving):
* bar-driven input. Upstream aggregates ticks into buckets via
  ``on_tick`` and evaluates each *completed* bar; showme's runner works on
  completed OHLCV bars, so :meth:`KaosStrategy.on_bar` performs the exact
  committed-bar bookkeeping upstream does on bucket roll (append close,
  advance bar counters, evaluate).
* no exchange/IO, no engine Event/msgspec dependency. Signals are plain
  dataclasses; actions are the upstream strings
  ("enter_long" / "enter_short" / "exit").
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

from .config import KaosConfig
from .costs import E_ABS_MOVE, CostModel
from .indicators import (
    calculate_bollinger_bands,
    calculate_ema,
    calculate_macd,
    calculate_rsi,
)

_CLOSES_MAXLEN = 512

DEFAULT_WEIGHTS: dict[str, float] = {
    "ema": 0.35,
    "macd": 0.30,
    "rsi": 0.20,
    "bollinger": 0.15,
}

VOTE_MODES = ("adaptive", "trend", "mean_revert", "legacy")
NORMALIZE_MODES = ("participating", "total")
EXIT_MODES = ("score", "trend_flip", "either", "hold", "trail")

_VOTE_CHAR = {1: "+", 0: "0", -1: "-"}

#: Signal actions (upstream SignalAction string values).
ENTER_LONG = "enter_long"
ENTER_SHORT = "enter_short"
EXIT = "exit"


@dataclass(frozen=True, slots=True)
class KaosSignal:
    """Upstream ``entropy.bot.signals.Signal`` shape, stdlib-only."""

    symbol: str
    action: str
    strength: float  # 0.0-1.0 confidence
    reason: str
    ts_ns: int
    strategy: str = "consensus"
    sigma: float | None = None


@dataclass(frozen=True, slots=True)
class Votes:
    """One -1/0/+1 vote per indicator for a completed bar."""

    ema: int
    macd: int
    rsi: int
    bollinger: int


@dataclass(frozen=True, slots=True)
class Regime:
    """Movement / efficiency classification of the last completed bar."""

    move: float
    efficiency: float
    slope: float
    tradeable: bool
    trending: bool
    trend_dir: int = 0

    @property
    def label(self) -> str:
        if not self.tradeable:
            return "chop"
        return "trend" if self.trending else "range"


def score_votes(
    votes: Votes,
    weights: dict[str, float],
    *,
    normalize: str = "total",
    min_participation: float = 0.0,
) -> float:
    """Weighted consensus score in [-1, 1] (upstream verbatim)."""
    total = sum(abs(w) for w in weights.values())
    if total <= 0.0:
        return 0.0
    raw = (
        weights.get("ema", 0.0) * votes.ema
        + weights.get("macd", 0.0) * votes.macd
        + weights.get("rsi", 0.0) * votes.rsi
        + weights.get("bollinger", 0.0) * votes.bollinger
    )
    if normalize != "participating":
        return raw / total
    participating = (
        abs(weights.get("ema", 0.0)) * (votes.ema != 0)
        + abs(weights.get("macd", 0.0)) * (votes.macd != 0)
        + abs(weights.get("rsi", 0.0)) * (votes.rsi != 0)
        + abs(weights.get("bollinger", 0.0)) * (votes.bollinger != 0)
    )
    if participating <= 0.0 or participating < min_participation * total:
        return 0.0
    return raw / participating


def tilt_weights(
    weights: dict[str, float], *, trending: bool, tilt: float
) -> dict[str, float]:
    """Re-weight the trend/oscillator blocks for the current regime."""
    lead, follow = (tilt, 1.0) if trending else (1.0, tilt)
    return {
        "ema": weights.get("ema", 0.0) * lead,
        "macd": weights.get("macd", 0.0) * lead,
        "rsi": weights.get("rsi", 0.0) * follow,
        "bollinger": weights.get("bollinger", 0.0) * follow,
    }


def trend_score(votes: Votes, weights: dict[str, float]) -> float:
    """Score of the trend block (EMA + MACD) alone, in [-1, 1]."""
    w = abs(weights.get("ema", 0.0)) + abs(weights.get("macd", 0.0))
    if w <= 0.0:
        return 0.0
    return (weights.get("ema", 0.0) * votes.ema + weights.get("macd", 0.0) * votes.macd) / w


class _SymbolState:
    __slots__ = (
        "bars_in_trade",
        "bars_since_exit",
        "closes",
        "direction",
        "last_close",
        "peak",
        "streak",
        "streak_dir",
    )

    def __init__(self) -> None:
        self.closes: deque[float] = deque(maxlen=_CLOSES_MAXLEN)
        # Upstream also tracks the tick bucket/pending state; the bar-driven
        # port receives only completed bars, so every on_bar call IS a
        # commit and those fields have no equivalent.
        self.direction: int = 0
        self.bars_in_trade: int = 0
        self.bars_since_exit: int = 1 << 30
        self.streak: int = 0
        self.streak_dir: int = 0
        self.last_close: float = 0.0
        self.peak: float = 0.0


class KaosStrategy:
    """Bar-driven port of ``ConsensusStrategy`` (see module docstring)."""

    name = "consensus"

    def __init__(self, cfg: KaosConfig | None = None) -> None:
        cfg = cfg or KaosConfig()
        threshold = cfg.threshold
        if not 0.0 < threshold <= 1.0:
            raise ValueError("threshold must be in (0, 1]")
        if cfg.vote_mode not in VOTE_MODES:
            raise ValueError(f"vote_mode must be one of {VOTE_MODES}")
        if cfg.normalize not in NORMALIZE_MODES:
            raise ValueError(f"normalize must be one of {NORMALIZE_MODES}")
        if cfg.exit_mode not in EXIT_MODES:
            raise ValueError(f"exit_mode must be one of {EXIT_MODES}")
        if min(cfg.ema_fast, cfg.ema_slow, cfg.macd_fast, cfg.macd_slow,
               cfg.macd_signal, cfg.rsi_period, cfg.bb_period) < 1:
            raise ValueError("indicator periods must be >= 1")
        if cfg.ema_fast >= cfg.ema_slow:
            raise ValueError("ema_fast must be shorter than ema_slow")
        if cfg.macd_fast >= cfg.macd_slow:
            raise ValueError("macd_fast must be shorter than macd_slow")
        if cfg.cost_edge_mult <= 0.0:
            raise ValueError("cost_edge_mult must be positive")
        if cfg.confirm_bars < 1:
            raise ValueError("confirm_bars must be >= 1")
        if cfg.trail_pct < 0.0:
            raise ValueError("trail_pct must be >= 0")
        if cfg.max_hold_bars < 0:
            raise ValueError("max_hold_bars must be >= 0 (0 = off)")
        if cfg.max_hold_bars > 0 and cfg.max_hold_bars < max(0, cfg.min_hold_bars):
            raise ValueError("max_hold_bars must be 0 (off) or >= min_hold_bars")

        self.cfg = cfg
        self.threshold = threshold
        self.weights: dict[str, float] = dict(cfg.weights)
        self.move_floor = cfg.move_floor
        self.trend_er = cfg.trend_er
        self.ema_fast, self.ema_slow = cfg.ema_fast, cfg.ema_slow
        self.macd_fast, self.macd_slow, self.macd_signal = (
            cfg.macd_fast, cfg.macd_slow, cfg.macd_signal,
        )
        self.rsi_period, self.rsi_low, self.rsi_high = cfg.rsi_period, cfg.rsi_low, cfg.rsi_high
        self.rsi_trend_low, self.rsi_trend_high = cfg.rsi_trend_low, cfg.rsi_trend_high
        self.bb_period, self.bb_std = cfg.bb_period, cfg.bb_std
        self.bb_low, self.bb_high = cfg.bb_low, cfg.bb_high
        self.bb_trend_low, self.bb_trend_high = cfg.bb_trend_low, cfg.bb_trend_high
        self.vote_mode = cfg.vote_mode
        self._vote_mode_for: dict[str, str] = {}
        if cfg.vote_mode == "legacy" or "legacy" in self._vote_mode_for.values():
            normalize, min_participation = "total", 0.0
        else:
            normalize, min_participation = cfg.normalize, cfg.min_participation
        self.normalize = normalize
        self.min_participation = min_participation
        self.min_hold_bars = max(0, cfg.min_hold_bars)
        self.cooldown_bars = max(0, cfg.cooldown_bars)
        self.exit_mode = cfg.exit_mode
        self.max_hold_bars = cfg.max_hold_bars
        self.long_only = cfg.long_only
        self.regime_window = max(2, cfg.regime_window)
        self.slope_lookback = max(1, cfg.slope_lookback)
        self.direction_bars = cfg.direction_bars
        self.direction_min_slope = cfg.direction_min_slope
        self.confirm_bars = cfg.confirm_bars
        self.trail_pct = cfg.trail_pct
        self.regime_tilt = cfg.regime_tilt
        self.costs: CostModel | None = CostModel(cfg.costs) if cfg.cost_aware else None
        self.cost_edge_mult = cfg.cost_edge_mult
        self._last_move_rms: dict[str, float] = {}
        self.min_bars = max(
            cfg.min_bars, cfg.ema_slow, cfg.macd_slow + cfg.macd_signal,
            cfg.rsi_period + 1, cfg.bb_period, self.regime_window + 1,
            self.slope_lookback + 1,
            self.direction_bars + 1 if self.direction_bars > 0 else 0,
        )
        self._states: dict[str, _SymbolState] = {}
        self.last_regime: dict[str, Regime] = {}

    # ---- position lifecycle ---------------------------------------------

    def on_position_closed(self, symbol: str, reason: str = "") -> None:
        """Re-arm after a position ended without this strategy asking."""
        st = self._states.get(symbol)
        if st is None or st.direction == 0:
            return
        st.direction = 0
        st.bars_in_trade = 0
        st.bars_since_exit = 0
        st.peak = 0.0
        st.last_close = 0.0

    # ---- hot path --------------------------------------------------------

    def on_bar(self, symbol: str, close: float, ts_ns: int) -> list[KaosSignal]:
        """Feed one COMPLETED bar close; returns that bar's signals (if any).

        Mirrors upstream ``on_tick`` on a bucket roll: the completed close is
        appended and the bar counters advance, then ``_evaluate`` runs. Bars
        must be fed in order; the strategy keeps <= 512 closes per symbol.
        """
        st = self._states.get(symbol)
        if st is None:
            st = _SymbolState()
            self._states[symbol] = st
        st.closes.append(float(close))
        if st.direction != 0:
            st.bars_in_trade += 1
        elif st.bars_since_exit < (1 << 30):
            st.bars_since_exit += 1
        return self._evaluate(symbol, ts_ns, st)

    # ---- evaluation (completed bars only) --------------------------------

    def _mode_for(self, symbol: str) -> str:
        mode = self._vote_mode_for.get(symbol)
        if mode is None and ":" in symbol:
            mode = self._vote_mode_for.get(symbol.split(":", 1)[1])
        return mode if mode is not None else self.vote_mode

    def _evaluate(self, symbol: str, ts_ns: int, st: _SymbolState) -> list[KaosSignal]:
        closes = list(st.closes)
        if len(closes) < self.min_bars:
            return []

        ema_fast = calculate_ema(closes, self.ema_fast)
        ema_slow = calculate_ema(closes, self.ema_slow)
        _, _, macd_hist = calculate_macd(
            closes, self.macd_fast, self.macd_slow, self.macd_signal
        )
        rsi = calculate_rsi(closes, self.rsi_period)
        bb_upper, _, bb_lower = calculate_bollinger_bands(closes, self.bb_period, self.bb_std)

        regime = self._regime(closes, ema_slow)
        self.last_regime[symbol] = regime
        close = closes[-1]
        pct_b = _percent_b(close, bb_upper[-1], bb_lower[-1])

        mode = self._mode_for(symbol)
        momentum_read = mode == "trend" or (
            mode == "adaptive" and regime.trending
        )
        if momentum_read:
            rsi_vote = _momentum_vote(rsi[-1], low=self.rsi_trend_low, high=self.rsi_trend_high)
            bb_vote = _momentum_vote(pct_b, low=self.bb_trend_low, high=self.bb_trend_high)
        else:
            rsi_vote = _band_vote(rsi[-1], low=self.rsi_low, high=self.rsi_high)
            bb_vote = _band_vote(pct_b, low=self.bb_low, high=self.bb_high)

        votes = Votes(
            ema=_cmp_vote(ema_fast[-1], ema_slow[-1]),
            macd=_sign_vote(macd_hist[-1]),
            rsi=rsi_vote,
            bollinger=bb_vote,
        )
        weights = (
            self.weights if mode == "legacy"
            else tilt_weights(self.weights, trending=regime.trending, tilt=self.regime_tilt)
        )
        score = score_votes(
            votes, weights,
            normalize=self.normalize, min_participation=self.min_participation,
        )
        reason = (
            f"consensus {score:.2f} [{regime.label}] "
            f"(ema{_VOTE_CHAR[votes.ema]} macd{_VOTE_CHAR[votes.macd]}"
            f" rsi{_VOTE_CHAR[votes.rsi]} bb{_VOTE_CHAR[votes.bollinger]})"
        )

        if st.direction == 0:
            if st.bars_since_exit < self.cooldown_bars:
                return []
            qualifying = abs(score) >= self.threshold and regime.tradeable
            if qualifying and self.costs is not None:
                # Cost gates: upstream amortizes the round-trip cost over the
                # regime window (per-bar requirement k*C/W) and adds a
                # sigma floor scaled the same way. Verbatim.
                window = max(1.0, float(self.regime_window))
                floor = max(
                    self.move_floor,
                    self.costs.minimum_move(symbol, self.cost_edge_mult) / window,
                )
                if regime.move <= floor:
                    qualifying = False
                else:
                    rms = self._bar_move_rms(closes)
                    self._last_move_rms[symbol] = rms
                    sigma_floor = (
                        self.costs.sigma_gate(symbol, self.cost_edge_mult) / window
                    )
                    if rms < sigma_floor:
                        qualifying = False
            if not qualifying:
                st.streak = 0
                st.streak_dir = 0
                return []
            sgn = 1 if score > 0 else -1
            if self.long_only and sgn < 0:
                st.streak = 0
                st.streak_dir = 0
                return []
            if st.streak_dir != sgn:
                st.streak, st.streak_dir = 1, sgn
            else:
                st.streak += 1
            if self.direction_bars > 0 and (
                regime.trend_dir == 0 or (sgn > 0) != (regime.trend_dir > 0)
            ):
                st.streak = 0
                st.streak_dir = 0
                return []
            if st.streak < self.confirm_bars:
                return []
            st.streak = 0
            st.streak_dir = 0
            st.direction = sgn
            st.bars_in_trade = 0
            st.peak = 0.0
            st.last_close = 0.0
            sigma = self._bar_move_rms(closes)
            self._last_move_rms[symbol] = sigma
            action = ENTER_LONG if sgn > 0 else ENTER_SHORT
            return [KaosSignal(symbol=symbol, action=action, strength=abs(score),
                               reason=reason, ts_ns=ts_ns, strategy=self.name,
                               sigma=sigma)]

        close = closes[-1]
        st.last_close = close
        if st.direction > 0:
            st.peak = max(st.peak, close) if st.peak > 0.0 else close
        else:
            st.peak = min(st.peak, close) if st.peak > 0.0 else close
        if self.max_hold_bars > 0 and st.bars_in_trade >= self.max_hold_bars:
            held = st.bars_in_trade
            st.direction = 0
            st.bars_in_trade = 0
            st.bars_since_exit = 0
            return [KaosSignal(symbol=symbol, action=EXIT, strength=1.0,
                               reason=f"time stop after {held} bars "
                                      f"(max_hold_bars={self.max_hold_bars})",
                               ts_ns=ts_ns, strategy=self.name)]
        if st.bars_in_trade < self.min_hold_bars:
            return []
        if self.costs is not None:
            self._last_move_rms[symbol] = self._bar_move_rms(closes)
        if not self._should_exit(score, votes, st.direction, symbol):
            return []
        st.direction = 0
        st.bars_in_trade = 0
        st.bars_since_exit = 0
        return [KaosSignal(symbol=symbol, action=EXIT, strength=1.0,
                           reason=reason, ts_ns=ts_ns, strategy=self.name)]

    def _should_exit(self, score: float, votes: Votes, direction: int,
                     symbol: str | None = None) -> bool:
        """Hysteresis exit band (upstream verbatim, incl. cost buffer)."""
        band = self.threshold / 2.0
        if self.costs is not None and symbol is not None:
            rms = self._last_move_rms.get(symbol, 0.0)
            cap = 0.3 * self.threshold
            if rms > 0.0:
                kc = self.costs.minimum_move(symbol, self.cost_edge_mult)
                band -= min(cap, kc / (E_ABS_MOVE * rms))
            else:
                band -= cap
            band = max(band, self.threshold * 0.05)
        by_score = (direction > 0 and score < band) or (direction < 0 and score > -band)
        if self.exit_mode == "score":
            return by_score
        ts = trend_score(votes, self.weights)
        by_trend = (direction > 0 and ts < 0.0) or (direction < 0 and ts > 0.0)
        if self.exit_mode == "hold":
            return False
        if self.exit_mode == "trail":
            st = self._states.get(symbol or "")
            if st is None or st.peak <= 0.0 or st.last_close <= 0.0:
                return False
            px = st.last_close
            if direction > 0:
                return px <= st.peak * (1.0 - self.trail_pct)
            return px >= st.peak * (1.0 + self.trail_pct)
        if self.exit_mode == "trend_flip":
            return by_trend
        return by_score or by_trend

    def _bar_move_rms(self, closes: list[float]) -> float:
        """Per-bar move magnitude (RMS of returns) over the regime window."""
        n = len(closes)
        window = min(self.regime_window, n - 1)
        if window < 2:
            return 0.0
        seg = closes[n - window - 1:]
        rets = [seg[i] / seg[i - 1] - 1.0 for i in range(1, len(seg))]
        return math.sqrt(sum(r * r for r in rets) / len(rets))

    def _regime(self, closes: list[float],
                ema_slow: list[float | None]) -> Regime:
        """Classify the bar: movement gates entries, efficiency picks the read."""
        n = len(closes)
        window = min(self.regime_window, n - 1)
        if window < 2:
            return Regime(move=0.0, efficiency=0.0, slope=0.0,
                          tradeable=False, trending=False)
        seg = closes[n - window - 1:]
        rets = [seg[i] / seg[i - 1] - 1.0 for i in range(1, len(seg))]
        move = sum(abs(r) for r in rets) / len(rets)
        path = sum(abs(seg[i] - seg[i - 1]) for i in range(1, len(seg)))
        efficiency = abs(seg[-1] - seg[0]) / path if path > 0.0 else 0.0

        slope = 0.0
        lb = self.slope_lookback
        if len(ema_slow) > lb and closes[-1] > 0.0:
            e_now, e_then = ema_slow[-1], ema_slow[-1 - lb]
            if e_now is not None and e_then is not None:
                slope = (e_now - e_then) / lb / closes[-1]
        trend_dir = 0
        db = self.direction_bars
        if db > 0 and len(ema_slow) > db and closes[-1] > 0.0:
            e_now, e_then = ema_slow[-1], ema_slow[-1 - db]
            if e_now is not None and e_then is not None:
                dslope = (e_now - e_then) / db / closes[-1]
                if abs(dslope) >= self.direction_min_slope:
                    trend_dir = 1 if dslope > 0.0 else -1
        return Regime(
            move=move, efficiency=efficiency, slope=slope, trend_dir=trend_dir,
            tradeable=move > self.move_floor,
            trending=efficiency >= self.trend_er,
        )


# ---- pure vote helpers (upstream verbatim) --------------------------------


def _cmp_vote(fast: float | None, slow: float | None) -> int:
    if fast is None or slow is None:
        return 0
    return 1 if fast > slow else (-1 if fast < slow else 0)


def _sign_vote(value: float | None) -> int:
    if value is None:
        return 0
    return 1 if value > 0.0 else (-1 if value < 0.0 else 0)


def _band_vote(value: float | None, low: float, high: float) -> int:
    """Mean-revert vote: below `low` -> +1 (long), above `high` -> -1 (short)."""
    if value is None:
        return 0
    return 1 if value < low else (-1 if value > high else 0)


def _momentum_vote(value: float | None, low: float, high: float) -> int:
    """Momentum vote: above `high` -> +1 (long), below `low` -> -1 (short)."""
    if value is None:
        return 0
    return 1 if value > high else (-1 if value < low else 0)


def _percent_b(close: float, upper: float | None, lower: float | None) -> float | None:
    if upper is None or lower is None or upper <= lower:
        return None
    return (close - lower) / (upper - lower)
