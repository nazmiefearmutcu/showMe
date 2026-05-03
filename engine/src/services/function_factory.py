"""FunctionFactory — wires every adapter into ``FunctionDeps``.

Single boot point: load config, instantiate adapters, hand them to a
shared ``FunctionDeps`` so every BaseFunction can resolve its data
needs without re-creating connections.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.core.base_function import FunctionDeps, FunctionRegistry
from src.core.base_data_source import DataRouter, BaseDataSource
from src.reference.symbol_registry import SymbolRegistry


class FunctionFactory:
    """Bootstrap container for all data adapters used by functions."""

    def __init__(self, config_path: str | Path = "config/data_sources.yaml") -> None:
        self.config_path = Path(config_path)
        self.config: dict[str, Any] = {}
        if self.config_path.exists():
            self.config = yaml.safe_load(self.config_path.read_text()) or {}
        self.deps = FunctionDeps()
        self._adapters: dict[str, BaseDataSource] = {}
        self._build()

    def _build(self) -> None:
        """Instantiate every adapter that imports cleanly."""
        # Equity
        from src.data_sources.equity.yfinance_adapter import YFinanceAdapter
        from src.data_sources.equity.finnhub_adapter import FinnhubAdapter
        from src.data_sources.equity.alphavantage_adapter import AlphaVantageAdapter
        from src.data_sources.equity.polygon_adapter import PolygonAdapter
        from src.data_sources.equity.eodhd_adapter import EODHDAdapter
        from src.data_sources.equity.stooq_adapter import StooqAdapter
        from src.data_sources.equity.sec_edgar_adapter import SECEdgarAdapter
        from src.data_sources.equity.sec_13f_adapter import SEC13FAdapter
        from src.data_sources.equity.seekingalpha_adapter import SeekingAlphaAdapter
        from src.data_sources.equity.finra_adapter import FINRAAdapter
        from src.data_sources.equity.sec_efts_adapter import SECFullTextSearch
        # Crypto
        from src.data_sources.crypto.coingecko_adapter import CoinGeckoAdapter
        from src.data_sources.crypto.cryptocompare_adapter import CryptoCompareAdapter
        from src.data_sources.crypto.ccxt_failover_adapter import CCXTFailoverAdapter
        # Macro
        from src.data_sources.macro.fred_adapter import FREDAdapter
        from src.data_sources.macro.worldbank_adapter import WorldBankAdapter
        from src.data_sources.macro.imf_adapter import IMFAdapter
        from src.data_sources.macro.oecd_adapter import OECDAdapter
        from src.data_sources.macro.tradingeconomics_adapter import TradingEconomicsAdapter
        from src.data_sources.macro.cme_fedwatch_adapter import CMEFedWatchAdapter
        from src.data_sources.macro.damodaran_adapter import DamodaranAdapter
        # FX
        from src.data_sources.fx.ecb_adapter import ECBAdapter
        from src.data_sources.fx.exchangerate_host_adapter import ExchangerateHostAdapter
        # Commodity
        from src.data_sources.commodity.eia_adapter import EIAAdapter
        # Bond
        from src.data_sources.bond.ustreasury_adapter import USTreasuryAdapter
        from src.data_sources.bond.treasury_auctions_adapter import TreasuryAuctionsAdapter
        # News
        from src.data_sources.news.gdelt_adapter import GDELTAdapter
        from src.data_sources.news.rss_adapter import RSSAdapter
        from src.data_sources.news.finnhub_news_adapter import FinnhubNewsAdapter
        # Alt
        from src.data_sources.alt.reddit_adapter import RedditAdapter
        from src.data_sources.alt.stocktwits_adapter import StockTwitsAdapter
        from src.data_sources.alt.openweathermap_adapter import OpenWeatherMapAdapter
        from src.data_sources.alt.sentinelhub_adapter import SentinelHubAdapter
        from src.data_sources.alt.opensky_adapter import OpenSkyAdapter
        from src.data_sources.alt.glassnode_adapter import GlassnodeAdapter
        from src.data_sources.alt.etherscan_adapter import EtherscanAdapter
        from src.data_sources.alt.mempool_adapter import MempoolAdapter
        from src.data_sources.alt.notion_adapter import NotionAdapter
        from src.data_sources.alt.granola_adapter import GranolaAdapter
        from src.data_sources.alt.polymarket_adapter import PolymarketAdapter
        # Reference
        from src.data_sources.reference.openfigi_adapter import OpenFIGIAdapter

        defaults = self.config.get("defaults", {}) or {}
        cfg_for = lambda name: {
            **defaults,
            **((self.config.get("adapters", {}) or {}).get(name, {}) or {}),
        }

        instances = {
            "yfinance":        YFinanceAdapter(cfg_for("yfinance")),
            "finnhub":         FinnhubAdapter(cfg_for("finnhub")),
            "alphavantage":    AlphaVantageAdapter(cfg_for("alphavantage")),
            "polygon":         PolygonAdapter(cfg_for("polygon")),
            "eodhd":           EODHDAdapter(cfg_for("eodhd")),
            "stooq":           StooqAdapter(cfg_for("stooq")),
            "sec_edgar":       SECEdgarAdapter(cfg_for("sec_edgar")),
            "sec_13f":         SEC13FAdapter(),
            "seekingalpha":    SeekingAlphaAdapter(),
            "finra":           FINRAAdapter(cfg_for("finra")),
            "sec_efts":        SECFullTextSearch(cfg_for("sec_efts")),
            "fred":            FREDAdapter(cfg_for("fred")),
            "worldbank":       WorldBankAdapter(cfg_for("worldbank")),
            "imf":             IMFAdapter(cfg_for("imf")),
            "oecd":            OECDAdapter(cfg_for("oecd")),
            "tradingeconomics":TradingEconomicsAdapter(cfg_for("tradingeconomics")),
            "cme_fedwatch":    CMEFedWatchAdapter(cfg_for("cme_fedwatch")),
            "damodaran":       DamodaranAdapter(cfg_for("damodaran")),
            "ecb":             ECBAdapter(cfg_for("ecb")),
            "exchangerate_host": ExchangerateHostAdapter(cfg_for("exchangerate_host")),
            "eia":             EIAAdapter(cfg_for("eia")),
            "ustreasury":      USTreasuryAdapter(cfg_for("ustreasury")),
            "treasury_auctions": TreasuryAuctionsAdapter(cfg_for("treasury_auctions")),
            "gdelt":           GDELTAdapter(cfg_for("gdelt")),
            "rss":             RSSAdapter(cfg_for("rss")),
            "finnhub_news":    FinnhubNewsAdapter(cfg_for("finnhub_news")),
            "reddit":          RedditAdapter(cfg_for("reddit")),
            "stocktwits":      StockTwitsAdapter(cfg_for("stocktwits")),
            "openweather":     OpenWeatherMapAdapter(cfg_for("openweathermap")),
            "sentinelhub":     SentinelHubAdapter(cfg_for("sentinelhub")),
            "opensky":         OpenSkyAdapter(cfg_for("opensky")),
            "glassnode":       GlassnodeAdapter(cfg_for("glassnode")),
            "etherscan":       EtherscanAdapter(cfg_for("etherscan")),
            "mempool":         MempoolAdapter(cfg_for("mempool")),
            "notion":          NotionAdapter(cfg_for("notion")),
            "granola":         GranolaAdapter(cfg_for("granola")),
            "polymarket":      PolymarketAdapter(cfg_for("polymarket")),
            "openfigi":        OpenFIGIAdapter(cfg_for("openfigi")),
            "coingecko":       CoinGeckoAdapter(cfg_for("coingecko")),
            "cryptocompare":   CryptoCompareAdapter(cfg_for("cryptocompare")),
            "ccxt_failover":   CCXTFailoverAdapter(cfg_for("ccxt_failover")),
        }
        self._adapters = instances
        # Bind to typed slots
        for name, inst in instances.items():
            setattr(self.deps, name, inst)
        self.deps.symbol_registry = SymbolRegistry(openfigi_adapter=instances["openfigi"])

    def adapter(self, name: str) -> BaseDataSource | None:
        return self._adapters.get(name)

    def all_adapters(self) -> dict[str, BaseDataSource]:
        return dict(self._adapters)

    def chain(self, asset_class: str, kind: str) -> DataRouter:
        """Return a DataRouter for a given (asset_class, kind) pair."""
        chains = (self.config.get("chains") or {}).get(asset_class, {})
        names = chains.get(kind, [])
        srcs = [self._adapters[n] for n in names if n in self._adapters]
        return DataRouter(srcs)


# ── Lazy singleton ──
_factory: FunctionFactory | None = None


def get_factory(config_path: str | Path = "config/data_sources.yaml") -> FunctionFactory:
    global _factory
    if _factory is None:
        _factory = FunctionFactory(config_path)
        _ensure_functions_registered()
    return _factory


def _ensure_functions_registered() -> None:
    """Import every functions/* module so its register() decorators run."""
    import importlib
    import pkgutil
    import src.functions as fns_pkg

    for _, modname, ispkg in pkgutil.walk_packages(fns_pkg.__path__, prefix="src.functions."):
        if not ispkg:
            try:
                importlib.import_module(modname)
            except Exception as e:
                # Don't crash boot for a single failing function — log and move on.
                import logging
                logging.getLogger("function_factory").warning(
                    "Function module %s failed to import: %s", modname, e
                )
