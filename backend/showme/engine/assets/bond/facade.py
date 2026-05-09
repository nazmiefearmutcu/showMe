from __future__ import annotations

from showme.engine.core.base_asset_class import BaseAssetClass
from showme.engine.core.instrument import AssetClass, Instrument


class BondAssetClass(BaseAssetClass):
    asset_class = AssetClass.BOND

    def supports_instrument(self, i: Instrument) -> bool:
        return i.asset_class == AssetClass.BOND

    def list_indicators(self) -> list[str]:
        return ["yield_spread", "duration", "convexity", "z_spread"]

    def list_functions(self) -> list[str]:
        return [
            "YAS", "CRPR", "CRVF", "DDIS", "DEBT", "WB", "SRSK", "ALLQ", "GC3D",
            "GP", "TECH", "TOP", "NI", "ECO", "ECST",
            "PORT", "TRA", "MARS",
            "EMSX", "AIM", "TSOX",
            "BQL", "DAPI",
            "ALRT",
        ]

    def default_data_source_chain(self, kind: str) -> list[str]:
        chains = {
            "yield_curve": ["fred", "ustreasury", "ecb", "worldbank"],
            "yield": ["fred", "tradingeconomics", "worldbank"],
            "credit": ["sec_edgar"],  # 10-K extracted
            "trace": ["finra"],
            "cds": ["markit_proxy"],  # ücretsiz approx.
        }
        return chains.get(kind, [])

    def list_brokers(self) -> list[str]:
        return ["ibkr", "saxo"]
