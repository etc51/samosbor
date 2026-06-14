from __future__ import annotations

from ..analysis.context import ExternalContextProvider, NeutralContextProvider
from ..analysis.indicators import annualized_volatility, atr, average_turnover, rolling_high, rolling_low, sma
from ..config import StrategySection
from ..domain import Candle, Instrument, Signal, SignalDirection


def bars_per_year_for_timeframe(timeframe: str) -> int:
    mapping = {
        "day": 252,
        "hour": 2016,
        "30min": 4032,
        "15min": 8064,
        "10min": 12096,
        "5min": 24192,
        "1min": 120960,
    }
    return mapping.get(timeframe.lower(), 252)


class TrendFollowingStrategy:
    def __init__(
        self,
        config: StrategySection,
        *,
        timeframe: str,
        context_provider: ExternalContextProvider | None = None,
    ):
        self.config = config
        self.timeframe = timeframe
        self.context_provider = context_provider or NeutralContextProvider()

    def generate_signal(
        self,
        instrument: Instrument,
        candles: list[Candle],
    ) -> Signal | None:
        required = max(
            self.config.slow_window,
            self.config.atr_window + 1,
            self.config.volume_window,
            self.config.breakout_window + 1,
        )
        if len(candles) < required:
            return None

        closes = [candle.close for candle in candles]
        fast = sma(closes, self.config.fast_window)
        slow = sma(closes, self.config.slow_window)
        atr_value = atr(candles, self.config.atr_window)
        turnover = average_turnover(candles, self.config.volume_window)
        breakout_high = rolling_high(candles[:-1], self.config.breakout_window)
        breakout_low = rolling_low(candles[:-1], self.config.breakout_window)
        volatility = annualized_volatility(
            candles,
            self.config.atr_window,
            bars_per_year_for_timeframe(self.timeframe),
        )

        if (
            fast is None
            or slow is None
            or atr_value is None
            or turnover is None
            or breakout_high is None
            or breakout_low is None
            or slow <= 0
            or atr_value <= 0
        ):
            return None

        if turnover < self.config.min_liquidity_rub:
            return None

        last = candles[-1]
        trend_strength = abs(fast - slow) / slow
        if trend_strength < self.config.min_trend_strength:
            return None

        context_score = self.context_provider.score(instrument, candles)
        breakout_long = last.close >= breakout_high
        breakout_short = last.close <= breakout_low

        if fast > slow and breakout_long:
            stop_distance = atr_value * self.config.atr_stop_multiple
            confidence = min(1.0, trend_strength * 80 + max(context_score, 0.0))
            reason = (
                f"trend-up fast={fast:.2f} slow={slow:.2f} "
                f"atr={atr_value:.2f} vol={volatility or 0.0:.3f}"
            )
            return Signal(
                instrument=instrument,
                direction=SignalDirection.LONG,
                strength=confidence,
                entry_price=last.close,
                stop_price=last.close - stop_distance,
                take_profit=last.close + stop_distance * self.config.reward_to_risk,
                reason=reason,
                context_score=context_score,
                metadata={
                    "trend_strength": trend_strength,
                    "turnover": turnover,
                    "volatility": volatility,
                },
            )

        if self.config.allow_shorts and fast < slow and breakout_short:
            stop_distance = atr_value * self.config.atr_stop_multiple
            confidence = min(1.0, trend_strength * 80 + max(-context_score, 0.0))
            reason = (
                f"trend-down fast={fast:.2f} slow={slow:.2f} "
                f"atr={atr_value:.2f} vol={volatility or 0.0:.3f}"
            )
            return Signal(
                instrument=instrument,
                direction=SignalDirection.SHORT,
                strength=confidence,
                entry_price=last.close,
                stop_price=last.close + stop_distance,
                take_profit=last.close - stop_distance * self.config.reward_to_risk,
                reason=reason,
                context_score=context_score,
                metadata={
                    "trend_strength": trend_strength,
                    "turnover": turnover,
                    "volatility": volatility,
                },
            )

        return None
