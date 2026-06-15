from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from samosbor.config import load_config
from samosbor.orchestrator import TradingOrchestrator


class FakeNightlyOrchestrator(TradingOrchestrator):
    def __init__(self, config):
        super().__init__(config)
        self.calls: list[str] = []
        self.walk_forward_adaptive_history: bool | None = None

    def run_paper_report(self, *, days=1, report_date=None, timezone_name=None):
        self.calls.append("paper-report")
        return {
            "period": {"days": days},
            "portfolio": {"trading_halted": False},
            "summary": {
                "trades": 6,
                "net_pnl_rub": 125.0,
                "win_rate_pct": 50.0,
                "profit_factor": 1.2,
                "expectancy_rub": 20.83,
            },
            "comparison_to_previous_window": {
                "delta": {"trades": 2, "net_pnl_rub": 75.0},
            },
            "output_dir": "runs/paper-reports/fake",
        }

    def tune_entry_schedule(
        self,
        *,
        lookback_days=45,
        report_date=None,
        timezone_name=None,
        min_trades_per_hour=3,
        max_hours_to_add=2,
        max_hours_to_remove=2,
    ):
        self.calls.append("tune-entry-hours")
        return {
            "changed": True,
            "reason": "hours updated from paper results",
            "current_hours": [9, 10],
            "proposed_hours": [10, 12],
            "additions": [12],
            "removals": [9],
            "output_dir": "runs/autotune/entry-schedule/fake",
        }

    def bootstrap_entry_feedback(self, *, replace_existing=False, max_signals_per_symbol=0):
        self.calls.append("bootstrap-entry-feedback")
        return {
            "generated_total": 12,
            "generated_by_symbol": {"CNYRUBF": 12},
            "resolved_signals": 12,
            "pending_signals": 0,
            "output_dir": "runs/autotune/entry-feedback-bootstrap/fake",
        }

    def tune_entry_symbols(
        self,
        *,
        lookback_days=45,
        report_date=None,
        timezone_name=None,
        min_trades_per_symbol=4,
        max_symbols_to_block=1,
        max_total_blocked_symbols=4,
    ):
        self.calls.append("tune-entry-symbols")
        return {
            "changed": False,
            "reason": "insufficient evidence for symbol restriction change",
            "current_blocked_symbols": [],
            "proposed_blocked_symbols": [],
            "additions": [],
            "output_dir": "runs/autotune/entry-symbols/fake",
        }

    def tune_entry_quality(
        self,
        *,
        lookback_trades=40,
        min_trades=8,
        min_trade_retention_ratio=0.5,
        min_expectancy_improvement_rub=50.0,
        bucket_step=0.05,
    ):
        self.calls.append("tune-entry-quality")
        return {
            "evidence_source": "signal-feedback",
            "changed": False,
            "reason": "no signal-strength threshold passed the safety guardrails",
            "current_min_signal_strength": 0.0,
            "recommended_min_signal_strength": 0.0,
            "lookback": {"eligible_trades": 12},
            "output_dir": "runs/autotune/entry-quality/fake",
        }

    def optimize_strategy(self):
        self.calls.append("optimize")
        return {
            "evaluated_candidates": 24,
            "best_candidate": {
                "symbols": ["CNYRUBF"],
                "style": "ema_adx_macd",
                "score": 12.3,
                "summary": {
                    "total_return_pct": 8.0,
                    "avg_monthly_return_pct": 1.1,
                    "max_drawdown_pct": 2.5,
                    "profit_factor": 1.6,
                    "trades": 18,
                },
            },
            "output_dir": "runs/optimizer/fake",
        }

    def run_walk_forward(self, *, adaptive_history=False):
        self.calls.append("walk-forward")
        self.walk_forward_adaptive_history = adaptive_history
        return {
            "config": {"train_months": 3, "test_months": 1, "step_months": 1},
            "summary": {"folds_evaluated": 4, "average_test_normalized_monthly_return_pct": 0.8},
            "available_months": ["2026-01", "2026-02", "2026-03", "2026-04"],
            "skipped_folds": 0,
            "output_dir": "runs/walk-forward/fake",
        }

    def run_monte_carlo(self):
        self.calls.append("monte-carlo")
        return {
            "target": {"monthly_profit_rub": 7500.0, "monthly_return_pct": 0.75},
            "backtest_summary": {"total_return_pct": 8.0},
            "monte_carlo": {"summary": {"probability_positive_pct": 64.0}},
            "output_dir": "runs/monte-carlo/fake",
        }

    def tune_strategy(
        self,
        *,
        min_monthly_improvement_pct=0.05,
        max_extra_drawdown_pct=1.0,
        min_positive_fold_probability_pct=55.0,
    ):
        self.calls.append("tune-strategy")
        return {
            "changed": False,
            "reason": "candidate failed one or more safety guardrails",
            "patch_values": {},
            "comparison": {"monthly_return_delta_pct": 0.0},
            "output_dir": "runs/autotune/strategy/fake",
        }

    def tune_exits(
        self,
        *,
        min_monthly_improvement_pct=0.03,
        max_extra_drawdown_pct=1.0,
        min_positive_fold_probability_pct=55.0,
    ):
        self.calls.append("tune-exits")
        return {
            "changed": False,
            "reason": "candidate exit settings failed one or more safety guardrails",
            "patch_values": {},
            "comparison": {"monthly_return_delta_pct": 0.0},
            "output_dir": "runs/autotune/exits/fake",
        }

    def refresh_effective_config(self, *, source_config_path, output_path=None):
        self.calls.append("refresh-effective-config")
        return {
            "source_config_path": str(Path(source_config_path).resolve()),
            "effective_config_path": str(Path(output_path).resolve()),
            "paper_only_mode": "local-paper",
            "allow_live_trading": False,
            "applied_strategy_overrides": {"fast_window": 10},
            "sources": [
                {
                    "source": "strategy",
                    "changed": False,
                    "selected_values": {"fast_window": 10},
                    "activation": {"required_confirmations": 2, "confirmed": False},
                }
            ],
            "rollback_guardrail": {
                "rollback_to_base": False,
                "reason": "no active overrides versus the base runtime config",
            },
            "output_dir": "runs/autotune/effective-config/fake",
        }


class NightlyAutonomyTest(unittest.TestCase):
    def test_nightly_autonomy_runs_all_steps_and_writes_summary(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config_dir = root / "configs"
            config_dir.mkdir(parents=True)
            active_config = config_dir / "paper.effective.toml"
            base_config = config_dir / "paper.toml"
            for config_path in (active_config, base_config):
                config_path.write_text(
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

            config = load_config(active_config)
            orchestrator = FakeNightlyOrchestrator(config)
            result = orchestrator.run_nightly_autonomy(
                active_config_path=active_config,
                base_config_path=base_config,
                effective_output_path=active_config,
            )

            self.assertEqual(
                orchestrator.calls,
                [
                    "paper-report",
                    "tune-entry-hours",
                    "tune-entry-symbols",
                    "bootstrap-entry-feedback",
                    "tune-entry-quality",
                    "optimize",
                    "walk-forward",
                    "monte-carlo",
                    "tune-strategy",
                    "tune-exits",
                    "refresh-effective-config",
                ],
            )
            self.assertEqual(result["analysis"]["paper_report"]["summary"]["trades"], 6)
            self.assertEqual(result["restrictions"]["entry_schedule"]["proposed_hours"], [10, 12])
            self.assertEqual(result["restrictions"]["entry_symbols"]["proposed_blocked_symbols"], [])
            self.assertEqual(result["research"]["optimizer"]["evaluated_candidates"], 24)
            self.assertEqual(result["research"]["walk_forward"]["summary"]["folds_evaluated"], 4)
            self.assertEqual(result["research"]["monte_carlo"]["monte_carlo_summary"]["probability_positive_pct"], 64.0)
            self.assertFalse(result["runtime"]["effective_config"]["rollback_guardrail"]["rollback_to_base"])
            self.assertTrue(orchestrator.walk_forward_adaptive_history)
            summary_dir = Path(result["output_dir"])
            self.assertTrue((summary_dir / "nightly_autonomy.json").exists())
            self.assertTrue((summary_dir / "summary.md").exists())
            persisted = json.loads((summary_dir / "nightly_autonomy.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["steps_executed"][0], "paper-report")
            self.assertEqual(persisted["steps_executed"][-1], "refresh-effective-config")


if __name__ == "__main__":
    unittest.main()
