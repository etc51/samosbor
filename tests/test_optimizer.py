from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from samosbor.config import BacktestSection, ResearchSection, RiskSection, StrategySection
from samosbor.domain import Candle, Instrument, InstrumentType
from samosbor.research.optimizer import ParameterOptimizer


class OptimizerTest(unittest.TestCase):
    def test_optimizer_returns_ranked_candidates(self):
        instrument = Instrument(symbol="TEST", instrument_type=InstrumentType.STOCK, lot_size=1)
        candles = []
        ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
        price = 100.0
        for _ in range(120):
            candles.append(
                Candle(
                    timestamp=ts,
                    open=price,
                    high=price * 1.01,
                    low=price * 0.995,
                    close=price * 1.004,
                    volume=5_000_000,
                )
            )
            ts += timedelta(hours=1)
            price *= 1.003

        optimizer = ParameterOptimizer(
            base_strategy=StrategySection(min_liquidity_rub=1.0),
            risk=RiskSection(),
            backtest=BacktestSection(initial_cash=100_000, warmup_bars=30),
            research=ResearchSection(
                fast_windows=[10],
                slow_windows=[30],
                atr_stop_multipliers=[1.5],
                reward_to_risk_values=[2.0],
                trend_strength_values=[0.002],
                subset_min_size=1,
                subset_max_size=1,
                top_n=3,
                min_trades=1,
            ),
            timeframe="hour",
            slippage_bps=0,
            commission_bps=0,
        )
        payload = optimizer.run({"TEST": candles}, {"TEST": instrument})

        self.assertEqual(payload["evaluated_candidates"], 1)
        self.assertIsNotNone(payload["best_candidate"])
        self.assertEqual(len(payload["top_candidates"]), 1)
        self.assertEqual(payload["best_candidate"]["style"], "sma_breakout")
        self.assertTrue(payload["best_candidate"]["require_breakout"])
        self.assertEqual(payload["best_candidate"]["adx_min"], 20.0)

    def test_optimizer_can_evaluate_ta_style_candidates(self):
        instrument = Instrument(symbol="TEST", instrument_type=InstrumentType.STOCK, lot_size=1)
        candles = []
        ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
        price = 100.0
        for _ in range(140):
            candles.append(
                Candle(
                    timestamp=ts,
                    open=price,
                    high=price * 1.012,
                    low=price * 0.994,
                    close=price * 1.006,
                    volume=5_000_000,
                )
            )
            ts += timedelta(hours=1)
            price *= 1.004

        optimizer = ParameterOptimizer(
            base_strategy=StrategySection(min_liquidity_rub=1.0),
            risk=RiskSection(),
            backtest=BacktestSection(initial_cash=100_000, warmup_bars=30),
            research=ResearchSection(
                strategy_styles=["ema_adx_macd"],
                fast_windows=[10],
                slow_windows=[30],
                require_breakout_values=[False],
                atr_stop_multipliers=[1.5],
                reward_to_risk_values=[2.0],
                trend_strength_values=[0.002],
                adx_min_values=[15.0],
                subset_min_size=1,
                subset_max_size=1,
                top_n=3,
                min_trades=1,
            ),
            timeframe="hour",
            slippage_bps=0,
            commission_bps=0,
        )

        payload = optimizer.run({"TEST": candles}, {"TEST": instrument})

        self.assertEqual(payload["evaluated_candidates"], 1)
        self.assertIsNotNone(payload["best_candidate"])
        self.assertEqual(payload["best_candidate"]["style"], "ema_adx_macd")
        self.assertFalse(payload["best_candidate"]["require_breakout"])
        self.assertEqual(payload["best_candidate"]["adx_min"], 15.0)

    def test_optimizer_can_evaluate_mean_reversion_style_candidates(self):
        instrument = Instrument(symbol="TEST", instrument_type=InstrumentType.STOCK, lot_size=1)
        candles = []
        ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
        price = 100.0
        for index in range(180):
            close = price + (0.35 if index % 2 == 0 else -0.45)
            if index in {59, 89, 119, 149, 179}:
                close -= 4.0
            candles.append(
                Candle(
                    timestamp=ts,
                    open=price,
                    high=max(price, close) + 0.9,
                    low=min(price, close) - 0.9,
                    close=close,
                    volume=5_000_000,
                )
            )
            ts += timedelta(hours=1)
            price = close

        optimizer = ParameterOptimizer(
            base_strategy=StrategySection(min_liquidity_rub=1.0),
            risk=RiskSection(),
            backtest=BacktestSection(initial_cash=100_000, warmup_bars=30),
            research=ResearchSection(
                strategy_styles=["rsi_mean_reversion"],
                fast_windows=[10],
                slow_windows=[30],
                atr_stop_multipliers=[1.5],
                reward_to_risk_values=[2.0],
                trend_strength_values=[0.002],
                rsi_long_max_values=[65.0],
                rsi_short_min_values=[35.0],
                subset_min_size=1,
                subset_max_size=1,
                top_n=3,
                min_trades=1,
            ),
            timeframe="hour",
            slippage_bps=0,
            commission_bps=0,
        )

        payload = optimizer.run({"TEST": candles}, {"TEST": instrument})

        self.assertEqual(payload["evaluated_candidates"], 1)
        self.assertIsNotNone(payload["best_candidate"])
        self.assertEqual(payload["best_candidate"]["style"], "rsi_mean_reversion")
        self.assertEqual(payload["best_candidate"]["rsi_long_max"], 65.0)
        self.assertEqual(payload["best_candidate"]["rsi_short_min"], 35.0)

    def test_optimizer_can_evaluate_donchian_ta_style_candidates(self):
        instrument = Instrument(symbol="TEST", instrument_type=InstrumentType.STOCK, lot_size=1)
        candles = []
        ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
        price = 100.0
        for _ in range(160):
            candles.append(
                Candle(
                    timestamp=ts,
                    open=price,
                    high=price * 1.015,
                    low=price * 0.993,
                    close=price * 1.007,
                    volume=5_000_000,
                )
            )
            ts += timedelta(hours=1)
            price *= 1.004

        optimizer = ParameterOptimizer(
            base_strategy=StrategySection(min_liquidity_rub=1.0),
            risk=RiskSection(),
            backtest=BacktestSection(initial_cash=100_000, warmup_bars=30),
            research=ResearchSection(
                strategy_styles=["ema_adx_donchian"],
                fast_windows=[10],
                slow_windows=[30],
                atr_stop_multipliers=[1.5],
                reward_to_risk_values=[2.0],
                trend_strength_values=[0.002],
                adx_min_values=[15.0],
                subset_min_size=1,
                subset_max_size=1,
                top_n=3,
                min_trades=1,
            ),
            timeframe="hour",
            slippage_bps=0,
            commission_bps=0,
        )

        payload = optimizer.run({"TEST": candles}, {"TEST": instrument})

        self.assertEqual(payload["evaluated_candidates"], 1)
        self.assertIsNotNone(payload["best_candidate"])
        self.assertEqual(payload["best_candidate"]["style"], "ema_adx_donchian")
        self.assertEqual(payload["best_candidate"]["adx_min"], 15.0)


if __name__ == "__main__":
    unittest.main()
