from __future__ import annotations

from showme.engine.core.base_asset_class import BaseAssetClass
from showme.engine.core.instrument import AssetClass, Instrument


class ETFAssetClass(BaseAssetClass):
    asset_class = AssetClass.ETF

    def supports_instrument(self, i: Instrument) -> bool:
        return i.asset_class == AssetClass.ETF

    def list_indicators(self) -> list[str]:
        return ["rsi", "macd", "bollinger", "sma_cross", "ema_cross"]

    def list_functions(self) -> list[str]:
        return [
            "DES", "FA", "HDS", "DVD", "ESG",
            "GP", "TECH", "TOP", "NI",
            "PORT", "TRA",
            "EMSX", "AIM",
            "ALRT", "BQL",
        ]

    def default_data_source_chain(self, kind: str) -> list[str]:
        # ETF mostly behaves like equity for data purposes.
        from showme.engine.assets.equity.facade import EquityAssetClass
        return EquityAssetClass({}).default_data_source_chain(kind)

    def list_brokers(self) -> list[str]:
        return ["alpaca", "ibkr"]
