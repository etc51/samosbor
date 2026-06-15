from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from pathlib import Path

from .autonomy.entry_schedule import (
    build_entry_schedule_tuning_payload,
    write_entry_schedule_tuning,
)
from .autonomy.entry_quality_tuning import (
    build_entry_quality_tuning_payload,
    write_entry_quality_tuning,
)
from .autonomy.exit_tuning import (
    build_exit_reason_breakdown,
    build_exit_tuning_payload,
    specialize_exit_tuning_research,
    write_exit_tuning,
)
from .autonomy.strategy_tuning import (
    adapt_strategy_tuning_research,
    build_strategy_tuning_payload,
    write_strategy_tuning,
)
from .config import AppConfig
from .config import StrategySection
from .data.csv_provider import CSVMarketDataProvider
from .data.moex_data_pack import MoexDataPackProvider
from .data.tbank import TBankMarketDataProvider
from .domain import ExitReason
from .execution.paper import LocalPaperBroker
from .execution.sandbox import TBankSandboxExecutor
from .reporting.metrics import compute_summary
from .reporting.paper_report import build_paper_report_payload, write_paper_report
from .reporting.research_writer import (
    write_monte_carlo_report,
    write_optimizer_report,
    write_walk_forward_report,
)
from .reporting.writer import write_backtest_report, write_json_payload, write_portfolio_snapshot
from .research.monte_carlo import MonteCarloSimulator
from .research.optimizer import ParameterOptimizer
from .research.targets import effective_target_monthly_profit_rub, effective_target_monthly_return_pct
from .research.walk_forward import (
    WalkForwardValidator,
    _available_months,
    _group_candles_by_month,
    _normalized_monthly_return_pct,
    _slice_grouped_candles,
    _trim_backtest_result,
)
from .risk.manager import RiskManager
from .safety import assert_paper_only_mode
from .strategy.trend_following import TrendFollowingStrategy
from .backtest.engine import BacktestEngine

LOGGER = logging.getLogger(__name__)


class TradingOrchestrator:
    def __init__(self, config: AppConfig):
        self.config = config

    def _data_provider(self):
        if self.config.data.source == "csv":
            return CSVMarketDataProvider(self.config.resolve_path(self.config.data.csv_path))
        if self.config.data.source == "moex-data-pack":
            return MoexDataPackProvider(
                self.config.resolve_path(self.config.data.local_data_pack_path),
                timeframe=self.config.data.timeframe,
                history_days=self.config.data.history_days,
            )
        if self.config.data.source == "tbank":
            return TBankMarketDataProvider(self.config)
        raise ValueError(f"Unsupported data source: {self.config.data.source}")

    def _strategy(self) -> TrendFollowingStrategy:
        return TrendFollowingStrategy(
            self.config.strategy,
            timeframe=self.config.data.timeframe,
        )

    def _risk_manager(self) -> RiskManager:
        return RiskManager(self.config.risk)

    def _load_paper_broker(self) -> LocalPaperBroker:
        state_path = self.config.resolve_path(self.config.execution.state_path)
        return LocalPaperBroker.load(
            state_path,
            initial_cash=self.config.backtest.initial_cash,
            slippage_bps=self.config.execution.slippage_bps,
            commission_bps=self.config.execution.commission_bps,
        )

    def _load_market_bundle(self):
        provider = self._data_provider()
        instruments = provider.resolve_universe(self.config.data.instruments)
        candles_by_symbol = provider.load_history(instruments)
        instruments_by_symbol = {instrument.symbol: instrument for instrument in instruments}
        return provider, instruments, candles_by_symbol, instruments_by_symbol

    def _run_backtest_bundle(
        self,
        candles_by_symbol: dict[str, list],
        instruments_by_symbol: dict[str, object],
        *,
        strategy_config: StrategySection | None = None,
    ):
        engine = BacktestEngine(
            strategy=TrendFollowingStrategy(
                strategy_config or self.config.strategy,
                timeframe=self.config.data.timeframe,
            ),
            risk_manager=self._risk_manager(),
            backtest=self.config.backtest,
            slippage_bps=self.config.execution.slippage_bps,
            commission_bps=self.config.execution.commission_bps,
        )
        result = engine.run_with_instruments(candles_by_symbol, instruments_by_symbol)
        summary = compute_summary(result, timeframe=self.config.data.timeframe)
        return result, summary

    def list_accounts(self) -> list[dict[str, str]]:
        provider = TBankMarketDataProvider(self.config)
        return provider.list_accounts()

    def init_sandbox(self, amount_rub: float) -> dict[str, object]:
        assert_paper_only_mode(
            self.config.execution.mode,
            allow_live_trading=self.config.execution.allow_live_trading,
            live_flag=False,
        )
        executor = TBankSandboxExecutor(self.config)
        account_id = executor.ensure_account()
        executor.fund_account(amount_rub)
        return {"account_id": account_id, "funded_rub": amount_rub}

    def run_backtest(self) -> dict[str, object]:
        assert_paper_only_mode(
            self.config.execution.mode,
            allow_live_trading=self.config.execution.allow_live_trading,
            live_flag=False,
        )
        _, _, candles_by_symbol, instruments_by_symbol = self._load_market_bundle()
        result, summary = self._run_backtest_bundle(candles_by_symbol, instruments_by_symbol)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        output_dir = self.config.resolve_path(self.config.reporting.output_dir) / "backtests" / stamp
        write_backtest_report(output_dir, result, summary)
        LOGGER.info("Backtest report written to %s", output_dir)
        return {"summary": summary, "output_dir": str(output_dir)}

    def optimize_strategy(self) -> dict[str, object]:
        assert_paper_only_mode(
            self.config.execution.mode,
            allow_live_trading=self.config.execution.allow_live_trading,
            live_flag=False,
        )
        _, _, candles_by_symbol, instruments_by_symbol = self._load_market_bundle()
        optimizer = ParameterOptimizer(
            base_strategy=self.config.strategy,
            risk=self.config.risk,
            backtest=self.config.backtest,
            research=self.config.research,
            timeframe=self.config.data.timeframe,
            slippage_bps=self.config.execution.slippage_bps,
            commission_bps=self.config.execution.commission_bps,
        )
        payload = optimizer.run(candles_by_symbol, instruments_by_symbol)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        output_dir = self.config.resolve_path(self.config.reporting.output_dir) / "optimizer" / stamp
        write_optimizer_report(output_dir, payload)
        payload["output_dir"] = str(output_dir)
        return payload

    def run_monte_carlo(self) -> dict[str, object]:
        assert_paper_only_mode(
            self.config.execution.mode,
            allow_live_trading=self.config.execution.allow_live_trading,
            live_flag=False,
        )
        _, _, candles_by_symbol, instruments_by_symbol = self._load_market_bundle()
        result, summary = self._run_backtest_bundle(candles_by_symbol, instruments_by_symbol)
        simulator = MonteCarloSimulator(
            iterations=self.config.research.monte_carlo_iterations,
            horizon_months=self.config.research.monte_carlo_horizon_months,
            target_monthly_return_pct=effective_target_monthly_return_pct(
                self.config.research,
                self.config.backtest,
            ),
            seed=self.config.research.random_seed,
        )
        payload = {
            "backtest_summary": summary,
            "target": {
                "monthly_profit_rub": round(
                    effective_target_monthly_profit_rub(self.config.research, self.config.backtest),
                    2,
                ),
                "monthly_return_pct": round(
                    effective_target_monthly_return_pct(self.config.research, self.config.backtest),
                    3,
                ),
            },
            "monte_carlo": simulator.run(result),
        }
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        output_dir = self.config.resolve_path(self.config.reporting.output_dir) / "monte-carlo" / stamp
        write_monte_carlo_report(output_dir, payload)
        payload["output_dir"] = str(output_dir)
        return payload

    def run_walk_forward(self) -> dict[str, object]:
        assert_paper_only_mode(
            self.config.execution.mode,
            allow_live_trading=self.config.execution.allow_live_trading,
            live_flag=False,
        )
        _, _, candles_by_symbol, instruments_by_symbol = self._load_market_bundle()
        validator = WalkForwardValidator(
            base_strategy=self.config.strategy,
            risk=self.config.risk,
            backtest=self.config.backtest,
            research=self.config.research,
            timeframe=self.config.data.timeframe,
            slippage_bps=self.config.execution.slippage_bps,
            commission_bps=self.config.execution.commission_bps,
        )
        payload = validator.run(candles_by_symbol, instruments_by_symbol)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        output_dir = self.config.resolve_path(self.config.reporting.output_dir) / "walk-forward" / stamp
        write_walk_forward_report(output_dir, payload)
        payload["output_dir"] = str(output_dir)
        return payload

    def tune_strategy(
        self,
        *,
        min_monthly_improvement_pct: float = 0.05,
        max_extra_drawdown_pct: float = 1.0,
        min_positive_fold_probability_pct: float = 55.0,
    ) -> dict[str, object]:
        assert_paper_only_mode(
            self.config.execution.mode,
            allow_live_trading=self.config.execution.allow_live_trading,
            live_flag=False,
        )
        _, instruments, candles_by_symbol, instruments_by_symbol = self._load_market_bundle()
        grouped = _group_candles_by_month(candles_by_symbol)
        available_months = _available_months(grouped)
        tuned_research, research_window = adapt_strategy_tuning_research(
            self.config.research,
            available_months=len(available_months),
            fixed_subset_size=len(instruments),
        )
        if tuned_research is None:
            payload = {
                "target": {
                    "monthly_profit_rub": round(
                        effective_target_monthly_profit_rub(self.config.research, self.config.backtest),
                        2,
                    ),
                    "monthly_return_pct": round(
                        effective_target_monthly_return_pct(self.config.research, self.config.backtest),
                        3,
                    ),
                },
                "research_window": research_window,
                "changed": False,
                "reason": research_window["reason"],
            }
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            output_dir = self.config.resolve_path(self.config.reporting.output_dir) / "autotune" / "strategy" / stamp
            write_json_payload(output_dir / "strategy_tuning.json", payload)
            payload["output_dir"] = str(output_dir)
            return payload

        validator = WalkForwardValidator(
            base_strategy=self.config.strategy,
            risk=self.config.risk,
            backtest=self.config.backtest,
            research=tuned_research,
            timeframe=self.config.data.timeframe,
            slippage_bps=self.config.execution.slippage_bps,
            commission_bps=self.config.execution.commission_bps,
        )
        walk_forward = validator.run(candles_by_symbol, instruments_by_symbol)
        latest_fold = walk_forward["folds"][-1]

        optimizer = ParameterOptimizer(
            base_strategy=self.config.strategy,
            risk=self.config.risk,
            backtest=self.config.backtest,
            research=tuned_research,
            timeframe=self.config.data.timeframe,
            slippage_bps=self.config.execution.slippage_bps,
            commission_bps=self.config.execution.commission_bps,
        )
        candidate_strategy = optimizer.strategy_from_candidate_payload(latest_fold["best_candidate"])
        baseline_summary = self._evaluate_strategy_test_window(
            strategy_config=self.config.strategy,
            grouped=grouped,
            instruments_by_symbol=instruments_by_symbol,
            symbols=latest_fold["best_candidate"]["symbols"],
            train_months=latest_fold["train_months"],
            test_months=latest_fold["test_months"],
        )
        payload = build_strategy_tuning_payload(
            current_strategy=self.config.strategy,
            candidate_strategy=candidate_strategy,
            baseline_latest_test_summary=baseline_summary,
            candidate_latest_test_summary=latest_fold["test_summary"],
            walk_forward_summary=walk_forward["summary"],
            walk_forward_config=walk_forward["config"],
            backtest=self.config.backtest,
            research=tuned_research,
            research_window=research_window,
            min_monthly_improvement_pct=min_monthly_improvement_pct,
            max_extra_drawdown_pct=max_extra_drawdown_pct,
            min_positive_fold_probability_pct=min_positive_fold_probability_pct,
        )
        payload["latest_fold"] = latest_fold
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        output_dir = self.config.resolve_path(self.config.reporting.output_dir) / "autotune" / "strategy" / stamp
        write_strategy_tuning(output_dir, payload)
        payload["output_dir"] = str(output_dir)
        return payload

    def tune_exits(
        self,
        *,
        min_monthly_improvement_pct: float = 0.03,
        max_extra_drawdown_pct: float = 1.0,
        min_positive_fold_probability_pct: float = 55.0,
    ) -> dict[str, object]:
        assert_paper_only_mode(
            self.config.execution.mode,
            allow_live_trading=self.config.execution.allow_live_trading,
            live_flag=False,
        )
        _, instruments, candles_by_symbol, instruments_by_symbol = self._load_market_bundle()
        grouped = _group_candles_by_month(candles_by_symbol)
        available_months = _available_months(grouped)
        tuned_research, research_window = adapt_strategy_tuning_research(
            self.config.research,
            available_months=len(available_months),
            fixed_subset_size=len(instruments),
        )
        if tuned_research is None:
            payload = {
                "target": {
                    "monthly_profit_rub": round(
                        effective_target_monthly_profit_rub(self.config.research, self.config.backtest),
                        2,
                    ),
                    "monthly_return_pct": round(
                        effective_target_monthly_return_pct(self.config.research, self.config.backtest),
                        3,
                    ),
                },
                "research_window": research_window,
                "changed": False,
                "reason": research_window["reason"],
            }
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            output_dir = self.config.resolve_path(self.config.reporting.output_dir) / "autotune" / "exits" / stamp
            write_json_payload(output_dir / "exit_tuning.json", payload)
            payload["output_dir"] = str(output_dir)
            return payload

        exit_research = specialize_exit_tuning_research(tuned_research, self.config.strategy)
        validator = WalkForwardValidator(
            base_strategy=self.config.strategy,
            risk=self.config.risk,
            backtest=self.config.backtest,
            research=exit_research,
            timeframe=self.config.data.timeframe,
            slippage_bps=self.config.execution.slippage_bps,
            commission_bps=self.config.execution.commission_bps,
        )
        walk_forward = validator.run(candles_by_symbol, instruments_by_symbol)
        latest_fold = walk_forward["folds"][-1]

        optimizer = ParameterOptimizer(
            base_strategy=self.config.strategy,
            risk=self.config.risk,
            backtest=self.config.backtest,
            research=exit_research,
            timeframe=self.config.data.timeframe,
            slippage_bps=self.config.execution.slippage_bps,
            commission_bps=self.config.execution.commission_bps,
        )
        candidate_strategy = optimizer.strategy_from_candidate_payload(latest_fold["best_candidate"])
        baseline_result, baseline_summary = self._evaluate_strategy_test_window_bundle(
            strategy_config=self.config.strategy,
            grouped=grouped,
            instruments_by_symbol=instruments_by_symbol,
            symbols=latest_fold["best_candidate"]["symbols"],
            train_months=latest_fold["train_months"],
            test_months=latest_fold["test_months"],
        )
        candidate_result, candidate_summary = self._evaluate_strategy_test_window_bundle(
            strategy_config=candidate_strategy,
            grouped=grouped,
            instruments_by_symbol=instruments_by_symbol,
            symbols=latest_fold["best_candidate"]["symbols"],
            train_months=latest_fold["train_months"],
            test_months=latest_fold["test_months"],
        )
        payload = build_exit_tuning_payload(
            current_strategy=self.config.strategy,
            candidate_strategy=candidate_strategy,
            baseline_latest_test_summary=baseline_summary,
            candidate_latest_test_summary=candidate_summary,
            baseline_exit_breakdown=build_exit_reason_breakdown(baseline_result.trades),
            candidate_exit_breakdown=build_exit_reason_breakdown(candidate_result.trades),
            walk_forward_summary=walk_forward["summary"],
            walk_forward_config=walk_forward["config"],
            backtest=self.config.backtest,
            research=exit_research,
            research_window=research_window,
            min_monthly_improvement_pct=min_monthly_improvement_pct,
            max_extra_drawdown_pct=max_extra_drawdown_pct,
            min_positive_fold_probability_pct=min_positive_fold_probability_pct,
        )
        payload["latest_fold"] = latest_fold
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        output_dir = self.config.resolve_path(self.config.reporting.output_dir) / "autotune" / "exits" / stamp
        write_exit_tuning(output_dir, payload)
        payload["output_dir"] = str(output_dir)
        return payload

    def run_paper_report(
        self,
        *,
        days: int = 1,
        report_date: str | None = None,
        timezone_name: str | None = None,
    ) -> dict[str, object]:
        broker = self._load_paper_broker()
        parsed_date = date.fromisoformat(report_date) if report_date else None
        payload = build_paper_report_payload(
            broker.portfolio,
            broker.trades,
            timezone_name=timezone_name or self.config.app.timezone,
            report_date=parsed_date,
            days=days,
        )
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        output_dir = self.config.resolve_path(self.config.reporting.output_dir) / "paper-reports" / stamp
        write_paper_report(output_dir, payload)
        payload["output_dir"] = str(output_dir)
        return payload

    def tune_entry_schedule(
        self,
        *,
        lookback_days: int = 45,
        report_date: str | None = None,
        timezone_name: str | None = None,
        min_trades_per_hour: int = 3,
        max_hours_to_add: int = 2,
        max_hours_to_remove: int = 2,
    ) -> dict[str, object]:
        broker = self._load_paper_broker()
        parsed_date = date.fromisoformat(report_date) if report_date else None
        payload = build_entry_schedule_tuning_payload(
            broker.portfolio,
            broker.trades,
            timezone_name=timezone_name or self.config.app.timezone,
            current_hours=self.config.strategy.allowed_entry_hours,
            report_date=parsed_date,
            lookback_days=lookback_days,
            min_trades_per_hour=min_trades_per_hour,
            max_hours_to_add=max_hours_to_add,
            max_hours_to_remove=max_hours_to_remove,
        )
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        output_dir = self.config.resolve_path(self.config.reporting.output_dir) / "autotune" / "entry-schedule" / stamp
        write_entry_schedule_tuning(output_dir, payload)
        payload["output_dir"] = str(output_dir)
        return payload

    def tune_entry_quality(
        self,
        *,
        lookback_trades: int = 40,
        min_trades: int = 8,
        min_trade_retention_ratio: float = 0.5,
        min_expectancy_improvement_rub: float = 50.0,
        bucket_step: float = 0.05,
    ) -> dict[str, object]:
        broker = self._load_paper_broker()
        payload = build_entry_quality_tuning_payload(
            trades=broker.trades,
            current_min_signal_strength=self.config.strategy.min_signal_strength,
            backtest=self.config.backtest,
            research=self.config.research,
            lookback_trades=lookback_trades,
            min_trades=min_trades,
            min_trade_retention_ratio=min_trade_retention_ratio,
            min_expectancy_improvement_rub=min_expectancy_improvement_rub,
            bucket_step=bucket_step,
        )
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        output_dir = self.config.resolve_path(self.config.reporting.output_dir) / "autotune" / "entry-quality" / stamp
        write_entry_quality_tuning(output_dir, payload)
        payload["output_dir"] = str(output_dir)
        return payload

    def run_paper_cycle(self) -> dict[str, object]:
        assert_paper_only_mode(
            self.config.execution.mode,
            allow_live_trading=self.config.execution.allow_live_trading,
            live_flag=False,
        )
        provider = self._data_provider()
        instruments = provider.resolve_universe(self.config.data.instruments)
        history = provider.load_history(instruments)
        marks = {symbol: candles[-1].close for symbol, candles in history.items() if candles}

        state_path = self.config.resolve_path(self.config.execution.state_path)
        broker = self._load_paper_broker()

        timestamp = datetime.now(timezone.utc)
        strategy = self._strategy()
        for instrument in instruments:
            strategy.prepare_history(instrument, history.get(instrument.symbol, []))
        risk_manager = self._risk_manager()
        cycle_events: list[dict[str, object]] = []

        broker.mark_to_market(marks, timestamp)
        risk_manager.update_drawdown_state(broker.portfolio, marks)

        for instrument in instruments:
            candles = history.get(instrument.symbol, [])
            if not candles:
                continue
            latest = candles[-1]
            position = broker.portfolio.positions.get(instrument.symbol)
            if position is not None:
                if position.direction.value == "long":
                    if latest.low <= position.stop_price:
                        broker.close_position(
                            instrument.symbol,
                            price=position.stop_price,
                            timestamp=latest.timestamp,
                            reason=ExitReason.STOP_LOSS,
                        )
                        position = None
                    elif latest.high >= position.take_profit:
                        broker.close_position(
                            instrument.symbol,
                            price=position.take_profit,
                            timestamp=latest.timestamp,
                            reason=ExitReason.TAKE_PROFIT,
                        )
                        position = None
                else:
                    if latest.high >= position.stop_price:
                        broker.close_position(
                            instrument.symbol,
                            price=position.stop_price,
                            timestamp=latest.timestamp,
                            reason=ExitReason.STOP_LOSS,
                        )
                        position = None
                    elif latest.low <= position.take_profit:
                        broker.close_position(
                            instrument.symbol,
                            price=position.take_profit,
                            timestamp=latest.timestamp,
                            reason=ExitReason.TAKE_PROFIT,
                        )
                        position = None

            signal = strategy.generate_signal(instrument, candles)
            if signal is None:
                continue

            if position and position.direction != signal.direction:
                broker.close_position(
                    instrument.symbol,
                    price=latest.close,
                    timestamp=latest.timestamp,
                    reason=ExitReason.SIGNAL_FLIP,
                )
                position = None

            if position is None:
                if not strategy.allows_entry_at(latest.timestamp):
                    cycle_events.append(
                        {
                            "timestamp": latest.timestamp.isoformat(),
                            "symbol": instrument.symbol,
                            "action": "signal",
                            "approved": False,
                            "reason": "entry blocked by schedule",
                            "direction": signal.direction.value,
                            "strength": signal.strength,
                            "quantity_lots": 0,
                        }
                    )
                    continue
                decision = risk_manager.approve(broker.portfolio, signal, marks, broker.trades)
                cycle_events.append(
                    {
                        "timestamp": latest.timestamp.isoformat(),
                        "symbol": instrument.symbol,
                        "action": "signal",
                        "approved": decision.approved,
                        "reason": decision.reason,
                        "direction": signal.direction.value,
                        "strength": signal.strength,
                        "quantity_lots": decision.quantity_lots,
                    }
                )
                if decision.approved:
                    broker.open_position(signal, decision.quantity_lots, latest.timestamp)

        broker.mark_to_market(marks, timestamp)
        broker.events.extend(cycle_events)
        broker.save(state_path)

        summary = {
            "timestamp": timestamp.isoformat(),
            "equity_rub": round(broker.portfolio.equity(marks), 2),
            "cash_rub": round(broker.portfolio.cash, 2),
            "gross_exposure_rub": round(broker.portfolio.gross_exposure(marks), 2),
            "open_positions": len(broker.portfolio.positions),
            "trading_halted": broker.portfolio.trading_halted,
        }
        stamp = timestamp.strftime("%Y%m%d-%H%M%S")
        output_dir = self.config.resolve_path(self.config.reporting.output_dir) / "paper" / stamp
        write_json_payload(output_dir / "cycle_summary.json", summary)
        write_json_payload(output_dir / "cycle_events.json", {"events": cycle_events})
        write_portfolio_snapshot(output_dir / "portfolio.json", broker.portfolio)
        return {"summary": summary, "output_dir": str(output_dir)}

    def _evaluate_strategy_test_window(
        self,
        *,
        strategy_config: StrategySection,
        grouped: dict[str, dict[str, list]],
        instruments_by_symbol: dict[str, object],
        symbols: list[str],
        train_months: list[str],
        test_months: list[str],
    ) -> dict[str, float | int]:
        _, summary = self._evaluate_strategy_test_window_bundle(
            strategy_config=strategy_config,
            grouped=grouped,
            instruments_by_symbol=instruments_by_symbol,
            symbols=symbols,
            train_months=train_months,
            test_months=test_months,
        )
        return summary

    def _evaluate_strategy_test_window_bundle(
        self,
        *,
        strategy_config: StrategySection,
        grouped: dict[str, dict[str, list]],
        instruments_by_symbol: dict[str, object],
        symbols: list[str],
        train_months: list[str],
        test_months: list[str],
    ) -> tuple[object, dict[str, float | int]]:
        selected_symbols = [symbol for symbol in symbols if symbol in instruments_by_symbol]
        combined_months = tuple([*train_months, *test_months])
        combined_bundle = _slice_grouped_candles(grouped, combined_months)
        test_bundle = _slice_grouped_candles(grouped, tuple(test_months))
        selected_candles = {symbol: combined_bundle[symbol] for symbol in selected_symbols}
        selected_instruments = {
            symbol: instruments_by_symbol[symbol] for symbol in selected_symbols
        }
        test_start_at = min(
            candle.timestamp
            for symbol in selected_symbols
            for candle in test_bundle.get(symbol, [])
        )
        engine = BacktestEngine(
            strategy=TrendFollowingStrategy(strategy_config, timeframe=self.config.data.timeframe),
            risk_manager=self._risk_manager(),
            backtest=self.config.backtest,
            slippage_bps=self.config.execution.slippage_bps,
            commission_bps=self.config.execution.commission_bps,
        )
        combined_result = engine.run_with_instruments(
            selected_candles,
            selected_instruments,
            trade_start_at=test_start_at,
        )
        test_result = _trim_backtest_result(combined_result, test_start_at)
        summary = compute_summary(test_result, timeframe=self.config.data.timeframe)
        summary["normalized_monthly_return_pct"] = round(
            _normalized_monthly_return_pct(
                float(summary["total_return_pct"]),
                len(test_months),
            ),
            3,
        )
        return test_result, summary
