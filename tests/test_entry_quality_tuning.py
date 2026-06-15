from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from samosbor.autonomy.entry_quality_tuning import (
    build_entry_quality_tuning_payload,
    build_signal_strength_breakdown,
)
from samosbor.config import BacktestSection, ResearchSection
from samosbor.domain import SignalDirection, TradeRecord


def _trade(index: int, signal_strength: float, net_pnl: float) -> TradeRecord:
    opened = datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)
    closed = opened + timedelta(hours=1)
    return TradeRecord(
        symbol="CNYRUBF",
        direction=SignalDirection.LONG,
        quantity_lots=1,
        entry_time=opened,
        exit_time=closed,
        entry_price=100.0,
        exit_price=101.0,
        gross_pnl=net_pnl,
        net_pnl=net_pnl,
        reason="take-profit" if net_pnl > 0 else "stop-loss",
        signal_strength=signal_strength,
    )


class EntryQualityTuningTest(unittest.TestCase):
    def test_signal_strength_breakdown_groups_recent_trades(self):
        rows = build_signal_strength_breakdown(
            [
                _trade(0, 0.21, -100.0),
                _trade(1, 0.24, -80.0),
                _trade(2, 0.71, 120.0),
            ],
            bucket_size=0.1,
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["bucket_start"], 0.2)
        self.assertEqual(rows[0]["net_pnl_rub"], -180.0)
        self.assertEqual(rows[1]["bucket_start"], 0.7)
        self.assertEqual(rows[1]["net_pnl_rub"], 120.0)

    def test_entry_quality_recommends_higher_threshold_when_low_strength_trades_drag(self):
        trades = [
            _trade(0, 0.22, -110.0),
            _trade(1, 0.24, -90.0),
            _trade(2, 0.28, -80.0),
            _trade(3, 0.31, -70.0),
            _trade(4, 0.72, 120.0),
            _trade(5, 0.75, 110.0),
            _trade(6, 0.79, 130.0),
            _trade(7, 0.83, 140.0),
        ]

        payload = build_entry_quality_tuning_payload(
            trades=trades,
            current_min_signal_strength=0.0,
            backtest=BacktestSection(initial_cash=1_000_000),
            research=ResearchSection(target_monthly_profit_rub=7_500.0),
            lookback_trades=8,
            min_trades=4,
            min_trade_retention_ratio=0.5,
            min_expectancy_improvement_rub=50.0,
            bucket_step=0.05,
        )

        self.assertTrue(payload["changed"])
        self.assertGreaterEqual(payload["recommended_min_signal_strength"], 0.7)
        self.assertEqual(payload["reason"], "signal-strength threshold improved recent paper expectancy")

    def test_entry_quality_reports_insufficient_evidence_for_legacy_trades(self):
        trades = [
            _trade(0, 0.0, 50.0),
            _trade(1, 0.0, -20.0),
        ]

        payload = build_entry_quality_tuning_payload(
            trades=trades,
            current_min_signal_strength=0.0,
            backtest=BacktestSection(initial_cash=1_000_000),
            research=ResearchSection(target_monthly_profit_rub=7_500.0),
            lookback_trades=10,
            min_trades=4,
        )

        self.assertFalse(payload["changed"])
        self.assertEqual(payload["reason"], "insufficient paper trades with signal strength evidence")


if __name__ == "__main__":
    unittest.main()
