"""KAOS engine configuration — the SHIPPED s20 live config, vendored.

Vendored from KAOS engine (Entropy repo) pure strategy layer,
Entropy HEAD: edfa322 — parity-tested.

Values are VERBATIM from ``scripts/entropy_live_paper.py::build_cfg``
(the shipped s20 Round-2 winner the live KAOS bot runs with) and
``src/entropy/bot/config.py::ConsensusConfig`` defaults. The risk-layer
sigma barriers (stop 20-sigma / take-profit 4-sigma, the locked A2
baseline) live here as ``SIGMA_STOP_MULT`` / ``SIGMA_TP_MULT``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# A2 baseline barriers (HAFIZA 2026-09-09, locked): stop = 20 sigma,
# take-profit = 4 sigma, anchored on the entry bar's per-bar return RMS
# carried by the entry signal. Deliberately asymmetric: the strategy's
# edge is buying/selling momentum bursts; the far stop lets the trail work.
SIGMA_STOP_MULT = 20.0
SIGMA_TP_MULT = 4.0

# Default bot name (frozen in the campaign CONTRACT.md, shared with the UI).
DEFAULT_KAOS_BOT_NAME = "KAOS Multibot"
DEFAULT_KAOS_SPEC_ID = "kaos-multibot"
DEFAULT_KAOS_TIMEFRAME = "15m"
DEFAULT_KAOS_TICK_SECONDS = 60

# Default universes. Crypto: the 20 liquid USD-M majors of the live runner
# (scripts/entropy_live_paper.py DEFAULT_SYMBOLS ~:119) mapped to ccxt
# binanceusdm linear-perp symbols. NASDAQ: the first 20 tickers of
# src/entropy/feeds/equities/universe.py LIVE_UNIVERSE (INDICES + MEGACAP +
# SEMIS[:8]).
CRYPTO_DEFAULT_SYMBOLS: tuple[str, ...] = (
    "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "BNB/USDT:USDT",
    "XRP/USDT:USDT", "DOGE/USDT:USDT", "ADA/USDT:USDT", "LINK/USDT:USDT",
    "AVAX/USDT:USDT", "SUI/USDT:USDT", "NEAR/USDT:USDT", "ENA/USDT:USDT",
    "LTC/USDT:USDT", "DOT/USDT:USDT", "APT/USDT:USDT", "ARB/USDT:USDT",
    "OP/USDT:USDT", "ATOM/USDT:USDT", "FIL/USDT:USDT", "SEI/USDT:USDT",
)
NASDAQ_DEFAULT_SYMBOLS: tuple[str, ...] = (
    "SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META",
    "AVGO", "TSLA", "BRKB", "LLY", "AMD", "INTC", "MU", "QCOM", "TXN",
    "ASML", "AMAT",
)

DEFAULT_VENUES: list[dict[str, object]] = [
    {
        "id": "crypto",
        "exchange_id": "binanceusdm",
        "market": "crypto-futures",
        "symbols": list(CRYPTO_DEFAULT_SYMBOLS),
        "risk_profile": "crypto",
    },
    {
        "id": "nasdaq",
        "exchange_id": "alpaca",
        "market": "us-equities",
        "symbols": list(NASDAQ_DEFAULT_SYMBOLS),
        "risk_profile": "equity",
    },
]


@dataclass(frozen=True)
class KaosCosts:
    """Vendored per-market cost model (mirrors entropy.bot.costs defaults).

    Flat fallback fee/slippage 1.0/1.0 bps; per-market overrides are the
    researched taker schedules (Binance spot 10/3, USDT-M futures 5/2,
    US equities 2/2 bps). Symbols classified exactly like
    ``entropy.bot.costs.classify_symbol`` so the cost gates land on the
    same regime as the live runner's symbols do.
    """

    flat_fee_bps: float = 1.0
    flat_slippage_bps: float = 1.0
    equity_fee_bps: float | None = 2.0
    equity_slippage_bps: float | None = 2.0
    crypto_spot_fee_bps: float | None = 10.0
    crypto_spot_slippage_bps: float | None = 3.0
    crypto_futures_fee_bps: float | None = 5.0
    crypto_futures_slippage_bps: float | None = 2.0


@dataclass(frozen=True)
class KaosConfig:
    """Every knob of the vendored consensus strategy (s20 shipped values)."""

    # --- scoring ----------------------------------------------------------
    threshold: float = 0.5
    min_bars: int = 35
    vote_mode: str = "trend"            # adaptive | trend | mean_revert | legacy
    normalize: str = "total"            # participating | total
    min_participation: float = 0.5
    w_ema: float = 0.35
    w_macd: float = 0.30
    w_rsi: float = 0.20
    w_bollinger: float = 0.15
    # --- indicators -------------------------------------------------------
    ema_fast: int = 9
    ema_slow: int = 21
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    rsi_period: int = 14
    rsi_low: float = 30.0
    rsi_high: float = 70.0
    rsi_trend_low: float = 45.0
    rsi_trend_high: float = 55.0
    bb_period: int = 20
    bb_std: float = 2.0
    bb_low: float = 0.05
    bb_high: float = 0.95
    bb_trend_low: float = 0.20
    bb_trend_high: float = 0.80
    # --- regime -----------------------------------------------------------
    move_floor: float = 0.0003
    trend_er: float = 0.35
    regime_window: int = 20
    slope_lookback: int = 5
    direction_bars: int = 20
    direction_min_slope: float = 0.00002
    confirm_bars: int = 2
    trail_pct: float = 0.3
    regime_tilt: float = 2.0
    # --- position lifecycle -----------------------------------------------
    min_hold_bars: int = 5
    cooldown_bars: int = 4
    exit_mode: str = "trail"            # score | trend_flip | either | hold | trail
    max_hold_bars: int = 192
    long_only: bool = False             # live KAOS: shorts OPEN (2026-09-08)
    # --- costs ------------------------------------------------------------
    cost_aware: bool = True
    cost_edge_mult: float = 1.0
    costs: KaosCosts = field(default_factory=KaosCosts)
    # --- cadence (recorded; the showme runner is bar-driven) --------------
    bar_s: float = 900.0

    @property
    def weights(self) -> dict[str, float]:
        return {
            "ema": self.w_ema, "macd": self.w_macd,
            "rsi": self.w_rsi, "bollinger": self.w_bollinger,
        }


def default_config() -> KaosConfig:
    """The shipped s20 configuration (live KAOS parity default)."""
    return KaosConfig()
