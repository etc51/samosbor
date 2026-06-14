from __future__ import annotations

import csv
import json
from pathlib import Path


def write_optimizer_report(output_dir: Path, payload: dict[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "optimizer.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    rows = payload.get("top_candidates", [])
    with (output_dir / "optimizer_top_candidates.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "score",
                "symbols",
                "fast_window",
                "slow_window",
                "atr_stop_multiple",
                "reward_to_risk",
                "min_trend_strength",
                "total_return_pct",
                "max_drawdown_pct",
                "sharpe_ratio",
                "avg_monthly_return_pct",
                "profit_factor",
                "trades",
            ]
        )
        for row in rows:
            summary = row["summary"]
            writer.writerow(
                [
                    row["score"],
                    ",".join(row["symbols"]),
                    row["fast_window"],
                    row["slow_window"],
                    row["atr_stop_multiple"],
                    row["reward_to_risk"],
                    row["min_trend_strength"],
                    summary["total_return_pct"],
                    summary["max_drawdown_pct"],
                    summary["sharpe_ratio"],
                    summary["avg_monthly_return_pct"],
                    summary["profit_factor"],
                    summary["trades"],
                ]
            )


def write_monte_carlo_report(output_dir: Path, payload: dict[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "monte_carlo.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
