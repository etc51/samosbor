from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from .config import AppConfig
from .data.csv_provider import CSVMarketDataProvider
from .data.tbank import TBankMarketDataProvider
from .domain import ExitReason
from .execution.paper import LocalPaperBroker
from .execution.sandbox import TBankSandboxExecutor
from .reporting.metrics import compute_summary
from .reporting.writer import write_backtest_report, write_json_payload, write_portfolio_snapshot
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
        provider = self._data_provider()
        instruments = provider.resolve_universe(self.config.data.instruments)
        candles_by_symbol = provider.load_history(instruments)
        instruments_by_symbol = {instrument.symbol: instrument for instrument in instruments}

        engine = BacktestEngine(
            strategy=self._strategy(),
            risk_manager=self._risk_manager(),
            backtest=self.config.backtest,
            slippage_bps=self.config.execution.slippage_bps,
            commission_bps=self.config.execution.commission_bps,
        )
        result = engine.run_with_instruments(candles_by_symbol, instruments_by_symbol)
        summary = compute_summary(result, timeframe=self.config.data.timeframe)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        output_dir = self.config.resolve_path(self.config.reporting.output_dir) / "backtests" / stamp
        write_backtest_report(output_dir, result, summary)
        LOGGER.info("Backtest report written to %s", output_dir)
        return {"summary": summary, "output_dir": str(output_dir)}

    def run_paper_cycle(self) -> dict[str, object]:
        assert_paper_only_mode(
            self.config.execution.mode,
            allow_live_trading=self.config.execution.allow_live_trading,
            live_flag=False,
        )
        provider = TBankMarketDataProvider(self.config)
        instruments = provider.resolve_universe(self.config.data.instruments)
        history = provider.load_history(instruments)
        marks = {symbol: candles[-1].close for symbol, candles in history.items() if candles}

        state_path = self.config.resolve_path(self.config.execution.state_path)
        broker = LocalPaperBroker.load(
            state_path,
            initial_cash=self.config.backtest.initial_cash,
            slippage_bps=self.config.execution.slippage_bps,
            commission_bps=self.config.execution.commission_bps,
        )

        timestamp = datetime.now(timezone.utc)
        strategy = self._strategy()
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
