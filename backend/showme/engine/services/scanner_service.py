"""Scanner service - scans Binance futures for high-confidence trading opportunities."""

import time
import threading
from pathlib import Path
from typing import Any, Optional

from showme.engine.api.binance_client import BinanceClient
from showme.engine.data.market_data import MarketDataProvider
from showme.engine.services.signal_service import SignalService
from showme.engine.consensus.engine import ConsensusEngine
from showme.engine.utils.logger import get_logger

logger = get_logger("services.scanner")

# Stablecoins and low-quality pairs to skip
SKIP_SYMBOLS = {
    "USDCUSDT", "BUSDUSDT", "TUSDUSDT", "DAIUSDT", "FDUSDUSDT",
    "EURUSDT", "GBPUSDT",
}

# No limit — scan all available futures symbols


class ScannerService:
    """Scans multiple coins and ranks them by confidence."""

    def __init__(self, config: dict[str, Any], symbol_file: Path | None = None,
                 timeframe: str | None = None,
                 shared_client: BinanceClient | None = None,
                 shared_symbols: list[str] | None = None) -> None:
        self.config = config
        # Reuse shared client to avoid rate limits on multi-TF scans
        if shared_client:
            self.client = shared_client
        else:
            self.client = BinanceClient(config)
            self.client.initialize()
        # Allow timeframe override (for multi-TF scanning)
        if timeframe:
            cfg = dict(config)
            cfg["timeframe"] = timeframe
        else:
            cfg = config
        self.market_data = MarketDataProvider(self.client, cfg)
        self.signal_service = SignalService(config, binance_client=self.client)
        self.consensus_engine = ConsensusEngine(config)
        self.symbol_file = symbol_file
        self.timeframe = cfg.get("timeframe", "1h")
        self._shared_symbols = shared_symbols
        self._request_delay = 0.1  # default; increased for multi-TF mode

        # Scan state
        self._scanning = False
        self._scan_results: list[dict] = []
        self._scan_progress: dict = {
            "current": 0, "total": 0, "symbol": "",
            "status": "idle", "hot_count": 0,
        }
        self._lock = threading.Lock()

    @property
    def is_scanning(self) -> bool:
        return self._scanning

    @property
    def progress(self) -> dict:
        with self._lock:
            return dict(self._scan_progress)

    @property
    def results(self) -> list[dict]:
        with self._lock:
            return list(self._scan_results)

    def _get_top_symbols_by_volume(self) -> list[str]:
        """Get futures symbols sorted by 24h volume (descending)."""
        try:
            tickers = self.client.client.futures_ticker()
            usdt_tickers = [
                t for t in tickers
                if t["symbol"].endswith("USDT")
                and t["symbol"] not in SKIP_SYMBOLS
            ]
            usdt_tickers.sort(key=lambda t: float(t.get("quoteVolume", 0)), reverse=True)
            symbols = [t["symbol"] for t in usdt_tickers]
            logger.info("Top %s futures symbols by volume selected for scan", len(symbols))
            return symbols
        except Exception as e:
            logger.error("Failed to get tickers, falling back to symbol list: %s", e)
            symbols = self.client.get_futures_symbols()
            return [s for s in symbols if s not in SKIP_SYMBOLS]

    def set_active_symbol(self, symbol: str) -> bool:
        """Write symbol to active_symbol.txt so the bot switches to it."""
        if self.symbol_file is None:
            return False
        try:
            self.symbol_file.parent.mkdir(parents=True, exist_ok=True)
            self.symbol_file.write_text(f"{symbol}\n")
            logger.info("Active symbol set to %s", symbol)
            return True
        except Exception as e:
            logger.error("Failed to set active symbol: %s", e)
            return False

    def scan(self, min_confidence: int = 55) -> list[dict]:
        """Scan all top symbols and return those with confidence >= threshold.

        Per PERF-10 P1: per-symbol fetch + indicator calc is parallelised via
        ``ThreadPoolExecutor`` (numpy + httpx release the GIL during the
        IO-heavy parts) instead of a serial loop with ``time.sleep``. The
        previous wall-clock floor of ``len(symbols) * request_delay`` is
        gone; effective concurrency is capped by ``max_workers``.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        try:
            symbols = self._shared_symbols if self._shared_symbols else self._get_top_symbols_by_volume()

            if not symbols:
                logger.warning("No futures symbols found")
                return []

            with self._lock:
                self._scanning = True
                self._scan_results = []
                self._scan_progress = {
                    "current": 0,
                    "total": len(symbols),
                    "symbol": "",
                    "status": "scanning",
                    "hot_count": 0,
                }

            logger.info("Scanning %s futures symbols (min confidence: %s%%)", len(symbols), min_confidence)

            hot_count = 0
            # Cap concurrency so we don't blow Binance rate limits or the
            # process FD budget. 8 is the same value the legacy
            # scanner.py:376 path uses for `Semaphore(8)`.
            max_workers = max(2, min(8, len(symbols)))
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {pool.submit(self._analyze_symbol, sym): sym for sym in symbols}
                completed = 0
                for fut in as_completed(futures):
                    if not self._scanning:
                        logger.info("Scan cancelled")
                        for pending in futures:
                            pending.cancel()
                        break
                    sym = futures[fut]
                    completed += 1
                    with self._lock:
                        self._scan_progress["current"] = completed
                        self._scan_progress["symbol"] = sym
                    try:
                        result = fut.result()
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("scan failed for %s: %s", sym, exc)
                        continue
                    if result is None:
                        continue
                    with self._lock:
                        self._scan_results.append(result)
                        if result["confidence"] >= min_confidence and result["signal"] != "NEUTRAL":
                            hot_count += 1
                            self._scan_progress["hot_count"] = hot_count

            # Sort results by confidence descending
            from operator import itemgetter
            with self._lock:
                self._scan_results.sort(key=itemgetter("confidence"), reverse=True)
                self._scanning = False
                self._scan_progress["status"] = "complete"
                self._scan_progress["hot_count"] = hot_count

            logger.info("Scan complete. %s coins above %s%% confidence out of %s analyzed.", hot_count, min_confidence, len(self._scan_results))
            return [r for r in self._scan_results if r["confidence"] >= min_confidence and r["signal"] != "NEUTRAL"]

        except Exception as e:
            logger.error("Scan crashed: %s", e, exc_info=True)
            with self._lock:
                self._scanning = False
                self._scan_progress["status"] = "error"
            return []

    def scan_async(self, min_confidence: int = 55) -> bool:
        """Start scanning in a background thread."""
        if self._scanning:
            return False
        thread = threading.Thread(target=self.scan, args=(min_confidence,), daemon=True)
        thread.start()
        return True

    def stop(self) -> None:
        """Stop an ongoing scan."""
        self._scanning = False

    def force_reset(self) -> None:
        """Force reset scanning state (recover from stuck state)."""
        with self._lock:
            self._scanning = False
            self._scan_progress["status"] = "idle"

    def _analyze_symbol(self, symbol: str) -> Optional[dict]:
        """Analyze a single symbol and return its consensus data."""
        try:
            df = self.market_data.get_ohlcv(symbol)
            if df is None or df.empty:
                return None

            current_price = float(df["close"].iloc[-1])
            indicator_results = self.signal_service.calculate_all(df)
            consensus = self.consensus_engine.evaluate(indicator_results)

            return {
                "symbol": symbol,
                "price": current_price,
                "signal": consensus.get("final_signal", "NEUTRAL"),
                "confidence": consensus.get("confidence", 0),
                "risk_level": consensus.get("risk_level", "HIGH"),
                "weighted_score": round(consensus.get("weighted_score", 0), 3),
                "should_trade": consensus.get("should_trade", False),
            }
        except Exception as e:
            logger.warning("Failed to analyze %s: %s", symbol, e)
            return None
