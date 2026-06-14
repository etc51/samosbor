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


if __name__ == "__main__":
    unittest.main()
