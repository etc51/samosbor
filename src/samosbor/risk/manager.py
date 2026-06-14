from __future__ import annotations

from statistics import mean

from ..config import RiskSection
from ..domain import InstrumentType, PortfolioState, RiskDecision, Signal, SignalDirection, TradeRecord


class RiskManager:
    def __init__(self, config: RiskSection):
        self.config = config

    def update_drawdown_state(self, portfolio: PortfolioState, marks: dict[str, float]) -> float:
        equity = portfolio.equity(marks)
        if portfolio.peak_equity <= 0:
            portfolio.peak_equity = equity
        else:
            portfolio.peak_equity = max(portfolio.peak_equity, equity)
        if portfolio.peak_equity > 0:
            drawdown = 1 - (equity / portfolio.peak_equity)
            if drawdown >= self.config.max_drawdown:
                portfolio.trading_halted = True
        return equity

    def approve(
        self,
        portfolio: PortfolioState,
        signal: Signal,
        marks: dict[str, float],
        recent_trades: list[TradeRecord],
    ) -> RiskDecision:
        equity = self.update_drawdown_state(portfolio, marks)
        if portfolio.trading_halted:
            return RiskDecision(False, "trading halted by drawdown control")

        if signal.instrument.symbol in portfolio.positions:
            return RiskDecision(False, "position already open")

        if len(portfolio.positions) >= self.config.max_positions:
            return RiskDecision(False, "max positions reached")

        if equity <= 0:
            return RiskDecision(False, "equity depleted")

        stop_distance = abs(signal.entry_price - signal.stop_price)
        if stop_distance <= 0:
            return RiskDecision(False, "invalid stop distance")

        risk_fraction = self._dynamic_risk_fraction(recent_trades)
        risk_budget = equity * risk_fraction
        risk_per_lot = stop_distance * signal.instrument.lot_size
        quantity_lots = int(risk_budget // risk_per_lot)
        if quantity_lots < 1:
            return RiskDecision(False, "risk budget too small")

        if (
            signal.instrument.instrument_type == InstrumentType.FUTURE
            and (
                signal.instrument.initial_margin_buy > 0
                or signal.instrument.initial_margin_sell > 0
            )
        ):
            margin_per_lot = (
                signal.instrument.initial_margin_buy
                if signal.direction == SignalDirection.LONG
                else signal.instrument.initial_margin_sell
            )
            if margin_per_lot <= 0:
                return RiskDecision(False, "futures margin data unavailable")

            current_margin = portfolio.margin_reserved()
            max_margin_rub = equity * self.config.max_gross_exposure
            max_extra_margin = max(0.0, max_margin_rub - current_margin)
            margin_capped = int(max_extra_margin // margin_per_lot)
            quantity_lots = min(quantity_lots, margin_capped)
            if quantity_lots < 1:
                return RiskDecision(False, "futures margin cap reached")

            reserved_cash = equity * self.config.cash_reserve_ratio
            free_cash = max(0.0, portfolio.cash - current_margin - reserved_cash)
            cash_capped = int(free_cash // margin_per_lot)
            quantity_lots = min(quantity_lots, cash_capped)
            if quantity_lots < 1:
                return RiskDecision(False, "cash reserve rule blocked entry")

            estimated_notional = quantity_lots * signal.entry_price * signal.instrument.lot_size
            return RiskDecision(
                True,
                "approved",
                quantity_lots=quantity_lots,
                risk_budget_rub=risk_budget,
                estimated_notional_rub=estimated_notional,
            )

        current_exposure = portfolio.gross_exposure(marks)
        notional_per_lot = signal.entry_price * signal.instrument.lot_size
        max_exposure_rub = equity * self.config.max_gross_exposure
        max_extra_notional = max(0.0, max_exposure_rub - current_exposure)
        exposure_capped = int(max_extra_notional // notional_per_lot)
        quantity_lots = min(quantity_lots, exposure_capped)
        if quantity_lots < 1:
            return RiskDecision(False, "gross exposure cap reached")

        if signal.direction == SignalDirection.LONG:
            reserved_cash = equity * self.config.cash_reserve_ratio
            free_cash = max(0.0, portfolio.cash - reserved_cash)
            cash_capped = int(free_cash // notional_per_lot)
            quantity_lots = min(quantity_lots, cash_capped)
            if quantity_lots < 1:
                return RiskDecision(False, "cash reserve rule blocked entry")

        estimated_notional = quantity_lots * notional_per_lot
        return RiskDecision(
            True,
            "approved",
            quantity_lots=quantity_lots,
            risk_budget_rub=risk_budget,
            estimated_notional_rub=estimated_notional,
        )

    def _dynamic_risk_fraction(self, recent_trades: list[TradeRecord]) -> float:
        if len(recent_trades) < self.config.min_trades_for_kelly:
            return self.config.max_risk_per_trade

        sample = recent_trades[-self.config.kelly_lookback_trades :]
        wins = [trade.net_pnl for trade in sample if trade.net_pnl > 0]
        losses = [-trade.net_pnl for trade in sample if trade.net_pnl < 0]
        if not wins or not losses:
            return self.config.max_risk_per_trade * 0.5

        win_rate = len(wins) / len(sample)
        avg_win = mean(wins)
        avg_loss = mean(losses)
        if avg_loss <= 0:
            return self.config.max_risk_per_trade * 0.5

        edge_ratio = avg_win / avg_loss
        kelly = win_rate - ((1 - win_rate) / edge_ratio)
        scale = max(0.25, min(1.0, 0.5 + kelly / 2))
        return self.config.max_risk_per_trade * scale
