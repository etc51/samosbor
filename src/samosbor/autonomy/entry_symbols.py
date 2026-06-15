from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from ..domain import PortfolioState, TradeRecord
from ..reporting.paper_report import build_paper_report_payload


def build_entry_symbol_tuning_payload(
    portfolio: PortfolioState,
    trades: list[TradeRecord],
    *,
    timezone_name: str,
    current_blocked_symbols: list[str],
    evidence_source: str = "closed-trades",
    report_date: date | None = None,
    lookback_days: int = 45,
    min_trades_per_symbol: int = 4,
    max_symbols_to_block: int = 1,
    max_total_blocked_symbols: int = 4,
) -> dict[str, object]:
    if lookback_days < 1:
        raise ValueError("lookback_days must be >= 1")
    if min_trades_per_symbol < 1:
        raise ValueError("min_trades_per_symbol must be >= 1")
    if max_symbols_to_block < 0:
        raise ValueError("max_symbols_to_block must be >= 0")
    if max_total_blocked_symbols < 0:
        raise ValueError("max_total_blocked_symbols must be >= 0")

    report = build_paper_report_payload(
        portfolio,
        trades,
        timezone_name=timezone_name,
        report_date=report_date,
        days=lookback_days,
    )
    rows = list(report["symbol_breakdown"])
    current_set = {
        str(symbol).strip().upper()
        for symbol in current_blocked_symbols
        if str(symbol).strip()
    }

    candidates = [
        row
        for row in rows
        if str(row["group"]).strip().upper() not in current_set
        and int(row["trades"]) >= min_trades_per_symbol
        and float(row["net_pnl_rub"]) < 0
        and float(row["expectancy_rub"]) < 0
        and float(row["profit_factor"]) < 1.0
    ]
    candidates.sort(
        key=lambda row: (
            float(row["net_pnl_rub"]),
            float(row["expectancy_rub"]),
            float(row["profit_factor"]),
        )
    )

    available_slots = max(0, max_total_blocked_symbols - len(current_set))
    additions = [
        str(row["group"]).strip().upper()
        for row in candidates[: min(max_symbols_to_block, available_slots)]
    ]
    proposed_blocked_symbols = sorted(current_set | set(additions))
    changed = proposed_blocked_symbols != sorted(current_set)

    if changed:
        reason = "blocked symbols updated from paper results"
    elif available_slots <= 0:
        reason = "blocked-symbol budget is already exhausted"
    else:
        reason = "insufficient evidence for symbol restriction change"

    return {
        "analysis_window": report["period"],
        "guardrails": {
            "min_trades_per_symbol": min_trades_per_symbol,
            "max_symbols_to_block": max_symbols_to_block,
            "max_total_blocked_symbols": max_total_blocked_symbols,
        },
        "evidence_source": evidence_source,
        "current_blocked_symbols": sorted(current_set),
        "proposed_blocked_symbols": proposed_blocked_symbols,
        "additions": additions,
        "changed": changed,
        "reason": reason,
        "symbol_breakdown": rows,
    }


def write_entry_symbol_tuning(output_dir: Path, payload: dict[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "symbol_restrictions.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "symbol_restrictions_patch.toml").write_text(
        _render_patch(payload),
        encoding="utf-8",
    )
    (output_dir / "summary.md").write_text(
        _render_markdown(payload),
        encoding="utf-8",
    )


def _render_patch(payload: dict[str, object]) -> str:
    symbols = ", ".join(f'"{symbol}"' for symbol in payload["proposed_blocked_symbols"])
    return "\n".join(
        [
            "# Candidate patch generated from paper-trading symbol results",
            "[strategy]",
            f"blocked_symbols = [{symbols}]",
            "",
        ]
    )


def _render_markdown(payload: dict[str, object]) -> str:
    rows = sorted(payload["symbol_breakdown"], key=lambda row: float(row["net_pnl_rub"]))
    worst_rows = rows[:3]
    best_rows = list(reversed(rows[-3:])) if rows else []
    lines = [
        "# Entry Symbol Tuning",
        "",
        f"- Lookback: {payload['analysis_window']['days']} day(s)",
        f"- Evidence source: {payload['evidence_source']}",
        f"- Current blocked symbols: {payload['current_blocked_symbols']}",
        f"- Proposed blocked symbols: {payload['proposed_blocked_symbols']}",
        f"- Additions: {payload['additions']}",
        f"- Changed: {payload['changed']}",
        f"- Reason: {payload['reason']}",
        "",
        "## Strong Symbols",
    ]
    if best_rows:
        for row in best_rows:
            lines.append(
                f"- {row['group']}: {row['net_pnl_rub']} RUB, {row['trades']} trades, expectancy {row['expectancy_rub']}"
            )
    else:
        lines.append("- No eligible paper trades in this window")

    lines.append("")
    lines.append("## Weak Symbols")
    if worst_rows:
        for row in worst_rows:
            lines.append(
                f"- {row['group']}: {row['net_pnl_rub']} RUB, {row['trades']} trades, expectancy {row['expectancy_rub']}"
            )
    else:
        lines.append("- No eligible paper trades in this window")
    lines.append("")
    return "\n".join(lines)
