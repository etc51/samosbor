from __future__ import annotations

from ..config import BacktestSection, ResearchSection


def effective_target_monthly_profit_rub(
    research: ResearchSection,
    backtest: BacktestSection,
) -> float:
    if research.target_monthly_profit_rub > 0:
        return float(research.target_monthly_profit_rub)
    return float(backtest.initial_cash) * float(research.target_monthly_return_pct) / 100.0


def effective_target_monthly_return_pct(
    research: ResearchSection,
    backtest: BacktestSection,
) -> float:
    if research.target_monthly_profit_rub > 0 and backtest.initial_cash > 0:
        return float(research.target_monthly_profit_rub) / float(backtest.initial_cash) * 100.0
    return float(research.target_monthly_return_pct)
