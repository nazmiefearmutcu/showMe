"""Signal service - orchestrates indicator calculation across all indicators."""

from typing import Any, Optional

import pandas as pd

from src.indicators.base import BaseIndicator, IndicatorResult
from src.indicators.rsi import RSIIndicator
from src.indicators.macd import MACDIndicator
from src.indicators.bollinger import BollingerBandsIndicator
from src.indicators.sma_cross import SMACrossIndicator
from src.indicators.ema_cross import EMACrossIndicator
from src.indicators.stochastic import StochasticIndicator
from src.indicators.adx_di import ADXDIIndicator
from src.indicators.cci import CCIIndicator
from src.indicators.williams_r import WilliamsRIndicator
from src.indicators.roc import ROCIndicator
from src.indicators.mfi import MFIIndicator
from src.indicators.atr_filter import ATRFilterIndicator
from src.indicators.ichimoku import IchimokuIndicator
from src.indicators.psar import PSARIndicator
from src.indicators.obv import OBVIndicator
# v2 expansion indicators
from src.indicators.supertrend import SupertrendIndicator
from src.indicators.vwap import VWAPIndicator
from src.indicators.cvd import CVDIndicator
from src.indicators.heikin_ashi import HeikinAshiIndicator
from src.indicators.keltner import KeltnerIndicator
from src.indicators.funding_rate import FundingRateIndicator
from src.indicators.open_interest import OpenInterestIndicator
from src.utils.logger import get_logger

logger = get_logger("services.signal_service")


class SignalService:
    """Runs all indicators and collects results."""

    def __init__(
        self,
        config: dict[str, Any],
        binance_client: Optional[Any] = None,
        cache: Optional[Any] = None,
        store: Optional[Any] = None,
    ) -> None:
        self.config = config
        self.binance_client = binance_client
        self.cache = cache
        self.store = store
        self.indicators: list[BaseIndicator] = self._build_indicators()

    def _build_indicators(self) -> list[BaseIndicator]:
        """Instantiate all indicator objects.

        Futures-only indicators (Funding Rate, Open Interest) are added
        only when market_type=='futures' AND a binance client is available.
        """
        # Standard 15 indicators (config-only)
        standard = [
            RSIIndicator(self.config),
            MACDIndicator(self.config),
            BollingerBandsIndicator(self.config),
            SMACrossIndicator(self.config),
            EMACrossIndicator(self.config),
            StochasticIndicator(self.config),
            ADXDIIndicator(self.config),
            CCIIndicator(self.config),
            WilliamsRIndicator(self.config),
            ROCIndicator(self.config),
            MFIIndicator(self.config),
            ATRFilterIndicator(self.config),
            IchimokuIndicator(self.config),
            PSARIndicator(self.config),
            OBVIndicator(self.config),
        ]

        # v2 expansion (config-only)
        expansion = [
            SupertrendIndicator(self.config),
            VWAPIndicator(self.config),
            CVDIndicator(self.config),
            HeikinAshiIndicator(self.config),
            KeltnerIndicator(self.config),
        ]

        result = standard + expansion

        # Futures-only with client (cache + store passed when available)
        if (
            self.config.get("market_type") == "futures"
            and self.binance_client is not None
        ):
            result.append(FundingRateIndicator(
                self.config, self.binance_client,
                cache=self.cache, store=self.store,
            ))
            result.append(OpenInterestIndicator(
                self.config, self.binance_client,
                cache=self.cache, store=self.store,
            ))
            # Liquidation Pressure (only when cache available — relies on WS forceOrder)
            if self.cache is not None:
                from src.indicators.liquidation_pressure import LiquidationPressureIndicator
                result.append(LiquidationPressureIndicator(
                    self.config, cache=self.cache, store=self.store,
                ))

        return result

    def calculate_all(self, df: pd.DataFrame) -> list[IndicatorResult]:
        """Calculate all indicators on the given OHLCV DataFrame.

        Returns list of IndicatorResult objects. Failed indicators return NEUTRAL.
        """
        results: list[IndicatorResult] = []

        for indicator in self.indicators:
            try:
                result = indicator.calculate(df)
                results.append(result)
                logger.debug(
                    f"  {indicator.name}: {result.signal.value} (score={result.score}) - {result.reason}"
                )
            except Exception as e:
                logger.error(f"Indicator {indicator.name} failed: {e}")
                from src.indicators.base import Signal, SIGNAL_SCORES
                fallback = IndicatorResult(
                    name=indicator.name,
                    signal=Signal.NEUTRAL,
                    score=0,
                    reason=f"Calculation error: {str(e)[:100]}",
                )
                results.append(fallback)

        active = sum(1 for r in results if r.signal.value != "NEUTRAL")
        logger.info(f"Signals calculated: {len(results)} total, {active} active (non-neutral)")

        return results

    def get_indicator_names(self) -> list[str]:
        """Return list of all indicator names."""
        return [ind.name for ind in self.indicators]
