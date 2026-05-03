"""Reference / static data envelope for an instrument."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ReferenceData:
    """Static descriptive data for an instrument.

    The fields are intentionally optional — different asset classes populate
    different subsets. Free-form ``extras`` exists so adapters can attach
    asset-specific data without bloating this dataclass.
    """
    symbol: str
    name: str | None = None
    asset_class: str | None = None
    exchange: str | None = None
    currency: str | None = None
    country: str | None = None

    # Equity-specific
    sector: str | None = None
    industry: str | None = None
    gics_sub_industry: str | None = None
    market_cap: float | None = None
    shares_outstanding: float | None = None
    shares_float: float | None = None
    employees: int | None = None
    ipo_date: datetime | None = None
    ceo: str | None = None
    headquarters: str | None = None
    website: str | None = None
    description: str | None = None
    isin: str | None = None
    cusip: str | None = None
    figi: str | None = None
    cik: str | None = None  # SEC CIK

    # Bond-specific
    coupon: float | None = None
    coupon_freq: int | None = None
    maturity: datetime | None = None
    issuer: str | None = None
    rating_sp: str | None = None
    rating_moodys: str | None = None
    rating_fitch: str | None = None

    # FX-specific
    base_currency: str | None = None
    quote_currency: str | None = None

    # Commodity-specific
    contract_size: float | None = None
    contract_unit: str | None = None
    delivery_month: str | None = None

    # Derivative-specific
    underlying: str | None = None
    strike: float | None = None
    expiry: datetime | None = None
    option_type: str | None = None  # "CALL"|"PUT"

    # Macro series-specific
    units: str | None = None
    frequency: str | None = None  # "Daily","Monthly","Quarterly","Annual"
    seasonal_adjustment: str | None = None
    notes: str | None = None

    # Provenance
    source: str | None = None
    fetched_at: datetime | None = None

    extras: dict[str, Any] = field(default_factory=dict)

    def merge(self, other: "ReferenceData") -> "ReferenceData":
        """Return a new RefData where ``other`` fills any fields missing on self."""
        merged = ReferenceData(symbol=self.symbol)
        for f in self.__dataclass_fields__:
            v = getattr(self, f) or getattr(other, f)
            setattr(merged, f, v)
        # extras: union (self wins on conflict)
        merged.extras = {**other.extras, **self.extras}
        return merged
