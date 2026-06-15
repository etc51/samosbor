from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from samosbor.backtest.engine import BacktestEngine
from samosbor.config import BacktestSection, RiskSection, StrategySection
from samosbor.domain import Candle, ExitReason, Instrument, InstrumentType, Signal, SignalDirection
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

    def test_backtest_can_force_flatten_position_in_session_window(self):
        instrument = Instrument(symbol="SBER", instrument_type=InstrumentType.STOCK, lot_size=1)
        candles = [
            Candle(
                timestamp=datetime(2025, 1, 1, 14, 0, tzinfo=timezone.utc),
                open=100.0,
                high=100.4,
                low=99.8,
                close=100.0,
                volume=2_000_000,
            ),
            Candle(
                timestamp=datetime(2025, 1, 1, 15, 0, tzinfo=timezone.utc),
                open=100.0,
                high=100.5,
                low=99.9,
                close=100.2,
                volume=2_200_000,
            ),
        ]

        class FakeIntradayStrategy:
            def prepare_history(self, instrument, candles):
                return None

            def generate_signal(self, instrument, history):
                if len(history) != 1:
                    return None
                return Signal(
                    instrument=instrument,
                    direction=SignalDirection.LONG,
                    strength=0.8,
                    entry_price=history[-1].close,
                    stop_price=95.0,
                    take_profit=110.0,
                    reason="test-entry",
                )

            def allows_entry_at(self, timestamp):
                return True

            def should_force_flatten_at(self, timestamp):
                return timestamp == datetime(2025, 1, 1, 15, 0, tzinfo=timezone.utc)

            def entry_block_reason_at(self, timestamp):
                return None

            def entry_block_reason_for_instrument(self, instrument, timestamp, direction=None):
                return None

        engine = BacktestEngine(
            strategy=FakeIntradayStrategy(),
            risk_manager=RiskManager(
                RiskSection(max_risk_per_trade=0.01, max_gross_exposure=10.0, max_positions=1)
            ),
            backtest=BacktestSection(initial_cash=100_000, warmup_bars=1),
            slippage_bps=0,
            commission_bps=0,
        )
        result = engine.run_with_instruments({"SBER": candles}, {"SBER": instrument})

        self.assertEqual(len(result.trades), 1)
        self.assertEqual(result.trades[0].reason, ExitReason.SESSION_FLAT.value)


if __name__ == "__main__":
    unittest.main()
