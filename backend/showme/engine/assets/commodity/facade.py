from __future__ import annotations

from showme.engine.core.base_asset_class import BaseAssetClass
from showme.engine.core.instrument import AssetClass, Instrument


class CommodityAssetClass(BaseAssetClass):
    asset_class = AssetClass.COMMODITY

    def supports_instrument(self, i: Instrument) -> bool:
        return i.asset_class == AssetClass.COMMODITY

    def list_indicators(self) -> list[str]:
        return [
            "rsi", "macd", "bollinger", "sma_cross", "ema_cross",
            "atr_filter", "ichimoku", "supertrend", "vwap",
        ]

    def list_functions(self) -> list[str]:
        return [
            "BOIL", "BGAS", "NGAS", "CPF", "GLCO", "WETR",
            "GP", "TECH", "TOP", "NI", "ECO", "ECST",
            "PORT", "TRA", "EMSX", "TSOX",
            "BQL", "DAPI", "ALRT",
        ]

    def default_data_source_chain(self, kind: str) -> list[str]:
        chains = {
            "quote": ["yfinance", "tradingeconomics"],
            "ohlcv": ["eia", "quandl", "yfinance"],
            "energy": ["eia"],
            "agri": ["usda"],
            "weather": ["openweathermap", "noaa", "open_meteo"],
        }
        return chains.get(kind, [])

    def list_brokers(self) -> list[str]:
        return ["ibkr", "saxo"]
