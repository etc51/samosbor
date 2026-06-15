from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from samosbor.autonomy.effective_config import (
    build_effective_strategy_overrides,
    default_effective_config_path,
    summarize_effective_config_sources,
    write_effective_config,
)
from samosbor.config import load_config


class EffectiveConfigTest(unittest.TestCase):
    def test_default_effective_config_path_reuses_existing_effective_file(self):
        original = Path("configs/server_tbank_cnyrubf_premium.toml")
        effective = Path("configs/server_tbank_cnyrubf_premium.effective.toml")
        self.assertEqual(
            default_effective_config_path(original).name,
            "server_tbank_cnyrubf_premium.effective.toml",
        )
        self.assertEqual(default_effective_config_path(effective).name, effective.name)

    def test_effective_config_uses_latest_autotune_values(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config_dir = root / "configs"
            autotune_dir = root / "runs" / "autotune"
            config_dir.mkdir(parents=True)

            base_config = config_dir / "paper.toml"
            base_config.write_text(
                "\n".join(
                    [
                        "[app]",
                        'timezone = "Europe/Moscow"',
                        "",
                        "[data]",
                        'source = "csv"',
                        'csv_path = "data/demo.csv"',
                        "",
                        "[strategy]",
                        'style = "ema_adx_macd"',
                        "fast_window = 10",
                        "slow_window = 40",
                        "require_breakout = false",
                        "atr_stop_multiple = 1.5",
                        "reward_to_risk = 2.0",
                        "min_signal_strength = 0.0",
                        "min_trend_strength = 0.002",
                        "adx_min = 20.0",
                        "allowed_entry_hours = [9, 10]",
                        "",
                        "[execution]",
                        'mode = "local-paper"',
                        "allow_live_trading = false",
                        'state_path = "state/paper_state.json"',
                        "",
                        "[backtest]",
                        "",
                        "[reporting]",
                        'output_dir = "runs"',
                        "",
                        "[research]",
                        "",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            self._write_json(
                autotune_dir / "strategy" / "20260101-000001" / "strategy_tuning.json",
                {
                    "changed": True,
                    "reason": "strategy candidate passed guardrails",
                    "current_strategy": {
                        "style": "ema_adx_macd",
                        "fast_window": 10,
                        "slow_window": 40,
                        "require_breakout": False,
                        "min_trend_strength": 0.002,
                        "adx_min": 20.0,
                    },
                    "candidate_strategy": {
                        "style": "ema_adx_macd",
                        "fast_window": 12,
                        "slow_window": 48,
                        "require_breakout": True,
                        "min_trend_strength": 0.003,
                        "adx_min": 18.0,
                    },
                },
            )
            self._write_json(
                autotune_dir / "exits" / "20260101-000001" / "exit_tuning.json",
                {
                    "changed": True,
                    "reason": "exit candidate passed guardrails",
                    "current_exit_settings": {
                        "atr_stop_multiple": 1.5,
                        "reward_to_risk": 2.0,
                    },
                    "candidate_exit_settings": {
                        "atr_stop_multiple": 1.75,
                        "reward_to_risk": 2.5,
                    },
                },
            )
            self._write_json(
                autotune_dir / "entry-schedule" / "20260101-000001" / "schedule_tuning.json",
                {
                    "changed": False,
                    "reason": "insufficient evidence for change",
                    "current_hours": [9, 10, 12],
                    "proposed_hours": [9, 10, 12],
                },
            )
            self._write_json(
                autotune_dir / "entry-quality" / "20260101-000001" / "entry_quality_tuning.json",
                {
                    "changed": False,
                    "reason": "current threshold already matches the best candidate",
                    "current_min_signal_strength": 0.2,
                    "recommended_min_signal_strength": 0.2,
                },
            )

            config = load_config(base_config)
            sources = summarize_effective_config_sources(root / "runs" / "autotune")
            overrides = build_effective_strategy_overrides(config)
            output_config = config_dir / "paper.effective.toml"
            write_effective_config(base_config, output_config, strategy_overrides=overrides)
            loaded = load_config(output_config)

            self.assertEqual(loaded.strategy.fast_window, 12)
            self.assertEqual(loaded.strategy.slow_window, 48)
            self.assertTrue(loaded.strategy.require_breakout)
            self.assertAlmostEqual(loaded.strategy.atr_stop_multiple, 1.75)
            self.assertAlmostEqual(loaded.strategy.reward_to_risk, 2.5)
            self.assertAlmostEqual(loaded.strategy.min_signal_strength, 0.2)
            self.assertAlmostEqual(loaded.strategy.min_trend_strength, 0.003)
            self.assertAlmostEqual(loaded.strategy.adx_min, 18.0)
            self.assertEqual(loaded.strategy.allowed_entry_hours, [9, 10, 12])
            self.assertEqual(loaded.execution.mode.value, "local-paper")
            self.assertFalse(loaded.execution.allow_live_trading)
            self.assertEqual(len(sources), 4)
            self.assertEqual(sources[0]["source"], "strategy")
            self.assertEqual(sources[1]["selected_values"]["atr_stop_multiple"], 1.75)
            self.assertEqual(sources[2]["selected_values"]["allowed_entry_hours"], [9, 10, 12])
            self.assertEqual(sources[3]["selected_values"]["min_signal_strength"], 0.2)

    @staticmethod
    def _write_json(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
