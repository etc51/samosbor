from __future__ import annotations

import unittest
from datetime import datetime, timezone

from samosbor.domain import ExitReason, Instrument, InstrumentType, PortfolioState, Signal, SignalDirection
from samosbor.execution.paper import LocalPaperBroker


class PaperBrokerTest(unittest.TestCase):
    def test_round_trip_trade_updates_cash_and_records_trade(self):
        broker = LocalPaperBroker.fresh(100_000, slippage_bps=0, commission_bps=0)
        instrument = Instrument(symbol="SBER", instrument_type=InstrumentType.STOCK, lot_size=10)
        signal = Signal(
            instrument=instrument,
            direction=SignalDirection.LONG,
            strength=0.8,
            entry_price=100.0,
            stop_price=95.0,
            take_profit=110.0,
            reason="test",
        )

        opened = broker.open_position(signal, 2, datetime(2025, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(opened.quantity_units, 20)
        trade = broker.close_position(
            "SBER",
            price=110.0,
            timestamp=datetime(2025, 1, 2, tzinfo=timezone.utc),
            reason=ExitReason.TAKE_PROFIT,
        )

        self.assertIsNotNone(trade)
        self.assertEqual(len(broker.trades), 1)
        self.assertGreater(broker.portfolio.cash, 100_000)


if __name__ == "__main__":
    unittest.main()
