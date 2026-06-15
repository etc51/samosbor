from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from samosbor.autonomy.entry_schedule import (
    build_entry_schedule_tuning_payload,
    write_entry_schedule_tuning,
)
from samosbor.domain import PortfolioState, SignalDirection, TradeRecord
from samosbor.reporting.paper_report import build_paper_report_payload, write_paper_report


def _trade(
    *,
    symbol: str,
    entry_time: datetime,
    exit_time: datetime,
    net_pnl: float,
    reason: str = "take-profit",
) -> TradeRecord:
    return TradeRecord(
        symbol=symbol,
        direction=SignalDirection.LONG,
        quantity_lots=1,
        entry_time=entry_time,
        exit_time=exit_time,
        entry_price=100.0,
        exit_price=101.0,
        gross_pnl=net_pnl,
        net_pnl=net_pnl,
        reason=reason,
    )


class PaperReportTest(unittest.TestCase):
    def test_paper_report_filters_by_moscow_date_and_writes_files(self):
        portfolio = PortfolioState(cash=100_000.0, realized_pnl=50.0, peak_equity=100_100.0)
        trades = [
            _trade(
                symbol="CNYRUBF",
                entry_time=datetime(2025, 1, 14, 6, 0, tzinfo=timezone.utc),
                exit_time=datetime(2025, 1, 14, 22, 15, tzinfo=timezone.utc),
                net_pnl=100.0,
            ),
            _trade(
                symbol="IMOEXF",
                entry_time=datetime(2025, 1, 14, 8, 0, tzinfo=timezone.utc),
                exit_time=datetime(2025, 1, 14, 21, 30, tzinfo=timezone.utc),
                net_pnl=-50.0,
                reason="stop-loss",
            ),
            _trade(
                symbol="USDRUBF",
                entry_time=datetime(2025, 1, 15, 18, 0, tzinfo=timezone.utc),
                exit_time=datetime(2025, 1, 15, 21, 10, tzinfo=timezone.utc),
                net_pnl=25.0,
            ),
        ]

        payload = build_paper_report_payload(
            portfolio,
            trades,
            timezone_name="Europe/Moscow",
            report_date=date(2025, 1, 15),
            days=1,
        )

        self.assertEqual(payload["summary"]["trades"], 2)
        self.assertEqual(payload["summary"]["net_pnl_rub"], 50.0)
        self.assertEqual(payload["summary"]["win_rate_pct"], 50.0)
        self.assertEqual(len(payload["closed_trades"]), 2)
        self.assertEqual(
            [row["entry_hour"] for row in payload["entry_hour_breakdown"]],
            [9, 11],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            write_paper_report(output_dir, payload)
            self.assertTrue((output_dir / "summary.json").exists())
            self.assertTrue((output_dir / "summary.md").exists())
            self.assertTrue((output_dir / "trades.csv").exists())


class EntryScheduleAutonomyTest(unittest.TestCase):
    def test_tuning_recommends_safe_add_remove_changes(self):
        portfolio = PortfolioState(cash=100_000.0, peak_equity=100_000.0)
        trades = [
            _trade(
                symbol="CNYRUBF",
                entry_time=datetime(2025, 1, 10, 6, 0, tzinfo=timezone.utc),
                exit_time=datetime(2025, 1, 10, 8, 0, tzinfo=timezone.utc),
                net_pnl=-100.0,
            ),
            _trade(
                symbol="CNYRUBF",
                entry_time=datetime(2025, 1, 11, 6, 5, tzinfo=timezone.utc),
                exit_time=datetime(2025, 1, 11, 8, 5, tzinfo=timezone.utc),
                net_pnl=-120.0,
            ),
            _trade(
                symbol="CNYRUBF",
                entry_time=datetime(2025, 1, 12, 6, 10, tzinfo=timezone.utc),
                exit_time=datetime(2025, 1, 12, 8, 10, tzinfo=timezone.utc),
                net_pnl=-80.0,
            ),
            _trade(
                symbol="CNYRUBF",
                entry_time=datetime(2025, 1, 13, 7, 0, tzinfo=timezone.utc),
                exit_time=datetime(2025, 1, 13, 9, 0, tzinfo=timezone.utc),
                net_pnl=-40.0,
            ),
            _trade(
                symbol="CNYRUBF",
                entry_time=datetime(2025, 1, 14, 7, 10, tzinfo=timezone.utc),
                exit_time=datetime(2025, 1, 14, 9, 10, tzinfo=timezone.utc),
                net_pnl=-30.0,
            ),
            _trade(
                symbol="CNYRUBF",
                entry_time=datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc),
                exit_time=datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc),
                net_pnl=200.0,
            ),
            _trade(
                symbol="CNYRUBF",
                entry_time=datetime(2025, 1, 16, 9, 5, tzinfo=timezone.utc),
                exit_time=datetime(2025, 1, 16, 10, 5, tzinfo=timezone.utc),
                net_pnl=150.0,
            ),
            _trade(
                symbol="CNYRUBF",
                entry_time=datetime(2025, 1, 17, 9, 10, tzinfo=timezone.utc),
                exit_time=datetime(2025, 1, 17, 10, 10, tzinfo=timezone.utc),
                net_pnl=125.0,
            ),
        ]

        payload = build_entry_schedule_tuning_payload(
            portfolio,
            trades,
            timezone_name="Europe/Moscow",
            current_hours=[9, 10, 11],
            report_date=date(2025, 1, 31),
            lookback_days=45,
            min_trades_per_hour=3,
            max_hours_to_add=1,
            max_hours_to_remove=1,
        )

        self.assertTrue(payload["changed"])
        self.assertEqual(payload["removals"], [9])
        self.assertEqual(payload["additions"], [12])
        self.assertEqual(payload["proposed_hours"], [10, 11, 12])

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            write_entry_schedule_tuning(output_dir, payload)
            self.assertTrue((output_dir / "schedule_tuning.json").exists())
            self.assertTrue((output_dir / "schedule_patch.toml").exists())
            self.assertTrue((output_dir / "summary.md").exists())


if __name__ == "__main__":
    unittest.main()
