"""Equity asset class facade."""

from __future__ import annotations

from showme.engine.core.base_asset_class import BaseAssetClass
from showme.engine.core.instrument import AssetClass, Instrument


class EquityAssetClass(BaseAssetClass):
    asset_class = AssetClass.EQUITY

    def supports_instrument(self, i: Instrument) -> bool:
        return i.asset_class in (AssetClass.EQUITY, AssetClass.ETF, AssetClass.REIT)

    def list_indicators(self) -> list[str]:
        # Same TA library applies; pandas-ta runs on equity OHLCV too.
        return [
            "rsi", "macd", "bollinger", "sma_cross", "ema_cross",
            "stochastic", "adx_di", "cci", "williams_r", "roc",
            "mfi", "atr_filter", "ichimoku", "psar", "obv",
            "supertrend", "vwap", "heikin_ashi", "keltner",
        ]

    def list_functions(self) -> list[str]:
        return [
            "DES", "FA", "EE", "ANR", "EQS", "RV", "SPLC",
            "HDS", "DVD", "CACT", "ESG", "WACC", "BETA", "PIB",
            "GP", "GPO", "HS", "HP", "GIP", "TECH", "BI",
            "TOP", "NI", "DSRES", "READ", "BRIEF", "SOSC", "TRAN", "EVTS", "CN",
            "PORT", "PORT_WHATIF", "TRA", "MARS",
            "MOST", "WEI", "SRCH", "FSRC", "CSRC", "SECF",
            "EMSX", "AIM", "TCA",
            "BQL", "DAPI", "FLDS",
            "ALRT", "GRAB",
        ]

    def default_data_source_chain(self, kind: str) -> list[str]:
        chains = {
            "quote": ["polygon", "finnhub", "alphavantage", "yfinance"],
            "ohlcv": ["polygon", "eodhd", "alphavantage", "yfinance", "stooq"],
            "fundamentals": ["sec_edgar", "yfinance", "finnhub"],
            "estimates": ["finnhub", "yfinance"],
            "ratings": ["finnhub", "yfinance"],
            "holdings": ["sec_13f", "yfinance"],
            "dividends": ["yfinance", "eodhd"],
            "corporate_actions": ["sec_edgar", "yfinance"],
            "news": ["benzinga", "finnhub_news", "newsapi", "gdelt", "rss"],
            "social": ["stocktwits", "reddit"],
            "esg": ["yfinance", "eodhd"],
            "transcripts": ["seekingalpha", "ir"],
        }
        return chains.get(kind, [])

    def list_brokers(self) -> list[str]:
        return ["alpaca", "ibkr", "saxo"]
