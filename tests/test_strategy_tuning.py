from __future__ import annotations

import unittest

from samosbor.autonomy.strategy_tuning import (
    adapt_strategy_tuning_research,
    build_strategy_tuning_payload,
)
from samosbor.config import BacktestSection, ResearchSection, StrategySection
from samosbor.research.targets import (
    effective_target_monthly_profit_rub,
    effective_target_monthly_return_pct,
)


class ResearchTargetTest(unittest.TestCase):
    def test_effective_target_prefers_profit_goal_when_present(self):
        backtest = BacktestSection(initial_cash=1_000_000)
        research = ResearchSection(target_monthly_return_pct=5.0, target_monthly_profit_rub=7_500.0)

        self.assertEqual(effective_target_monthly_profit_rub(research, backtest), 7_500.0)
        self.assertEqual(effective_target_monthly_return_pct(research, backtest), 0.75)


class StrategyTuningTest(unittest.TestCase):
    def test_adaptive_research_shrinks_walk_forward_window_to_fit_history(self):
        research = ResearchSection(
            walk_forward_train_months=6,
            walk_forward_test_months=1,
            walk_forward_step_months=1,
            subset_min_size=1,
            subset_max_size=2,
        )

        adjusted, meta = adapt_strategy_tuning_research(
            research,
            available_months=4,
            fixed_subset_size=1,
        )

        self.assertIsNotNone(adjusted)
        self.assertTrue(meta["history_was_adapted"])
        self.assertEqual(adjusted.walk_forward_train_months, 3)
        self.assertEqual(adjusted.walk_forward_test_months, 1)
        self.assertEqual(adjusted.subset_min_size, 1)
        self.assertEqual(adjusted.subset_max_size, 1)

    def test_strategy_tuning_accepts_candidate_when_guardrails_pass(self):
        current = StrategySection(
            style="ema_adx_macd",
            fast_window=10,
            slow_window=40,
            require_breakout=False,
            atr_stop_multiple=1.5,
            reward_to_risk=2.0,
            min_trend_strength=0.002,
            adx_min=20.0,
        )
        candidate = StrategySection(
            style="ema_adx_macd",
            fast_window=10,
            slow_window=40,
            require_breakout=True,
            atr_stop_multiple=1.5,
            reward_to_risk=2.0,
            min_trend_strength=0.002,
            adx_min=15.0,
        )
        payload = build_strategy_tuning_payload(
            current_strategy=current,
            candidate_strategy=candidate,
            baseline_latest_test_summary={
                "total_return_pct": 0.4,
                "normalized_monthly_return_pct": 0.4,
                "max_drawdown_pct": 1.8,
                "sharpe_ratio": 0.3,
            },
            candidate_latest_test_summary={
                "total_return_pct": 1.1,
                "normalized_monthly_return_pct": 1.1,
                "max_drawdown_pct": 2.1,
                "sharpe_ratio": 0.7,
            },
            walk_forward_summary={
                "average_test_normalized_monthly_return_pct": 0.8,
                "probability_positive_pct": 66.7,
            },
            walk_forward_config={
                "train_months": 3,
                "test_months": 1,
                "step_months": 1,
            },
            backtest=BacktestSection(initial_cash=1_000_000),
            research=ResearchSection(target_monthly_profit_rub=7_500.0),
            research_window={"available_months": 4, "usable": True},
        )

        self.assertTrue(payload["changed"])
        self.assertEqual(payload["patch_values"]["require_breakout"], True)
        self.assertEqual(payload["patch_values"]["adx_min"], 15.0)

    def test_strategy_tuning_rejects_candidate_when_drawdown_deteriorates_too_much(self):
        current = StrategySection(style="ema_adx_macd")
        candidate = StrategySection(style="ema_adx_macd", reward_to_risk=1.5)
        payload = build_strategy_tuning_payload(
            current_strategy=current,
            candidate_strategy=candidate,
            baseline_latest_test_summary={
                "total_return_pct": 0.6,
                "normalized_monthly_return_pct": 0.6,
                "max_drawdown_pct": 1.0,
                "sharpe_ratio": 0.5,
            },
            candidate_latest_test_summary={
                "total_return_pct": 1.2,
                "normalized_monthly_return_pct": 1.2,
                "max_drawdown_pct": 3.5,
                "sharpe_ratio": 0.8,
            },
            walk_forward_summary={
                "average_test_normalized_monthly_return_pct": 0.9,
                "probability_positive_pct": 75.0,
            },
            walk_forward_config={
                "train_months": 3,
                "test_months": 1,
                "step_months": 1,
            },
            backtest=BacktestSection(initial_cash=1_000_000),
            research=ResearchSection(target_monthly_profit_rub=7_500.0),
            research_window={"available_months": 4, "usable": True},
        )

        self.assertFalse(payload["changed"])
        self.assertEqual(payload["reason"], "candidate failed one or more safety guardrails")


if __name__ == "__main__":
    unittest.main()
