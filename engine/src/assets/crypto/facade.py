"""Crypto asset class facade.

Wraps the existing ShowMe crypto pipeline (`src/services/bot_service.py`,
`src/services/signal_service.py`, `src/consensus/`, `src/trading/`,
`src/data/`, `src/indicators/`) **without moving any files**. The legacy
modules continue to work exactly as before — this facade simply provides
a uniform ``BaseAssetClass`` interface so the new multi-asset terminal can
treat crypto as one asset class among many.
"""

from __future__ import annotations

from typing import Any

from src.core.base_asset_class import BaseAssetClass
from src.core.instrument import AssetClass, Instrument


class CryptoAssetClass(BaseAssetClass):
    """Crypto facade. Reuses legacy ShowMe services."""
    asset_class = AssetClass.CRYPTO

    def supports_instrument(self, instrument: Instrument) -> bool:
        return instrument.asset_class == AssetClass.CRYPTO

    def list_indicators(self) -> list[str]:
        # Mirrors src/services/signal_service.py registration order.
        return [
            "rsi", "macd", "bollinger", "sma_cross", "ema_cross",
            "stochastic", "adx_di", "cci", "williams_r", "roc",
            "mfi", "atr_filter", "ichimoku", "psar", "obv",
            # v2 expansion
            "supertrend", "vwap", "cvd", "heikin_ashi", "keltner",
            # futures-only
            "funding_rate", "open_interest", "liquidation_pressure",
        ]

    def list_functions(self) -> list[str]:
        # Bloomberg fonksiyonlarının kripto varyantları (her biri eklendikçe genişler)
        return [
            "DES", "GP", "GPO", "HS", "HP", "TECH",     # info & charting
            "TOP", "CN", "SOSC",                          # news/social
            "OVME", "OMON", "OSA", "HVT", "IVOL",         # derivatives (Deribit)
            "WIRP",                                       # rate expectations
            "ALRT", "GRAB",                               # alerts/screenshot
            "MOST", "WEI",                                # screen
            "PORT", "TRA", "MARS",                        # portfolio
            "EMSX", "AIM", "TCA",                         # trading
            "BQL", "DAPI",                                # api
            # legacy:
            "SCAN",                                       # auto-scanner (legacy)
        ]

    def default_data_source_chain(self, kind: str) -> list[str]:
        chains = {
            "ohlcv": ["binance", "bybit", "okx", "coingecko"],
            "quote": ["binance_ws", "binance", "bybit"],
            "orderbook": ["binance_ws", "binance"],
            "trades": ["binance_ws", "binance"],
            "news": ["benzinga", "gdelt", "rss_crypto"],
            "social": ["reddit", "stocktwits"],
            "options": ["deribit"],
            "funding_rate": ["binance"],
            "open_interest": ["binance", "bybit"],
        }
        return chains.get(kind, [])

    def list_brokers(self) -> list[str]:
        return ["binance", "bybit", "okx", "coinbase"]

    # ─── Legacy bridge ───
    def get_legacy_bot_service(self, config: dict[str, Any]) -> Any:
        """Lazy import to avoid pulling the entire bot service when an
        equity-only deployment imports the asset registry.
        """
        from src.services.bot_service import BotService
        return BotService(config)

    def get_legacy_signal_service(self, config: dict[str, Any]) -> Any:
        from src.services.signal_service import SignalService
        return SignalService(config)
