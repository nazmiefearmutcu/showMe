"""Universal Instrument model.

A single dataclass that can represent any tradable or referenceable security
across asset classes (crypto, equity, bond, fx, commodity, derivative, etf,
fund, reit, index, macro series).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AssetClass(str, Enum):
    """Top-level asset class taxonomy."""
    CRYPTO = "CRYPTO"
    EQUITY = "EQUITY"
    BOND = "BOND"
    FX = "FX"
    COMMODITY = "COMMODITY"
    DERIVATIVE = "DERIVATIVE"  # options + futures (non-crypto)
    ETF = "ETF"
    FUND = "FUND"
    REIT = "REIT"
    INDEX = "INDEX"
    MACRO = "MACRO"  # FRED series, World Bank series — not tradable but addressable


@dataclass(frozen=True)
class Instrument:
    """A universal cross-asset instrument identifier.

    All adapters speak this language. ``symbol`` is the canonical ticker as
    used by the **primary** data source for that asset class (e.g. Binance
    "BTCUSDT", Yahoo "AAPL", FRED "DGS10"). Cross-source mapping happens
    inside ``src/reference/symbol_registry.py``.
    """
    symbol: str
    asset_class: AssetClass
    exchange: str | None = None        # "BINANCE", "NASDAQ", "FRED", "ECB", "LSE"...
    currency: str = "USD"              # ISO 4217 (USDT for stablecoin pairs)
    isin: str | None = None
    cusip: str | None = None
    figi: str | None = None            # OpenFIGI canonical id
    name: str | None = None            # human-readable, e.g. "Apple Inc."
    metadata: dict[str, Any] = field(default_factory=dict)
    # Asset-specific fields are kept loose in metadata:
    #   crypto:  {"contract_type": "PERPETUAL"|"DELIVERY", "settle_asset": "USDT"}
    #   bond:    {"coupon": 0.025, "maturity": "2034-05-15", "issuer": "US Treasury"}
    #   option:  {"underlying": "AAPL", "strike": 200, "expiry": "2026-06-19", "type": "CALL"}
    #   future:  {"underlying": "CL", "expiry": "2026-06-30"}

    def __str__(self) -> str:
        prefix = f"{self.exchange}:" if self.exchange else ""
        return f"{prefix}{self.symbol}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "asset_class": self.asset_class.value,
            "exchange": self.exchange,
            "currency": self.currency,
            "isin": self.isin,
            "cusip": self.cusip,
            "figi": self.figi,
            "name": self.name,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Instrument":
        return cls(
            symbol=data["symbol"],
            asset_class=AssetClass(data["asset_class"]),
            exchange=data.get("exchange"),
            currency=data.get("currency", "USD"),
            isin=data.get("isin"),
            cusip=data.get("cusip"),
            figi=data.get("figi"),
            name=data.get("name"),
            metadata=dict(data.get("metadata", {})),
        )

    @classmethod
    def crypto(cls, symbol: str, exchange: str = "BINANCE", **kw: Any) -> "Instrument":
        """Convenience constructor for crypto perpetual/spot."""
        return cls(symbol=symbol, asset_class=AssetClass.CRYPTO, exchange=exchange, **kw)

    @classmethod
    def equity(cls, symbol: str, exchange: str | None = None, **kw: Any) -> "Instrument":
        return cls(symbol=symbol, asset_class=AssetClass.EQUITY, exchange=exchange, **kw)

    @classmethod
    def macro_series(cls, series_id: str, exchange: str = "FRED", **kw: Any) -> "Instrument":
        return cls(symbol=series_id, asset_class=AssetClass.MACRO, exchange=exchange, **kw)
