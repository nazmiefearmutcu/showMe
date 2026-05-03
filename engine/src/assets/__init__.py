"""Per-asset-class facades.

Each subpackage exposes a ``BaseAssetClass`` implementation that the rest
of the system uses as its single entry point for that asset class. Heavy
imports are lazy to keep startup cheap when only one asset class is used.
"""

from src.assets.crypto.facade import CryptoAssetClass
from src.assets.equity.facade import EquityAssetClass
from src.assets.bond.facade import BondAssetClass
from src.assets.fx.facade import FXAssetClass
from src.assets.commodity.facade import CommodityAssetClass
from src.assets.derivative.facade import DerivativeAssetClass
from src.assets.etf.facade import ETFAssetClass
from src.assets.fund.facade import FundAssetClass
from src.assets.macro.facade import MacroAssetClass

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
