from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from samosbor.autonomy.effective_config import (
    base_strategy_values,
    build_effective_config_guardrail_payload,
    build_effective_strategy_overrides,
    default_effective_config_path,
    summarize_effective_config_sources,
    write_effective_config,
)
from samosbor.config import load_config
from samosbor.domain import PortfolioState, SignalDirection, TradeRecord
from samosbor.reporting.paper_report import build_paper_report_payload


def _trade(
    *,
    entry_time: datetime,
    exit_time: datetime,
    net_pnl: float,
) -> TradeRecord:
    return TradeRecord(
        symbol="CNYRUBF",
        direction=SignalDirection.LONG,
        quantity_lots=1,
        entry_time=entry_time,
        exit_time=exit_time,
        entry_price=100.0,
        exit_price=100.0 + net_pnl,
        gross_pnl=net_pnl,
        net_pnl=net_pnl,
        reason="stop-loss" if net_pnl < 0 else "take-profit",
        signal_strength=0.5,
    )


class EffectiveConfigTest(unittest.TestCase):
    def test_default_effective_config_path_reuses_existing_effective_file(self):
        original = Path("configs/server_tbank_cnyrubf_premium.toml")
        effective = Path("configs/server_tbank_cnyrubf_premium.effective.toml")
        self.assertEqual(
            default_effective_config_path(original).name,
            "server_tbank_cnyrubf_premium.effective.toml",
        )
        self.assertEqual(default_effective_config_path(effective).name, effective.name)

    def test_latest_candidate_waits_for_second_confirmation_before_activation(self):
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
                    "current_min_signal_strength": 0.0,
                    "recommended_min_signal_strength": 0.0,
                },
            )

            config = load_config(base_config)
            sources = summarize_effective_config_sources(root / "runs" / "autotune")
            overrides = build_effective_strategy_overrides(config)
            output_config = config_dir / "paper.effective.toml"
            write_effective_config(base_config, output_config, strategy_overrides=overrides)
            loaded = load_config(output_config)

            self.assertEqual(loaded.strategy.fast_window, 10)
            self.assertEqual(loaded.strategy.slow_window, 40)
            self.assertFalse(loaded.strategy.require_breakout)
            self.assertAlmostEqual(loaded.strategy.atr_stop_multiple, 1.5)
            self.assertAlmostEqual(loaded.strategy.reward_to_risk, 2.0)
            self.assertAlmostEqual(loaded.strategy.min_signal_strength, 0.0)
            self.assertAlmostEqual(loaded.strategy.min_trend_strength, 0.002)
            self.assertAlmostEqual(loaded.strategy.adx_min, 20.0)
            self.assertEqual(loaded.strategy.allowed_entry_hours, [9, 10, 12])
            self.assertFalse(sources[0]["activation"]["confirmed"])
            self.assertTrue(sources[0]["activation"]["pending_activation"])
            self.assertEqual(sources[0]["activation"]["confirmation_count"], 1)
            self.assertEqual(sources[1]["selected_values"]["atr_stop_multiple"], 1.5)
            self.assertEqual(sources[3]["selected_values"]["min_signal_strength"], 0.0)

    def test_effective_config_uses_confirmed_autotune_values(self):
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

            for stamp in ("20260101-000001", "20260102-000001"):
                self._write_json(
                    autotune_dir / "strategy" / stamp / "strategy_tuning.json",
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
                    autotune_dir / "exits" / stamp / "exit_tuning.json",
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
                autotune_dir / "entry-schedule" / "20260102-000001" / "schedule_tuning.json",
                {
                    "changed": False,
                    "reason": "insufficient evidence for change",
                    "current_hours": [9, 10, 12],
                    "proposed_hours": [9, 10, 12],
                },
            )
            self._write_json(
                autotune_dir / "entry-quality" / "20260102-000001" / "entry_quality_tuning.json",
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
            self.assertTrue(sources[0]["activation"]["confirmed"])
            self.assertEqual(sources[0]["activation"]["confirmation_count"], 2)
            self.assertEqual(sources[1]["selected_values"]["atr_stop_multiple"], 1.75)
            self.assertEqual(sources[2]["selected_values"]["allowed_entry_hours"], [9, 10, 12])
            self.assertEqual(sources[3]["selected_values"]["min_signal_strength"], 0.2)

    def test_guardrail_rolls_back_to_base_when_recent_window_turns_negative(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config_dir = root / "configs"
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

            config = load_config(base_config)
            paper_report = build_paper_report_payload(
                PortfolioState(cash=100_000.0, realized_pnl=-400.0, peak_equity=100_500.0),
                trades=[
                    _trade(
                        entry_time=datetime(2025, 1, 15, 8, 0, tzinfo=timezone.utc),
                        exit_time=datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc),
                        net_pnl=-120.0,
                    ),
                    _trade(
                        entry_time=datetime(2025, 1, 15, 12, 0, tzinfo=timezone.utc),
                        exit_time=datetime(2025, 1, 15, 14, 0, tzinfo=timezone.utc),
                        net_pnl=-110.0,
                    ),
                    _trade(
                        entry_time=datetime(2025, 1, 16, 8, 0, tzinfo=timezone.utc),
                        exit_time=datetime(2025, 1, 16, 10, 0, tzinfo=timezone.utc),
                        net_pnl=-100.0,
                    ),
                    _trade(
                        entry_time=datetime(2025, 1, 16, 12, 0, tzinfo=timezone.utc),
                        exit_time=datetime(2025, 1, 16, 14, 0, tzinfo=timezone.utc),
                        net_pnl=-90.0,
                    ),
                    _trade(
                        entry_time=datetime(2025, 1, 17, 8, 0, tzinfo=timezone.utc),
                        exit_time=datetime(2025, 1, 17, 10, 0, tzinfo=timezone.utc),
                        net_pnl=-80.0,
                    ),
                    _trade(
                        entry_time=datetime(2025, 1, 17, 12, 0, tzinfo=timezone.utc),
                        exit_time=datetime(2025, 1, 17, 14, 0, tzinfo=timezone.utc),
                        net_pnl=-70.0,
                    ),
                ],
                timezone_name="Europe/Moscow",
                report_date=date(2025, 1, 17),
                days=3,
            )
            decision = build_effective_config_guardrail_payload(
                base_values=base_strategy_values(config),
                source_summaries=[
                    {
                        "source": "strategy",
                        "selected_values": {
                            "fast_window": 12,
                            "slow_window": 48,
                        },
                    },
                    {
                        "source": "entry-quality",
                        "selected_values": {
                            "min_signal_strength": 0.25,
                        },
                    },
                ],
                paper_report=paper_report,
                guardrail_days=3,
                min_recent_trades=6,
            )

            self.assertTrue(decision["rollback_to_base"])
            self.assertEqual(decision["active_sources"], ["strategy", "entry-quality"])
            self.assertIn("fast_window", decision["active_override_keys"])
            self.assertIn("min_signal_strength", decision["active_override_keys"])
            self.assertLess(decision["recent_summary"]["net_pnl_rub"], 0)

    @staticmethod
    def _write_json(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
