"""Showme adapter — OHLCV frames in, KAOS bot decisions out.

Vendored from KAOS engine (Entropy repo) pure strategy layer,
Entropy HEAD: edfa322 — parity-tested.

``evaluate`` replays the vendored consensus strategy over each symbol's
fetched OHLCV window (fresh instance per call — deterministic and
restart-safe, mirroring how ``evaluate_last_bar`` serves spec bots) and
maps the last completed bar's signal to a :class:`KaosDecision`, the shape
``BotRunner`` routes through the EXISTING dispatch (guards, signal_log,
PERF, pills). One decision = one symbol entry/exit signal.

Honesty rules honored here:
* decisions carry the KAOS consensus reason verbatim;
* the 20-sigma stop / 4-sigma take-profit barriers (locked A2 baseline)
  are attached as percent fields computed from the entry bar's sigma;
* symbols the runner already holds are only allowed EXIT decisions and
  flat symbols only ENTRY decisions (no double entries, no phantom exits).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .config import SIGMA_STOP_MULT, SIGMA_TP_MULT, KaosConfig, default_config
from .strategy import ENTER_LONG, EXIT, KaosStrategy

LOG = logging.getLogger("showme.bots.kaos")

#: Minimum useful window: the strategy needs >= cfg.min_bars closes; anything
#: shorter can only produce abstentions (upstream returns [] the same way).
_DEFAULT_WINDOW = 200


@dataclass(frozen=True)
class KaosDecision:
    """One actionable KAOS signal, shaped for the existing runner dispatch."""

    symbol: str
    venue_id: str
    market: str
    risk_profile: str
    kind: str                 # "entry" | "exit"
    side: str                 # "long" | "short"
    price: float
    bar_index: int
    bar_time: str
    reason: str
    strength: float
    sigma: float | None
    stop_loss_pct: float | None   # 20 * sigma * 100 (entries; None on exits)
    take_profit_pct: float | None  # 4 * sigma * 100 (entries; None on exits)
    regime: str = ""
    score: float = 0.0

    @property
    def details(self) -> dict[str, Any]:
        return {
            "engine": "kaos",
            "regime": self.regime,
            "strength": self.strength,
            "sigma": self.sigma,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
        }


def evaluate(
    bars_by_symbol: dict[str, pd.DataFrame],
    venue: Any,
    cfg: KaosConfig | None = None,
    *,
    in_position_by_symbol: dict[str, dict[str, Any]] | None = None,
) -> list[KaosDecision]:
    """Evaluate every symbol's bar window for one venue; return decisions.

    ``bars_by_symbol`` maps symbol -> OHLCV DataFrame (lowercase columns,
    UTC datetime index, incomplete last bar already dropped by
    ``bots.ohlcv.fetch_ohlcv``). ``venue`` is a ``BotRecord.venues`` entry
    (duck-typed: ``id`` / ``market`` / ``symbols`` / ``risk_profile``).
    ``in_position_by_symbol`` maps symbol -> {"entry": SignalEntry, ...} for
    symbols the runner currently holds.

    Per-symbol evaluation errors are isolated: a failing symbol is skipped
    (logged) and can never block the rest of the venue's universe.
    """
    cfg = cfg or default_config()
    in_pos = in_position_by_symbol or {}
    decisions: list[KaosDecision] = []
    for symbol in getattr(venue, "symbols", []) or []:
        held_state = in_pos.get(symbol)
        try:
            decision = _evaluate_symbol(
                symbol, bars_by_symbol.get(symbol), venue, cfg,
                held_state=held_state,
            )
        except Exception as exc:  # noqa: BLE001
            LOG.warning("kaos: evaluation failed for %s on venue %s: %s",
                        symbol, getattr(venue, "id", "?"), exc)
            continue
        if decision is not None:
            decisions.append(decision)
    return decisions


def _evaluate_symbol(
    symbol: str,
    df: pd.DataFrame | None,
    venue: Any,
    cfg: KaosConfig,
    *,
    held_state: dict[str, Any] | None,
) -> KaosDecision | None:
    if df is None or df.empty or "close" not in df.columns:
        return None
    closes = [float(v) for v in df["close"].tolist()]
    if len(closes) < 2:
        return None
    strategy = KaosStrategy(cfg)
    ts_ns_last = int(df.index[-1].value) if hasattr(df.index[-1], "value") else 0
    signals: list = []
    for i, close in enumerate(closes):
        signals = strategy.on_bar(symbol, close, ts_ns_last - (len(closes) - 1 - i))
    if not signals:
        return None
    signal = signals[-1]  # the last completed bar's signal (replay may chain)
    regime = strategy.last_regime.get(symbol)
    price = closes[-1]
    bar_time = str(df.index[-1])
    bar_index = len(df) - 1
    held = held_state is not None

    if signal.action == EXIT:
        if not held:
            return None  # phantom exit: runner holds nothing on this symbol
        held_side = str((held_state or {}).get("side") or "long")
        return KaosDecision(
            symbol=symbol, venue_id=str(getattr(venue, "id", "")),
            market=str(getattr(venue, "market", "")),
            risk_profile=str(getattr(venue, "risk_profile", "")),
            kind="exit", side=held_side,
            price=price, bar_index=bar_index, bar_time=bar_time,
            reason=signal.reason, strength=signal.strength,
            sigma=None, stop_loss_pct=None, take_profit_pct=None,
            regime=regime.label if regime else "",
        )
    if held:
        return None  # already in a position on this symbol — never double
    side = "long" if signal.action == ENTER_LONG else "short"
    sigma = float(signal.sigma) if signal.sigma is not None else None
    stop_pct = SIGMA_STOP_MULT * sigma * 100.0 if sigma else None
    tp_pct = SIGMA_TP_MULT * sigma * 100.0 if sigma else None
    return KaosDecision(
        symbol=symbol, venue_id=str(getattr(venue, "id", "")),
        market=str(getattr(venue, "market", "")),
        risk_profile=str(getattr(venue, "risk_profile", "")),
        kind="entry", side=side,
        price=price, bar_index=bar_index, bar_time=bar_time,
        reason=signal.reason, strength=signal.strength,
        sigma=sigma, stop_loss_pct=stop_pct, take_profit_pct=tp_pct,
        regime=regime.label if regime else "",
        score=signal.strength,
    )
