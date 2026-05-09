"""Signal service - orchestrates indicator calculation across all indicators."""

from typing import Any, Optional

import pandas as pd

from showme.engine.indicators.base import BaseIndicator, IndicatorResult
from showme.engine.indicators.rsi import RSIIndicator
from showme.engine.indicators.macd import MACDIndicator
from showme.engine.indicators.bollinger import BollingerBandsIndicator
from showme.engine.indicators.sma_cross import SMACrossIndicator
from showme.engine.indicators.ema_cross import EMACrossIndicator
from showme.engine.indicators.stochastic import StochasticIndicator
from showme.engine.indicators.adx_di import ADXDIIndicator
from showme.engine.indicators.cci import CCIIndicator
from showme.engine.indicators.williams_r import WilliamsRIndicator
from showme.engine.indicators.roc import ROCIndicator
from showme.engine.indicators.mfi import MFIIndicator
from showme.engine.indicators.atr_filter import ATRFilterIndicator
from showme.engine.indicators.ichimoku import IchimokuIndicator
from showme.engine.indicators.psar import PSARIndicator
from showme.engine.indicators.obv import OBVIndicator
# v2 expansion indicators
from showme.engine.indicators.supertrend import SupertrendIndicator
from showme.engine.indicators.vwap import VWAPIndicator
from showme.engine.indicators.cvd import CVDIndicator
from showme.engine.indicators.heikin_ashi import HeikinAshiIndicator
from showme.engine.indicators.keltner import KeltnerIndicator
from showme.engine.indicators.funding_rate import FundingRateIndicator
from showme.engine.indicators.open_interest import OpenInterestIndicator
from showme.engine.utils.logger import get_logger

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
                from showme.engine.indicators.liquidation_pressure import LiquidationPressureIndicator
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
                from showme.engine.indicators.base import Signal
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
