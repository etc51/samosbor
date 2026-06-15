from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from samosbor.domain import Candle
from samosbor.offline_parquet_cache import (
    candles_to_frame,
    incremental_fetch_start,
    latest_candle_timestamp,
    load_candle_frame,
    merge_candle_frames,
    write_candle_frame,
)


class OfflineParquetCacheTest(unittest.TestCase):
    def test_merge_candle_frames_replaces_overlap_and_sorts_index(self):
        base_time = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
        existing = candles_to_frame(
            [
                Candle(base_time, 100.0, 101.0, 99.0, 100.5, 10.0),
                Candle(base_time + timedelta(minutes=30), 101.0, 102.0, 100.0, 101.5, 11.0),
            ]
        )
        fresh = candles_to_frame(
            [
                Candle(base_time + timedelta(minutes=30), 101.5, 103.0, 101.0, 102.5, 12.0),
                Candle(base_time + timedelta(minutes=60), 102.5, 104.0, 102.0, 103.5, 13.0),
            ]
        )

        merged = merge_candle_frames(existing, fresh)

        self.assertEqual(len(merged), 3)
        self.assertEqual(float(merged.iloc[1]["close"]), 102.5)
        self.assertEqual(float(merged.iloc[2]["close"]), 103.5)
        self.assertEqual(merged.index.name, "time")

    def test_load_and_write_round_trip_preserves_latest_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "SBER_30min.parquet"
            candles = [
                Candle(
                    datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
                    100.0,
                    101.0,
                    99.0,
                    100.5,
                    10.0,
                ),
                Candle(
                    datetime(2026, 6, 1, 10, 30, tzinfo=timezone.utc),
                    100.5,
                    102.0,
                    100.0,
                    101.5,
                    12.0,
                ),
            ]
            frame = candles_to_frame(candles)
            write_candle_frame(path, frame)

            loaded = load_candle_frame(path)

            self.assertEqual(len(loaded), 2)
            self.assertEqual(
                latest_candle_timestamp(loaded),
                datetime(2026, 6, 1, 10, 30, tzinfo=timezone.utc),
            )

    def test_incremental_fetch_start_uses_overlap_when_cache_exists(self):
        latest = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
        fetch_from = incremental_fetch_start(
            latest,
            bootstrap_history_days=120,
            overlap_hours=48,
        )

        self.assertEqual(fetch_from, latest - timedelta(hours=48))

    def test_incremental_fetch_start_bootstraps_when_cache_missing(self):
        before = datetime.now(timezone.utc) - timedelta(days=3)
        fetch_from = incremental_fetch_start(
            None,
            bootstrap_history_days=3,
            overlap_hours=48,
        )
        after = datetime.now(timezone.utc) - timedelta(days=3, minutes=-1)

        self.assertGreaterEqual(fetch_from, before)
        self.assertLessEqual(fetch_from, after)


if __name__ == "__main__":
    unittest.main()
