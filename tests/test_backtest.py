from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from samosbor.backtest.engine import BacktestEngine
from samosbor.config import BacktestSection, RiskSection, StrategySection
from samosbor.domain import Candle, Instrument, InstrumentType
from samosbor.risk.manager import RiskManager
from samosbor.strategy.trend_following import TrendFollowingStrategy


class BacktestSmokeTest(unittest.TestCase):
    def test_backtest_generates_trades_and_equity_curve(self):
        instrument = Instrument(symbol="SBER", instrument_type=InstrumentType.STOCK, lot_size=10)
        candles = []
        ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
        price = 100.0
        for _ in range(120):
            candles.append(
                Candle(
                    timestamp=ts,
                    open=price,
                    high=price * 1.015,
                    low=price * 0.995,
                    close=price * 1.01,
                    volume=1_500_000,
                )
            )
            ts += timedelta(hours=1)
            price *= 1.01

        engine = BacktestEngine(
            strategy=TrendFollowingStrategy(StrategySection(), timeframe="hour"),
            risk_manager=RiskManager(RiskSection()),
            backtest=BacktestSection(initial_cash=1_000_000, warmup_bars=30),
            slippage_bps=2,
            commission_bps=2,
        )
        result = engine.run_with_instruments({"SBER": candles}, {"SBER": instrument})

        self.assertGreaterEqual(len(result.trades), 1)
        self.assertGreaterEqual(len(result.equity_curve), len(candles))
        self.assertGreater(result.portfolio.cash, 900_000)


if __name__ == "__main__":
    unittest.main()
