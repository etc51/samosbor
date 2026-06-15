from __future__ import annotations

import math
import warnings
from datetime import datetime
from zoneinfo import ZoneInfo

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
        self.style = config.style.strip().lower()
        self._prepared_ta: dict[str, dict[str, object]] = {}
        if self.style not in {"sma_breakout", "ema_adx_macd"}:
            raise ValueError(f"Unsupported strategy style: {config.style}")
        self.schedule_timezone = ZoneInfo(config.schedule_timezone)

    def prepare_history(self, instrument: Instrument, candles: list[Candle]) -> None:
        if self.style != "ema_adx_macd" or not candles:
            return
        features = self._compute_ta_feature_series(candles)
        timestamps = [candle.timestamp for candle in candles]
        self._prepared_ta[instrument.instrument_id] = {
            "timestamps": timestamps,
            "features": features,
        }

    def allows_entry_at(self, timestamp: datetime) -> bool:
        localized = timestamp.astimezone(self.schedule_timezone)
        if self.config.allowed_entry_weekdays and localized.weekday() not in self.config.allowed_entry_weekdays:
            return False
        if self.config.allowed_entry_hours and localized.hour not in self.config.allowed_entry_hours:
            return False
        return True

    def _required_bars(self) -> int:
        required = max(
            self.config.slow_window,
            self.config.atr_window + 1,
            self.config.volume_window,
            self.config.breakout_window + 1,
        )
        if self.style == "ema_adx_macd":
            ta_bars = max(
                self.config.adx_window * 3,
                self.config.rsi_window + 2,
                self.config.macd_slow + self.config.macd_signal + 5,
            )
            required = max(required, ta_bars)
        return required

    def generate_signal(
        self,
        instrument: Instrument,
        candles: list[Candle],
    ) -> Signal | None:
        required = self._required_bars()
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
        breakout_long = last.close >= breakout_high if self.config.require_breakout else True
        breakout_short = last.close <= breakout_low if self.config.require_breakout else True

        if self.style == "ema_adx_macd":
            ta_features = self._resolved_ta_features(instrument, candles)
            if ta_features is None:
                return None
            fast = ta_features["ema_fast"]
            slow = ta_features["ema_slow"]
            trend_strength = abs(fast - slow) / abs(slow) if slow else 0.0
            if trend_strength < self.config.min_trend_strength:
                return None
            if (
                fast > slow
                and ta_features["adx"] >= self.config.adx_min
                and ta_features["macd_hist"] > 0
                and self.config.rsi_long_min <= ta_features["rsi"] <= self.config.rsi_long_max
                and last.close >= fast
                and breakout_long
            ):
                return self._build_signal(
                    instrument=instrument,
                    direction=SignalDirection.LONG,
                    last=last,
                    atr_value=atr_value,
                    context_score=context_score,
                    trend_strength=trend_strength,
                    turnover=turnover,
                    volatility=volatility,
                    extra_reason=(
                        f"ema-up ema_fast={fast:.2f} ema_slow={slow:.2f} "
                        f"adx={ta_features['adx']:.2f} rsi={ta_features['rsi']:.2f} "
                        f"macd_hist={ta_features['macd_hist']:.4f}"
                    ),
                )
            if (
                self.config.allow_shorts
                and fast < slow
                and ta_features["adx"] >= self.config.adx_min
                and ta_features["macd_hist"] < 0
                and self.config.rsi_short_min <= ta_features["rsi"] <= self.config.rsi_short_max
                and last.close <= fast
                and breakout_short
            ):
                return self._build_signal(
                    instrument=instrument,
                    direction=SignalDirection.SHORT,
                    last=last,
                    atr_value=atr_value,
                    context_score=context_score,
                    trend_strength=trend_strength,
                    turnover=turnover,
                    volatility=volatility,
                    extra_reason=(
                        f"ema-down ema_fast={fast:.2f} ema_slow={slow:.2f} "
                        f"adx={ta_features['adx']:.2f} rsi={ta_features['rsi']:.2f} "
                        f"macd_hist={ta_features['macd_hist']:.4f}"
                    ),
                )
            return None

        if fast > slow and breakout_long:
            return self._build_signal(
                instrument=instrument,
                direction=SignalDirection.LONG,
                last=last,
                atr_value=atr_value,
                context_score=context_score,
                trend_strength=trend_strength,
                turnover=turnover,
                volatility=volatility,
                extra_reason=(
                    f"trend-up fast={fast:.2f} slow={slow:.2f} "
                    f"atr={atr_value:.2f} vol={volatility or 0.0:.3f}"
                ),
            )

        if self.config.allow_shorts and fast < slow and breakout_short:
            return self._build_signal(
                instrument=instrument,
                direction=SignalDirection.SHORT,
                last=last,
                atr_value=atr_value,
                context_score=context_score,
                trend_strength=trend_strength,
                turnover=turnover,
                volatility=volatility,
                extra_reason=(
                    f"trend-down fast={fast:.2f} slow={slow:.2f} "
                    f"atr={atr_value:.2f} vol={volatility or 0.0:.3f}"
                ),
            )

        return None

    def _build_signal(
        self,
        *,
        instrument: Instrument,
        direction: SignalDirection,
        last: Candle,
        atr_value: float,
        context_score: float,
        trend_strength: float,
        turnover: float,
        volatility: float | None,
        extra_reason: str,
    ) -> Signal:
        stop_distance = atr_value * self.config.atr_stop_multiple
        if direction == SignalDirection.LONG:
            stop_distance = atr_value * self.config.atr_stop_multiple
            confidence = min(1.0, trend_strength * 80 + max(context_score, 0.0))
            if confidence < self.config.min_signal_strength:
                return None
            reason = extra_reason
            return Signal(
                instrument=instrument,
                direction=direction,
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
        confidence = min(1.0, trend_strength * 80 + max(-context_score, 0.0))
        if confidence < self.config.min_signal_strength:
            return None
        return Signal(
            instrument=instrument,
            direction=direction,
            strength=confidence,
            entry_price=last.close,
            stop_price=last.close + stop_distance,
            take_profit=last.close - stop_distance * self.config.reward_to_risk,
            reason=extra_reason,
            context_score=context_score,
            metadata={
                "trend_strength": trend_strength,
                "turnover": turnover,
                "volatility": volatility,
            },
        )

    def _resolved_ta_features(
        self,
        instrument: Instrument,
        candles: list[Candle],
    ) -> dict[str, float] | None:
        prepared = self._prepared_ta.get(instrument.instrument_id)
        if prepared is not None and candles:
            timestamps = prepared["timestamps"]
            features = prepared["features"]
            index = len(candles) - 1
            if index < len(timestamps) and timestamps[index] == candles[-1].timestamp:
                return features[index]
        return self._ta_features(candles)

    def _ta_dependencies(self):
        try:
            import pandas as pd
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=".*mode.copy_on_write.*",
                )
                import pandas_ta as ta
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "TA indicator mode requires pandas and pandas-ta to be installed."
            ) from exc
        return pd, ta

    def _ta_features(self, candles: list[Candle]) -> dict[str, float] | None:
        window = max(self._required_bars() + 5, 250)
        subset = candles[-window:]
        features = self._compute_ta_feature_series(subset)
        if not features:
            return None
        return features[-1]

    def _compute_ta_feature_series(self, candles: list[Candle]) -> list[dict[str, float] | None]:
        pd, ta = self._ta_dependencies()
        frame = pd.DataFrame(
            {
                "open": [candle.open for candle in candles],
                "high": [candle.high for candle in candles],
                "low": [candle.low for candle in candles],
                "close": [candle.close for candle in candles],
                "volume": [candle.volume for candle in candles],
            }
        )
        ema_fast = ta.ema(frame["close"], length=self.config.fast_window)
        ema_slow = ta.ema(frame["close"], length=self.config.slow_window)
        rsi = ta.rsi(frame["close"], length=self.config.rsi_window)
        macd = ta.macd(
            frame["close"],
            fast=self.config.macd_fast,
            slow=self.config.macd_slow,
            signal=self.config.macd_signal,
        )
        adx = ta.adx(
            frame["high"],
            frame["low"],
            frame["close"],
            length=self.config.adx_window,
        )
        if macd is None or adx is None:
            return [None for _ in candles]

        series: list[dict[str, float] | None] = []
        for index in range(len(candles)):
            values = {
                "ema_fast": float(ema_fast.iloc[index]) if ema_fast is not None else math.nan,
                "ema_slow": float(ema_slow.iloc[index]) if ema_slow is not None else math.nan,
                "rsi": float(rsi.iloc[index]) if rsi is not None else math.nan,
                "macd": float(macd.iloc[index, 0]),
                "macd_hist": float(macd.iloc[index, 1]),
                "macd_signal": float(macd.iloc[index, 2]),
                "adx": float(adx.iloc[index, 0]),
                "dmp": float(adx.iloc[index, 1]),
                "dmn": float(adx.iloc[index, 2]),
            }
            if any(math.isnan(value) for value in values.values()):
                series.append(None)
                continue
            series.append(values)
        return series
