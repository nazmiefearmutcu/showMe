"""Vendored execution-cost model — pure math port of ``entropy.bot.costs``.

Vendored from KAOS engine (Entropy repo) pure strategy layer,
Entropy HEAD: edfa322 — parity-tested.

Only the pieces the PURE strategy layer consumes are ported:
``E_ABS_MOVE``, market classification, ``MarketCosts.round_trip`` /
``minimum_move`` / ``sigma_gate``, and ``CostModel.for_symbol`` /
``minimum_move`` / ``sigma_gate``. The equity universe membership check is
served by the vendored NASDAQ default universe (the strategy only ever sees
symbols the showme venues feed it).
"""
from __future__ import annotations

import enum
import math
import re

from .config import NASDAQ_DEFAULT_SYMBOLS, KaosCosts

#: E|X| for X ~ N(0, sigma): sqrt(2/pi) * sigma — the expected per-bar move.
E_ABS_MOVE = math.sqrt(2.0 / math.pi)

_CRYPTO_QUOTES = (
    "USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USDP", "DAI",
    "BTC", "ETH", "BNB", "XRP", "SOL", "DOGE", "ADA", "AVAX",
    "LINK", "DOT", "MATIC", "LTC", "BCH", "TRX", "SHIB", "EUR", "TRY",
)

_DATED_FUTURES_RE = re.compile(r"_\d{6}$")

_EQUITY_UNIVERSE = frozenset(NASDAQ_DEFAULT_SYMBOLS)


class MarketClass(enum.StrEnum):
    EQUITY = "equity"
    CRYPTO_SPOT = "crypto_spot"
    CRYPTO_FUTURES = "crypto_futures"


def classify_symbol(symbol: str, *, market_hint: str | None = None) -> MarketClass:
    """Map a symbol to its cost regime (entropy.bot.costs.classify_symbol).

    ``market_hint`` ("crypto-futures" | "us-equities") comes from the showme
    VenueSpec when the caller knows the venue market explicitly; it maps
    deterministically onto the same two crypto classes the Entropy
    classifier distinguishes. Without a hint the classification follows the
    vendored Entropy logic (venue prefixes, then universe membership, then
    suffix heuristics).
    """
    if market_hint == "crypto-futures":
        return MarketClass.CRYPTO_FUTURES
    if market_hint == "us-equities":
        return MarketClass.EQUITY
    low = symbol.lower()
    if low.startswith(("binance-futures", "futures:")):
        return MarketClass.CRYPTO_FUTURES
    if low.startswith(
        ("binance-spot", "spot:", "coinbase:", "coinbase-spot:", "crypto:")
    ):
        return MarketClass.CRYPTO_SPOT
    if symbol in _EQUITY_UNIVERSE:
        return MarketClass.EQUITY
    up = symbol.upper()
    if up.endswith(("-PERP", "-SWAP")) or _DATED_FUTURES_RE.search(up) is not None:
        return MarketClass.CRYPTO_FUTURES
    if up.endswith(("-USD", "-USDT", "-USDC")):
        return MarketClass.CRYPTO_SPOT
    if any(up.endswith(q) for q in _CRYPTO_QUOTES):
        return MarketClass.CRYPTO_SPOT
    return MarketClass.EQUITY


class MarketCosts:
    """One-way execution costs for one market, in basis points."""

    __slots__ = ("fee_bps", "slippage_bps")

    def __init__(self, fee_bps: float | None, slippage_bps: float | None) -> None:
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps

    def resolved(self, flat_fee_bps: float, flat_slippage_bps: float) -> MarketCosts:
        return MarketCosts(
            fee_bps=flat_fee_bps if self.fee_bps is None else self.fee_bps,
            slippage_bps=(
                flat_slippage_bps if self.slippage_bps is None else self.slippage_bps
            ),
        )

    @property
    def round_trip_bps(self) -> float:
        fee = 0.0 if self.fee_bps is None else self.fee_bps
        slip = 0.0 if self.slippage_bps is None else self.slippage_bps
        return 2.0 * (fee + slip)

    @property
    def round_trip(self) -> float:
        return self.round_trip_bps / 10_000.0

    @property
    def breakeven_move(self) -> float:
        return self.round_trip

    def minimum_move(self, edge_mult: float = 2.0) -> float:
        return edge_mult * self.round_trip

    def sigma_gate(self, edge_mult: float = 2.0) -> float:
        return edge_mult * self.round_trip / E_ABS_MOVE

    def cost_to_stop(self, stop_pct: float) -> float:
        if stop_pct <= 0.0:
            return math.inf
        return self.round_trip_bps / (stop_pct * 100.0)


class CostModel:
    """Resolves per-symbol costs: market overrides, else the flat fallback."""

    def __init__(self, cfg: KaosCosts | None = None) -> None:
        c = cfg or KaosCosts()
        self.flat_fee_bps = c.flat_fee_bps
        self.flat_slippage_bps = c.flat_slippage_bps
        self.market: dict[MarketClass, MarketCosts] = {}
        pairs = (
            (MarketClass.EQUITY, c.equity_fee_bps, c.equity_slippage_bps),
            (MarketClass.CRYPTO_SPOT, c.crypto_spot_fee_bps, c.crypto_spot_slippage_bps),
            (MarketClass.CRYPTO_FUTURES, c.crypto_futures_fee_bps, c.crypto_futures_slippage_bps),
        )
        for cls, fee, slip in pairs:
            if fee is not None or slip is not None:
                self.market[cls] = MarketCosts(fee_bps=fee, slippage_bps=slip)

    def for_symbol(self, symbol: str, *, market_hint: str | None = None) -> MarketCosts:
        cls = classify_symbol(symbol, market_hint=market_hint)
        costs = self.market.get(cls)
        if costs is not None:
            return costs.resolved(self.flat_fee_bps, self.flat_slippage_bps)
        return MarketCosts(
            fee_bps=self.flat_fee_bps, slippage_bps=self.flat_slippage_bps
        )

    def minimum_move(self, symbol: str, edge_mult: float = 2.0, *,
                     market_hint: str | None = None) -> float:
        return self.for_symbol(symbol, market_hint=market_hint).minimum_move(edge_mult)

    def sigma_gate(self, symbol: str, edge_mult: float = 2.0, *,
                   market_hint: str | None = None) -> float:
        return self.for_symbol(symbol, market_hint=market_hint).sigma_gate(edge_mult)
