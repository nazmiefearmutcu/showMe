from __future__ import annotations

from src.core.base_asset_class import BaseAssetClass
from src.core.instrument import AssetClass, Instrument


class FXAssetClass(BaseAssetClass):
    asset_class = AssetClass.FX

    def supports_instrument(self, i: Instrument) -> bool:
        return i.asset_class == AssetClass.FX

    def list_indicators(self) -> list[str]:
        return [
            "rsi", "macd", "bollinger", "sma_cross", "ema_cross",
            "atr_filter", "ichimoku", "psar",
        ]

    def list_functions(self) -> list[str]:
        return [
            "FXFC", "FXIP", "WCRS", "FRD", "OVDV",
            "GP", "TECH",
            "TOP", "NI", "ECO", "ECST", "WIRP", "BTMM",
            "PORT", "TRA",
            "FXGO", "EMSX",
            "BQL", "DAPI", "ALRT",
        ]

    def default_data_source_chain(self, kind: str) -> list[str]:
        chains = {
            "quote": ["oanda", "ecb", "exchangerate_host", "twelvedata"],
            "ohlcv": ["ecb", "yfinance", "oanda"],
            "forward": ["ecb", "oanda"],
            "options": ["deribit", "saxo"],
        }
        return chains.get(kind, [])

    def list_brokers(self) -> list[str]:
        return ["oanda", "ibkr", "saxo"]
