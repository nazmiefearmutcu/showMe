"""Per-asset-class facades.

Each subpackage exposes a ``BaseAssetClass`` implementation that the rest
of the system uses as its single entry point for that asset class. Heavy
imports are lazy to keep startup cheap when only one asset class is used.
"""

from showme.engine.assets.crypto.facade import CryptoAssetClass
from showme.engine.assets.equity.facade import EquityAssetClass
from showme.engine.assets.bond.facade import BondAssetClass
from showme.engine.assets.fx.facade import FXAssetClass
from showme.engine.assets.commodity.facade import CommodityAssetClass
from showme.engine.assets.derivative.facade import DerivativeAssetClass
from showme.engine.assets.etf.facade import ETFAssetClass
from showme.engine.assets.fund.facade import FundAssetClass
from showme.engine.assets.macro.facade import MacroAssetClass

__all__ = [
    "CryptoAssetClass",
    "EquityAssetClass",
    "BondAssetClass",
    "FXAssetClass",
    "CommodityAssetClass",
    "DerivativeAssetClass",
    "ETFAssetClass",
    "FundAssetClass",
    "MacroAssetClass",
]
