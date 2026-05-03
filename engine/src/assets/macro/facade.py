from __future__ import annotations

from src.core.base_asset_class import BaseAssetClass
from src.core.instrument import AssetClass, Instrument


class MacroAssetClass(BaseAssetClass):
    """Macro 'asset class' = economic series (FRED, World Bank, OECD).

    These are not tradable but addressable as instruments so the same
    function/router/registry framework can serve them.
    """
    asset_class = AssetClass.MACRO

    def supports_instrument(self, i: Instrument) -> bool:
        return i.asset_class == AssetClass.MACRO

    def list_indicators(self) -> list[str]:
        return ["yoy", "qoq", "z_score", "trend", "anomaly"]

    def list_functions(self) -> list[str]:
        return [
            "ECO", "ECST", "ECFC", "BTMM", "WIRP", "GMM", "COUN",
            "GP", "TOP", "NI",
            "BQL", "DAPI", "ALRT",
        ]

    def default_data_source_chain(self, kind: str) -> list[str]:
        chains = {
            "series": ["fred", "worldbank", "imf", "oecd", "tradingeconomics"],
            "calendar": ["tradingeconomics", "finnhub", "nasdaq_econ"],
            "forecast": ["oecd", "imf", "tradingeconomics"],
        }
        return chains.get(kind, [])

    def list_brokers(self) -> list[str]:
        return []
