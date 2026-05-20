"""Binance API client abstraction layer.

Provides a clean interface for market data retrieval and order execution.
Supports both spot and futures (architecture-ready), paper and live modes.
"""

import os
from typing import Any, Optional

from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

from showme.engine.utils.logger import get_logger
from showme.engine.utils.helpers import retry_with_backoff

logger = get_logger("api.binance_client")


class BinanceClient:
    """Wrapper around python-binance Client with retry and error handling."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.mode = config.get("mode", "paper")
        self.market_type = config.get("market_type", "spot")
        self._client: Optional[Client] = None
        self._initialized = False

    def initialize(self) -> None:
        """Initialize the Binance client connection."""
        if self.mode == "paper":
            api_key = os.getenv("BINANCE_API_KEY", "")
            api_secret = os.getenv("BINANCE_API_SECRET", "")
            if not api_key or not api_secret:
                logger.warning(
                    "No API keys found. Paper mode will use public endpoints for market data."
                )
                self._client = Client("", "")
            else:
                self._client = Client(api_key, api_secret)
        elif self.mode == "live":
            use_testnet = os.getenv("USE_TESTNET", "false").lower() == "true"
            if use_testnet:
                api_key = os.getenv("BINANCE_TESTNET_API_KEY", "")
                api_secret = os.getenv("BINANCE_TESTNET_API_SECRET", "")
                self._client = Client(api_key, api_secret, testnet=True)
                logger.info("Connected to Binance TESTNET")
            else:
                api_key = os.getenv("BINANCE_API_KEY", "")
                api_secret = os.getenv("BINANCE_API_SECRET", "")
                if not api_key or not api_secret:
                    raise ValueError(
                        "BINANCE_API_KEY and BINANCE_API_SECRET must be set for live mode"
                    )
                self._client = Client(api_key, api_secret)
                logger.info("Connected to Binance LIVE")

        self._initialized = True
        logger.info("BinanceClient initialized | mode=%s | market=%s", self.mode, self.market_type)

    @property
    def client(self) -> Client:
        """Get the underlying binance Client instance."""
        if not self._initialized or self._client is None:
            raise RuntimeError("BinanceClient not initialized. Call initialize() first.")
        return self._client

    def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 200,
    ) -> list[list]:
        """Fetch kline/candlestick data with retry logic.

        Uses futures endpoint when market_type is 'futures'.
        """
        def _fetch():
            if self.market_type == "futures":
                return self.client.futures_klines(
                    symbol=symbol,
                    interval=interval,
                    limit=limit,
                )
            return self.client.get_klines(
                symbol=symbol,
                interval=interval,
                limit=limit,
            )

        try:
            return retry_with_backoff(
                _fetch,
                max_retries=3,
                base_delay=2.0,
                exceptions=(BinanceAPIException, BinanceRequestException, Exception),
            )
        except Exception as e:
            logger.error("Failed to fetch klines for %s: %s", symbol, e)
            return []

    def get_ticker_price(self, symbol: str) -> Optional[float]:
        """Get the current price for a symbol."""
        try:
            if self.market_type == "futures":
                ticker = self.client.futures_symbol_ticker(symbol=symbol)
            else:
                ticker = self.client.get_symbol_ticker(symbol=symbol)
            return float(ticker["price"])
        except Exception as e:
            logger.error("Failed to get ticker price for %s: %s", symbol, e)
            return None

    def get_all_prices(self) -> dict[str, float]:
        """Bulk fetch all symbol prices in a SINGLE HTTP call.

        Replaces N×ticker_price calls when monitoring many positions.
        Returns {symbol: lastPrice} for every actively-traded pair.
        """
        try:
            if self.market_type == "futures":
                tickers = self.client.futures_ticker()  # 24h tickers, all symbols
            else:
                tickers = self.client.get_all_tickers()  # spot bulk endpoint
            result: dict[str, float] = {}
            for t in tickers or []:
                sym = t.get("symbol")
                price_str = t.get("lastPrice") or t.get("price")
                if sym and price_str:
                    try:
                        result[sym] = float(price_str)
                    except (TypeError, ValueError):
                        continue
            return result
        except Exception as e:
            logger.error("Failed to bulk-fetch prices: %s", e)
            return {}

    def get_account_balance(self, asset: str = "USDT") -> float:
        """Get account balance for a specific asset."""
        try:
            account = self.client.get_account()
            for balance in account["balances"]:
                if balance["asset"] == asset:
                    return float(balance["free"])
            return 0.0
        except Exception as e:
            logger.error("Failed to get account balance: %s", e)
            return 0.0

    def get_symbol_info(self, symbol: str) -> Optional[dict]:
        """Get exchange info for a symbol (precision, filters, etc.)."""
        try:
            if self.market_type == "futures":
                info = self.client.futures_exchange_info()
                for s in info.get("symbols", []):
                    if s["symbol"] == symbol:
                        return s
                return None
            return self.client.get_symbol_info(symbol)
        except Exception as e:
            logger.error("Failed to get symbol info for %s: %s", symbol, e)
            return None

    def place_market_buy(self, symbol: str, quantity: float) -> Optional[dict]:
        """Place a market buy order."""
        if self.mode == "paper":
            logger.warning("place_market_buy called in paper mode - should use paper engine")
            return None
        try:
            order = self.client.order_market_buy(
                symbol=symbol,
                quantity=quantity,
            )
            logger.info("MARKET BUY executed | %s | qty=%s | order_id=%s", symbol, quantity, order['orderId'])
            return order
        except BinanceAPIException as e:
            logger.error("Binance API error on market buy %s: %s", symbol, e)
            return None
        except Exception as e:
            logger.error("Unexpected error on market buy %s: %s", symbol, e)
            return None

    def place_market_sell(self, symbol: str, quantity: float) -> Optional[dict]:
        """Place a market sell order."""
        if self.mode == "paper":
            logger.warning("place_market_sell called in paper mode - should use paper engine")
            return None
        try:
            order = self.client.order_market_sell(
                symbol=symbol,
                quantity=quantity,
            )
            logger.info("MARKET SELL executed | %s | qty=%s | order_id=%s", symbol, quantity, order['orderId'])
            return order
        except BinanceAPIException as e:
            logger.error("Binance API error on market sell %s: %s", symbol, e)
            return None
        except Exception as e:
            logger.error("Unexpected error on market sell %s: %s", symbol, e)
            return None

    def place_limit_buy(self, symbol: str, quantity: float, price: float) -> Optional[dict]:
        """Place a limit buy order."""
        if self.mode == "paper":
            return None
        try:
            order = self.client.order_limit_buy(
                symbol=symbol,
                quantity=quantity,
                price=str(price),
            )
            logger.info("LIMIT BUY placed | %s | qty=%s | price=%s", symbol, quantity, price)
            return order
        except Exception as e:
            logger.error("Error placing limit buy %s: %s", symbol, e)
            return None

    def place_limit_sell(self, symbol: str, quantity: float, price: float) -> Optional[dict]:
        """Place a limit sell order."""
        if self.mode == "paper":
            return None
        try:
            order = self.client.order_limit_sell(
                symbol=symbol,
                quantity=quantity,
                price=str(price),
            )
            logger.info("LIMIT SELL placed | %s | qty=%s | price=%s", symbol, quantity, price)
            return order
        except Exception as e:
            logger.error("Error placing limit sell %s: %s", symbol, e)
            return None

    def cancel_order(self, symbol: str, order_id: int) -> Optional[dict]:
        """Cancel an open order."""
        if self.mode == "paper":
            return None
        try:
            result = self.client.cancel_order(symbol=symbol, orderId=order_id)
            logger.info("Order cancelled | %s | order_id=%s", symbol, order_id)
            return result
        except Exception as e:
            logger.error("Error cancelling order %s for %s: %s", order_id, symbol, e)
            return None

    def get_futures_symbols(self, quote_asset: str = "USDT") -> list[str]:
        """Get all actively trading futures symbols for a quote asset."""
        try:
            info = self.client.futures_exchange_info()
            symbols = []
            for s in info.get("symbols", []):
                if (
                    s.get("quoteAsset") == quote_asset
                    and s.get("status") == "TRADING"
                    and s.get("contractType") == "PERPETUAL"
                ):
                    symbols.append(s["symbol"])
            logger.info("Fetched %s futures symbols for %s", len(symbols), quote_asset)
            return sorted(symbols)
        except Exception as e:
            logger.error("Failed to fetch futures symbols: %s", e)
            return []

    def get_order_status(self, symbol: str, order_id: int) -> Optional[dict]:
        """Check the status of an order."""
        try:
            return self.client.get_order(symbol=symbol, orderId=order_id)
        except Exception as e:
            logger.error("Error getting order status %s: %s", order_id, e)
            return None

    def get_funding_rate(self, symbol: str, limit: int = 200) -> list[dict]:
        """Fetch historical funding rate (futures only).

        Returns list of dicts with keys: symbol, fundingRate (str), fundingTime (ms).
        Returns [] if not in futures mode or call fails.
        """
        if self.market_type != "futures":
            return []
        try:
            return retry_with_backoff(
                lambda: self.client.futures_funding_rate(symbol=symbol, limit=limit),
                max_retries=3,
                base_delay=2.0,
                exceptions=(BinanceAPIException, BinanceRequestException, Exception),
            ) or []
        except Exception as e:
            logger.warning("Funding rate fetch failed for %s: %s", symbol, e)
            return []

    def get_open_interest_hist(
        self, symbol: str, period: str = "1h", limit: int = 500
    ) -> list[dict]:
        """Fetch historical open interest (futures only).

        period must be one of: 5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d.
        Returns list of dicts with keys: symbol, sumOpenInterest, sumOpenInterestValue, timestamp.
        """
        if self.market_type != "futures":
            return []
        try:
            return retry_with_backoff(
                lambda: self.client.futures_open_interest_hist(
                    symbol=symbol, period=period, limit=limit
                ),
                max_retries=3,
                base_delay=2.0,
                exceptions=(BinanceAPIException, BinanceRequestException, Exception),
            ) or []
        except Exception as e:
            logger.warning("Open interest fetch failed for %s: %s", symbol, e)
            return []
