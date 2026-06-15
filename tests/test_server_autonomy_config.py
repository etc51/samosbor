from __future__ import annotations

import unittest

from samosbor.server_autonomy_config import build_offline_autonomy_config_text


class ServerAutonomyConfigTest(unittest.TestCase):
    def test_build_offline_autonomy_config_rewrites_data_source_and_path(self):
        source = "\n".join(
            [
                "[app]",
                'timezone = "Europe/Moscow"',
                "",
                "[data]",
                'source = "tbank"',
                'timeframe = "30min"',
                "history_days = 120",
                'csv_path = "data/demo.csv"',
                "",
                "[strategy]",
                'style = "ema_adx_macd"',
                "",
            ]
        )
        rendered = build_offline_autonomy_config_text(
            source,
            parquet_dir_path="data/server_moex_strategy_lab_data_processed",
        )

        self.assertIn('source = "parquet-directory"', rendered)
        self.assertIn(
            'parquet_dir_path = "data/server_moex_strategy_lab_data_processed"',
            rendered,
        )
        self.assertNotIn('source = "tbank"', rendered)
        self.assertNotIn('csv_path = "data/demo.csv"', rendered)
        self.assertIn('[strategy]\nstyle = "ema_adx_macd"', rendered)

    def test_build_offline_autonomy_config_reuses_existing_parquet_key(self):
        source = "\n".join(
            [
                "[data]",
                'source = "csv"',
                'parquet_dir_path = "old/path"',
                'local_data_pack_path = "unused"',
                "",
                "[execution]",
                'mode = "local-paper"',
                "",
            ]
        )

        rendered = build_offline_autonomy_config_text(
            source,
            parquet_dir_path="data/new_path",
        )

        self.assertIn('source = "parquet-directory"', rendered)
        self.assertIn('parquet_dir_path = "data/new_path"', rendered)
        self.assertNotIn('parquet_dir_path = "old/path"', rendered)
        self.assertNotIn('local_data_pack_path = "unused"', rendered)

    def test_build_offline_autonomy_config_requires_data_section(self):
        with self.assertRaises(ValueError):
            build_offline_autonomy_config_text(
                "[app]\nname = \"samosbor\"\n",
                parquet_dir_path="data/new_path",
            )


if __name__ == "__main__":
    unittest.main()
