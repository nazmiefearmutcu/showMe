from __future__ import annotations

from src.core.base_asset_class import BaseAssetClass
from src.core.instrument import AssetClass, Instrument


class FundAssetClass(BaseAssetClass):
    asset_class = AssetClass.FUND

    def supports_instrument(self, i: Instrument) -> bool:
        return i.asset_class == AssetClass.FUND

    def list_indicators(self) -> list[str]:
        return []  # NAV-based; technical indicators rarely meaningful

    def list_functions(self) -> list[str]:
        return ["DES", "HDS", "DVD", "FA", "PORT", "TRA", "BQL"]

    def default_data_source_chain(self, kind: str) -> list[str]:
        chains = {
            "nav": ["yfinance", "morningstar"],
            "holdings": ["sec_edgar", "issuer"],
        }
        return chains.get(kind, [])

    def list_brokers(self) -> list[str]:
        return ["ibkr"]
