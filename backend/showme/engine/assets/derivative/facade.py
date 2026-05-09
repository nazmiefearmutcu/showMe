from __future__ import annotations

from showme.engine.core.base_asset_class import BaseAssetClass
from showme.engine.core.instrument import AssetClass, Instrument


class DerivativeAssetClass(BaseAssetClass):
    asset_class = AssetClass.DERIVATIVE

    def supports_instrument(self, i: Instrument) -> bool:
        return i.asset_class == AssetClass.DERIVATIVE

    def list_indicators(self) -> list[str]:
        return ["iv_rank", "iv_percentile", "vol_skew", "term_structure"]

    def list_functions(self) -> list[str]:
        return [
            "OVME", "OMON", "OSA", "HVT", "IVOL",
            "GP", "TECH",
            "EMSX", "BBGT", "ALRT",
        ]

    def default_data_source_chain(self, kind: str) -> list[str]:
        chains = {
            "options_chain": ["yfinance", "polygon", "deribit"],
            "futures_chain": ["yfinance", "cme"],
        }
        return chains.get(kind, [])

    def list_brokers(self) -> list[str]:
        return ["ibkr", "saxo", "deribit"]
