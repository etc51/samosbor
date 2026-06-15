from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

from ..config import BacktestSection, ResearchSection, StrategySection
from ..domain import TradeRecord
from ..research.targets import effective_target_monthly_profit_rub, effective_target_monthly_return_pct


def specialize_exit_tuning_research(
    research: ResearchSection,
    current_strategy: StrategySection,
) -> ResearchSection:
    return replace(
        research,
        strategy_styles=[current_strategy.style],
        fast_windows=[current_strategy.fast_window],
        slow_windows=[current_strategy.slow_window],
        require_breakout_values=[current_strategy.require_breakout],
        trend_strength_values=[current_strategy.min_trend_strength],
        adx_min_values=[current_strategy.adx_min],
    )


def build_exit_reason_breakdown(trades: list[TradeRecord]) -> list[dict[str, object]]:
    grouped: dict[str, list[TradeRecord]] = defaultdict(list)
    for trade in trades:
        grouped[trade.reason].append(trade)

    rows = []
    for reason, group in grouped.items():
        wins = [trade for trade in group if trade.net_pnl > 0]
        net_pnl = sum(trade.net_pnl for trade in group)
        rows.append(
            {
                "reason": reason,
                "trades": len(group),
                "win_rate_pct": round(len(wins) / len(group) * 100, 3) if group else 0.0,
                "net_pnl_rub": round(net_pnl, 2),
                "avg_net_pnl_rub": round(net_pnl / len(group), 2) if group else 0.0,
            }
        )
    rows.sort(key=lambda item: float(item["net_pnl_rub"]))
    return rows


def build_exit_tuning_payload(
    *,
    current_strategy: StrategySection,
    candidate_strategy: StrategySection,
    baseline_latest_test_summary: dict[str, float | int],
    candidate_latest_test_summary: dict[str, float | int],
    baseline_exit_breakdown: list[dict[str, object]],
    candidate_exit_breakdown: list[dict[str, object]],
    walk_forward_summary: dict[str, float | int],
    walk_forward_config: dict[str, object],
    backtest: BacktestSection,
    research: ResearchSection,
    research_window: dict[str, object],
    min_monthly_improvement_pct: float = 0.03,
    max_extra_drawdown_pct: float = 1.0,
    min_positive_fold_probability_pct: float = 55.0,
) -> dict[str, object]:
    effective_target_profit = effective_target_monthly_profit_rub(research, backtest)
    effective_target_return = effective_target_monthly_return_pct(research, backtest)
    current_view = _exit_view(current_strategy)
    candidate_view = _exit_view(candidate_strategy)
    patch_values = {
        key: value
        for key, value in candidate_view.items()
        if current_view.get(key) != value
    }

    monthly_delta = round(
        float(candidate_latest_test_summary["normalized_monthly_return_pct"])
        - float(baseline_latest_test_summary["normalized_monthly_return_pct"]),
        3,
    )
    total_return_delta = round(
        float(candidate_latest_test_summary["total_return_pct"])
        - float(baseline_latest_test_summary["total_return_pct"]),
        3,
    )
    drawdown_delta = round(
        float(candidate_latest_test_summary["max_drawdown_pct"])
        - float(baseline_latest_test_summary["max_drawdown_pct"]),
        3,
    )
    sharpe_delta = round(
        float(candidate_latest_test_summary["sharpe_ratio"])
        - float(baseline_latest_test_summary["sharpe_ratio"]),
        3,
    )
    stop_loss_delta = round(
        _reason_metric(candidate_exit_breakdown, "stop-loss", "net_pnl_rub")
        - _reason_metric(baseline_exit_breakdown, "stop-loss", "net_pnl_rub"),
        2,
    )
    take_profit_delta = round(
        _reason_metric(candidate_exit_breakdown, "take-profit", "net_pnl_rub")
        - _reason_metric(baseline_exit_breakdown, "take-profit", "net_pnl_rub"),
        2,
    )

    changed = bool(patch_values) and (
        monthly_delta >= min_monthly_improvement_pct
        and total_return_delta > 0
        and drawdown_delta <= max_extra_drawdown_pct
        and float(walk_forward_summary["average_test_normalized_monthly_return_pct"]) > 0
        and float(walk_forward_summary["probability_positive_pct"])
        >= min_positive_fold_probability_pct
    )

    if not patch_values:
        reason = "current exit settings already match the latest walk-forward winner"
    elif not changed:
        reason = "candidate exit settings failed one or more safety guardrails"
    else:
        reason = "candidate exit settings improved the latest OOS window without breaking guardrails"

    return {
        "target": {
            "monthly_profit_rub": round(effective_target_profit, 2),
            "monthly_return_pct": round(effective_target_return, 3),
        },
        "research_window": research_window,
        "walk_forward": {
            "config": walk_forward_config,
            "summary": walk_forward_summary,
        },
        "guardrails": {
            "min_monthly_improvement_pct": min_monthly_improvement_pct,
            "max_extra_drawdown_pct": max_extra_drawdown_pct,
            "min_positive_fold_probability_pct": min_positive_fold_probability_pct,
        },
        "current_exit_settings": current_view,
        "candidate_exit_settings": candidate_view,
        "patch_values": patch_values,
        "baseline_latest_test_summary": baseline_latest_test_summary,
        "candidate_latest_test_summary": candidate_latest_test_summary,
        "baseline_exit_breakdown": baseline_exit_breakdown,
        "candidate_exit_breakdown": candidate_exit_breakdown,
        "comparison": {
            "monthly_return_delta_pct": monthly_delta,
            "total_return_delta_pct": total_return_delta,
            "max_drawdown_delta_pct": drawdown_delta,
            "sharpe_delta": sharpe_delta,
            "stop_loss_net_pnl_delta_rub": stop_loss_delta,
            "take_profit_net_pnl_delta_rub": take_profit_delta,
        },
        "changed": changed,
        "reason": reason,
    }


def write_exit_tuning(output_dir: Path, payload: dict[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "exit_tuning.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "exit_patch.toml").write_text(
        _render_exit_patch(payload),
        encoding="utf-8",
    )
    (output_dir / "summary.md").write_text(_render_markdown(payload), encoding="utf-8")


def _exit_view(strategy: StrategySection) -> dict[str, object]:
    return {
        "atr_stop_multiple": strategy.atr_stop_multiple,
        "reward_to_risk": strategy.reward_to_risk,
    }


def _reason_metric(rows: list[dict[str, object]], reason: str, key: str) -> float:
    for row in rows:
        if row["reason"] == reason:
            return float(row[key])
    return 0.0


def _render_exit_patch(payload: dict[str, object]) -> str:
    patch_values = payload.get("patch_values", {})
    if not patch_values:
        return "\n".join(
            [
                "# No exit parameter changes recommended by the latest tuning pass",
                "",
            ]
        )

    lines = [
        "# Candidate exit patch generated from walk-forward tuning",
        "[strategy]",
    ]
    for key, value in patch_values.items():
        lines.append(f"{key} = {value}")
    lines.append("")
    return "\n".join(lines)


def _render_markdown(payload: dict[str, object]) -> str:
    comparison = payload["comparison"]
    baseline = payload["baseline_latest_test_summary"]
    candidate = payload["candidate_latest_test_summary"]
    lines = [
        "# Exit Tuning",
        "",
        f"- Target: {payload['target']['monthly_profit_rub']} RUB/month ({payload['target']['monthly_return_pct']}%)",
        f"- Changed: {payload['changed']}",
        f"- Reason: {payload['reason']}",
        f"- Current exits: {payload['current_exit_settings']}",
        f"- Candidate exits: {payload['candidate_exit_settings']}",
        f"- Latest OOS monthly delta: {comparison['monthly_return_delta_pct']} pct",
        f"- Latest OOS total return delta: {comparison['total_return_delta_pct']} pct",
        f"- Latest OOS drawdown delta: {comparison['max_drawdown_delta_pct']} pct",
        f"- Stop-loss net delta: {comparison['stop_loss_net_pnl_delta_rub']} RUB",
        f"- Take-profit net delta: {comparison['take_profit_net_pnl_delta_rub']} RUB",
        "",
        "## Baseline OOS",
        f"- Return: {baseline['total_return_pct']}%",
        f"- Monthly: {baseline['normalized_monthly_return_pct']}%",
        f"- Drawdown: {baseline['max_drawdown_pct']}%",
        f"- Sharpe: {baseline['sharpe_ratio']}",
        "",
        "## Candidate OOS",
        f"- Return: {candidate['total_return_pct']}%",
        f"- Monthly: {candidate['normalized_monthly_return_pct']}%",
        f"- Drawdown: {candidate['max_drawdown_pct']}%",
        f"- Sharpe: {candidate['sharpe_ratio']}",
        "",
    ]
    return "\n".join(lines)
