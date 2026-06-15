from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

from samosbor.autonomy.signal_feedback import (
    default_signal_horizon_bars,
    load_signal_feedback,
    record_shadow_signal,
    resolve_pending_signals,
    resolved_feedback_to_trades,
    save_signal_feedback,
    signal_feedback_path,
)
from samosbor.domain import Candle, Instrument, InstrumentType, Signal, SignalDirection


class SignalFeedbackTest(unittest.TestCase):
    def test_signal_feedback_path_uses_state_stem(self):
        path = signal_feedback_path(Path("state/server_state.json"))
        self.assertEqual(str(path).replace("\\", "/"), "state/server_state_signal_feedback.json")

    def test_record_and_resolve_shadow_signal(self):
        payload = {"pending": [], "resolved": []}
        signal = Signal(
            instrument=Instrument(symbol="CNYRUBF", instrument_type=InstrumentType.FUTURE, lot_size=1),
            direction=SignalDirection.LONG,
            strength=0.72,
            entry_price=100.0,
            stop_price=98.0,
            take_profit=104.0,
            reason="test",
        )
        opened_at = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
        record_shadow_signal(payload, signal, timestamp=opened_at, horizon_bars=3)

        candles = [
            Candle(
                timestamp=opened_at + timedelta(hours=1),
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=1_000_000,
            ),
            Candle(
                timestamp=opened_at + timedelta(hours=2),
                open=100.5,
                high=104.5,
                low=100.0,
                close=104.2,
                volume=1_000_000,
            ),
        ]

        resolved = resolve_pending_signals(payload, {"CNYRUBF": candles})

        self.assertEqual(len(payload["pending"]), 0)
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["outcome_reason"], "take-profit")
        trades = resolved_feedback_to_trades(payload)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].signal_strength, 0.72)
        self.assertEqual(trades[0].reason, "take-profit")

    def test_shadow_signal_can_expire(self):
        payload = {"pending": [], "resolved": []}
        signal = Signal(
            instrument=Instrument(symbol="CNYRUBF", instrument_type=InstrumentType.FUTURE, lot_size=1),
            direction=SignalDirection.SHORT,
            strength=0.51,
            entry_price=100.0,
            stop_price=102.0,
            take_profit=96.0,
            reason="test",
        )
        opened_at = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
        record_shadow_signal(payload, signal, timestamp=opened_at, horizon_bars=2)
        candles = [
            Candle(
                timestamp=opened_at + timedelta(hours=1),
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.2,
                volume=1_000_000,
            ),
            Candle(
                timestamp=opened_at + timedelta(hours=2),
                open=100.2,
                high=101.2,
                low=99.5,
                close=100.8,
                volume=1_000_000,
            ),
        ]
        resolve_pending_signals(payload, {"CNYRUBF": candles})
        trades = resolved_feedback_to_trades(payload)

        self.assertEqual(trades[0].reason, "expired")
        self.assertAlmostEqual(trades[0].net_pnl, -0.8, places=6)

    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "signal_feedback.json"
            payload = {"pending": [{"symbol": "CNYRUBF"}], "resolved": []}
            save_signal_feedback(path, payload)
            loaded = load_signal_feedback(path)
            self.assertEqual(loaded["pending"][0]["symbol"], "CNYRUBF")

    def test_default_signal_horizon_bars_has_hourly_default(self):
        self.assertEqual(default_signal_horizon_bars("hour"), 24)
        self.assertEqual(default_signal_horizon_bars("unknown"), 24)


if __name__ == "__main__":
    unittest.main()
