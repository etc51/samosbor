from __future__ import annotations

import unittest
from datetime import datetime, timezone

from samosbor.config import RiskSection
from samosbor.domain import (
    Instrument,
    InstrumentType,
    PortfolioState,
    Position,
    Signal,
    SignalDirection,
)
from samosbor.risk.manager import RiskManager


def _stock_signal(symbol: str) -> Signal:
    return Signal(
        instrument=Instrument(symbol=symbol, instrument_type=InstrumentType.STOCK, lot_size=1),
        direction=SignalDirection.LONG,
        strength=0.8,
        entry_price=100.0,
        stop_price=99.0,
        take_profit=102.0,
        reason="test",
    )


class RiskManagerDiversificationTest(unittest.TestCase):
    def test_stock_position_is_capped_by_single_position_exposure_ratio(self):
        manager = RiskManager(
            RiskSection(
                max_risk_per_trade=0.02,
                max_gross_exposure=1.5,
                cash_reserve_ratio=0.0,
                max_positions=4,
                max_position_exposure_ratio=0.30,
            )
        )
        portfolio = PortfolioState(cash=300_000.0, peak_equity=300_000.0)

        decision = manager.approve(portfolio, _stock_signal("SBER"), {"SBER": 100.0}, [])

        self.assertTrue(decision.approved)
        self.assertEqual(decision.quantity_lots, 900)
        self.assertEqual(decision.estimated_notional_rub, 90_000.0)

    def test_position_cap_still_leaves_room_for_other_stocks(self):
        manager = RiskManager(
            RiskSection(
                max_risk_per_trade=0.02,
                max_gross_exposure=1.5,
                cash_reserve_ratio=0.10,
                max_positions=4,
                max_position_exposure_ratio=0.30,
            )
        )
        existing_instrument = Instrument(symbol="SBER", instrument_type=InstrumentType.STOCK, lot_size=1)
        now = datetime(2025, 1, 1, tzinfo=timezone.utc)
        portfolio = PortfolioState(
            cash=210_000.0,
            peak_equity=300_000.0,
            positions={
                "SBER": Position(
                    instrument=existing_instrument,
                    direction=SignalDirection.LONG,
                    quantity_lots=900,
                    entry_price=100.0,
                    entry_commission=0.0,
                    margin_requirement=0.0,
                    current_price=100.0,
                    stop_price=95.0,
                    take_profit=110.0,
                    opened_at=now,
                    updated_at=now,
                )
            },
        )

        decision = manager.approve(portfolio, _stock_signal("GAZP"), {"SBER": 100.0, "GAZP": 100.0}, [])

        self.assertTrue(decision.approved)
        self.assertEqual(decision.quantity_lots, 900)
        self.assertEqual(decision.estimated_notional_rub, 90_000.0)

    def test_futures_position_is_capped_by_single_position_exposure_ratio(self):
        manager = RiskManager(
            RiskSection(
                max_risk_per_trade=0.02,
                max_gross_exposure=2.0,
                cash_reserve_ratio=0.0,
                max_positions=4,
                max_position_exposure_ratio=0.30,
            )
        )
        portfolio = PortfolioState(cash=300_000.0, peak_equity=300_000.0)
        instrument = Instrument(
            symbol="RI",
            instrument_type=InstrumentType.FUTURE,
            lot_size=1,
            initial_margin_buy=500.0,
            initial_margin_sell=500.0,
        )
        signal = Signal(
            instrument=instrument,
            direction=SignalDirection.LONG,
            strength=0.7,
            entry_price=1_000.0,
            stop_price=990.0,
            take_profit=1_020.0,
            reason="test",
        )

        decision = manager.approve(portfolio, signal, {"RI": 1_000.0}, [])

        self.assertTrue(decision.approved)
        self.assertEqual(decision.quantity_lots, 90)
        self.assertEqual(decision.estimated_notional_rub, 90_000.0)


if __name__ == "__main__":
    unittest.main()
