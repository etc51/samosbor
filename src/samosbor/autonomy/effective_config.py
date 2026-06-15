from __future__ import annotations

import json
import re
from pathlib import Path

from ..config import AppConfig

_SECTION_PATTERN = re.compile(r"^\s*\[.+\]\s*$")
_KEY_PATTERN = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")
_STRATEGY_OVERRIDE_ORDER = [
    "style",
    "fast_window",
    "slow_window",
    "require_breakout",
    "atr_stop_multiple",
    "reward_to_risk",
    "min_signal_strength",
    "min_trend_strength",
    "adx_min",
    "allowed_entry_hours",
]
_REQUIRED_CONFIRMATIONS = 2


def default_effective_config_path(config_path: str | Path) -> Path:
    path = Path(config_path).resolve()
    if path.name.endswith(".effective.toml"):
        return path
    suffix = path.suffix or ".toml"
    return path.with_name(f"{path.stem}.effective{suffix}")


def base_strategy_values(config: AppConfig) -> dict[str, object]:
    return {
        "style": config.strategy.style,
        "fast_window": config.strategy.fast_window,
        "slow_window": config.strategy.slow_window,
        "require_breakout": config.strategy.require_breakout,
        "atr_stop_multiple": config.strategy.atr_stop_multiple,
        "reward_to_risk": config.strategy.reward_to_risk,
        "min_signal_strength": config.strategy.min_signal_strength,
        "min_trend_strength": config.strategy.min_trend_strength,
        "adx_min": config.strategy.adx_min,
        "allowed_entry_hours": list(config.strategy.allowed_entry_hours),
    }


def build_effective_strategy_overrides(
    config: AppConfig,
    *,
    source_summaries: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    summaries = source_summaries
    if summaries is None:
        autotune_dir = config.resolve_path(config.reporting.output_dir) / "autotune"
        summaries = summarize_effective_config_sources(autotune_dir)
    overrides: dict[str, object] = {}
    for item in summaries:
        overrides.update(item["selected_values"])
    return overrides


def summarize_effective_config_sources(
    autotune_dir: Path,
    *,
    required_confirmations: int = _REQUIRED_CONFIRMATIONS,
) -> list[dict[str, object]]:
    return [
        _build_source_summary(
            autotune_dir=autotune_dir,
            source_name="strategy",
            json_name="strategy_tuning.json",
            current_value_builder=_strategy_current_values,
            candidate_value_builder=_strategy_candidate_values,
            required_confirmations=required_confirmations,
        ),
        _build_source_summary(
            autotune_dir=autotune_dir,
            source_name="exits",
            json_name="exit_tuning.json",
            current_value_builder=_exit_current_values,
            candidate_value_builder=_exit_candidate_values,
            required_confirmations=required_confirmations,
        ),
        _build_source_summary(
            autotune_dir=autotune_dir,
            source_name="entry-schedule",
            json_name="schedule_tuning.json",
            current_value_builder=_entry_schedule_current_values,
            candidate_value_builder=_entry_schedule_candidate_values,
            required_confirmations=required_confirmations,
        ),
        _build_source_summary(
            autotune_dir=autotune_dir,
            source_name="entry-quality",
            json_name="entry_quality_tuning.json",
            current_value_builder=_entry_quality_current_values,
            candidate_value_builder=_entry_quality_candidate_values,
            required_confirmations=required_confirmations,
        ),
    ]


def build_effective_config_guardrail_payload(
    *,
    base_values: dict[str, object],
    source_summaries: list[dict[str, object]],
    paper_report: dict[str, object],
    guardrail_days: int = 3,
    min_recent_trades: int = 6,
) -> dict[str, object]:
    active_sources: list[str] = []
    active_override_keys: list[str] = []
    for source in source_summaries:
        changed_keys = [
            key
            for key, value in source.get("selected_values", {}).items()
            if base_values.get(key) != value
        ]
        if changed_keys:
            active_sources.append(str(source.get("source", "")))
            active_override_keys.extend(changed_keys)

    summary = dict(paper_report.get("summary", {}))
    comparison = dict(paper_report.get("comparison_to_previous_window", {}))
    previous_summary = dict(comparison.get("summary", {}))
    delta = dict(comparison.get("delta", {}))
    portfolio = dict(paper_report.get("portfolio", {}))

    trades = int(summary.get("trades", 0))
    net_pnl = float(summary.get("net_pnl_rub", 0.0))
    expectancy = float(summary.get("expectancy_rub", 0.0))
    profit_factor = float(summary.get("profit_factor", 0.0))
    previous_trades = int(previous_summary.get("trades", 0))
    delta_net_pnl = float(delta.get("net_pnl_rub", 0.0))
    trading_halted = bool(portfolio.get("trading_halted", False))

    enough_trades = trades >= min_recent_trades
    recent_window_negative = net_pnl < 0 and expectancy < 0 and profit_factor < 1.0
    deterioration_confirmed = delta_net_pnl < 0 or previous_trades == 0
    rollback_to_base = bool(active_sources) and (
        trading_halted or (enough_trades and recent_window_negative and deterioration_confirmed)
    )

    if rollback_to_base and trading_halted:
        reason = "portfolio drawdown halt is active while autotune overrides are applied"
    elif rollback_to_base:
        reason = "recent paper window deteriorated while autotune overrides were active"
    elif not active_sources:
        reason = "no active overrides versus the base runtime config"
    elif not enough_trades:
        reason = f"need at least {min_recent_trades} recent trades before rollback guardrail can judge overrides"
    elif not recent_window_negative:
        reason = "recent paper window does not show a broad enough deterioration"
    else:
        reason = "recent paper window is weak but not worse than the previous comparison window"

    return {
        "rollback_to_base": rollback_to_base,
        "reason": reason,
        "guardrails": {
            "days": guardrail_days,
            "min_recent_trades": min_recent_trades,
            "require_negative_net_pnl": True,
            "require_negative_expectancy": True,
            "require_profit_factor_below_one": True,
            "require_worse_than_previous_window": True,
            "always_rollback_if_trading_halted": True,
        },
        "active_sources": active_sources,
        "active_override_keys": sorted(set(active_override_keys)),
        "recent_summary": summary,
        "previous_summary": previous_summary,
        "comparison_delta": delta,
        "trading_halted": trading_halted,
    }


def write_effective_config(
    source_config_path: str | Path,
    output_path: str | Path,
    *,
    strategy_overrides: dict[str, object],
) -> None:
    source_path = Path(source_config_path).resolve()
    target_path = Path(output_path).resolve()
    rendered = _apply_strategy_overrides(
        source_path.read_text(encoding="utf-8"),
        strategy_overrides,
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(rendered, encoding="utf-8")


def _build_source_summary(
    *,
    autotune_dir: Path,
    source_name: str,
    json_name: str,
    current_value_builder,
    candidate_value_builder,
    required_confirmations: int,
) -> dict[str, object]:
    payload_paths = _payload_history_paths(autotune_dir / source_name, json_name)
    payload_path = payload_paths[-1] if payload_paths else None
    if payload_path is None:
        return {
            "source": source_name,
            "artifact_path": "",
            "changed": False,
            "current_values": {},
            "candidate_values": {},
            "selected_values": {},
            "reason": "no tuning artifacts found",
            "activation": {
                "required_confirmations": required_confirmations,
                "confirmation_count": 0,
                "confirmed": False,
                "pending_activation": False,
                "reason": "no tuning artifacts found",
            },
        }

    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    changed = bool(payload.get("changed", False))
    current_values = current_value_builder(payload)
    candidate_values = candidate_value_builder(payload)
    activation = {
        "required_confirmations": required_confirmations,
        "confirmation_count": 0,
        "confirmed": False,
        "pending_activation": False,
        "reason": "latest tuning run keeps current runtime values",
    }
    selected_values = current_values

    if changed and candidate_values:
        confirmation_count = _candidate_confirmation_count(
            payload_paths,
            candidate_value_builder=candidate_value_builder,
            target_values=candidate_values,
        )
        confirmed = confirmation_count >= max(1, required_confirmations)
        activation = {
            "required_confirmations": required_confirmations,
            "confirmation_count": confirmation_count,
            "confirmed": confirmed,
            "pending_activation": not confirmed,
            "reason": (
                f"candidate confirmed across {confirmation_count} consecutive tuning runs"
                if confirmed
                else f"candidate is waiting for {required_confirmations} consecutive confirmations"
            ),
        }
        selected_values = candidate_values if confirmed else current_values

    return {
        "source": source_name,
        "artifact_path": str(payload_path),
        "changed": changed,
        "current_values": current_values,
        "candidate_values": candidate_values,
        "selected_values": selected_values,
        "reason": str(payload.get("reason", "latest tuning payload loaded")),
        "activation": activation,
    }


def _payload_history_paths(source_dir: Path, json_name: str) -> list[Path]:
    if not source_dir.exists():
        return []
    return sorted(
        [
            path / json_name
            for path in source_dir.iterdir()
            if path.is_dir() and (path / json_name).exists()
        ],
        key=lambda path: path.parent.name,
    )


def _candidate_confirmation_count(
    payload_paths: list[Path],
    *,
    candidate_value_builder,
    target_values: dict[str, object],
) -> int:
    count = 0
    for payload_path in reversed(payload_paths):
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        if not payload.get("changed", False):
            break
        if candidate_value_builder(payload) != target_values:
            break
        count += 1
    return count


def _strategy_current_values(payload: dict[str, object]) -> dict[str, object]:
    source = payload.get("current_strategy", {})
    return {
        key: source[key]
        for key in ("style", "fast_window", "slow_window", "require_breakout", "min_trend_strength", "adx_min")
        if key in source
    }


def _strategy_candidate_values(payload: dict[str, object]) -> dict[str, object]:
    source = payload.get("candidate_strategy", {})
    return {
        key: source[key]
        for key in ("style", "fast_window", "slow_window", "require_breakout", "min_trend_strength", "adx_min")
        if key in source
    }


def _exit_current_values(payload: dict[str, object]) -> dict[str, object]:
    source = payload.get("current_exit_settings", {})
    return {
        key: source[key]
        for key in ("atr_stop_multiple", "reward_to_risk")
        if key in source
    }


def _exit_candidate_values(payload: dict[str, object]) -> dict[str, object]:
    source = payload.get("candidate_exit_settings", {})
    return {
        key: source[key]
        for key in ("atr_stop_multiple", "reward_to_risk")
        if key in source
    }


def _entry_schedule_current_values(payload: dict[str, object]) -> dict[str, object]:
    return {"allowed_entry_hours": [int(value) for value in payload.get("current_hours", [])]}


def _entry_schedule_candidate_values(payload: dict[str, object]) -> dict[str, object]:
    return {"allowed_entry_hours": [int(value) for value in payload.get("proposed_hours", [])]}


def _entry_quality_current_values(payload: dict[str, object]) -> dict[str, object]:
    return {"min_signal_strength": float(payload.get("current_min_signal_strength", 0.0))}


def _entry_quality_candidate_values(payload: dict[str, object]) -> dict[str, object]:
    return {"min_signal_strength": float(payload.get("recommended_min_signal_strength", 0.0))}


def _strategy_values(payload: dict[str, object]) -> dict[str, object]:
    source = payload.get("candidate_strategy", {}) if payload.get("changed") else payload.get("current_strategy", {})
    return {
        key: source[key]
        for key in ("style", "fast_window", "slow_window", "require_breakout", "min_trend_strength", "adx_min")
        if key in source
    }


def _exit_values(payload: dict[str, object]) -> dict[str, object]:
    source = payload.get("candidate_exit_settings", {}) if payload.get("changed") else payload.get("current_exit_settings", {})
    return {
        key: source[key]
        for key in ("atr_stop_multiple", "reward_to_risk")
        if key in source
    }


def _entry_schedule_values(payload: dict[str, object]) -> dict[str, object]:
    key = "proposed_hours" if payload.get("changed") else "current_hours"
    return {"allowed_entry_hours": [int(value) for value in payload.get(key, [])]}


def _entry_quality_values(payload: dict[str, object]) -> dict[str, object]:
    key = "recommended_min_signal_strength" if payload.get("changed") else "current_min_signal_strength"
    return {"min_signal_strength": float(payload.get(key, 0.0))}


def _apply_strategy_overrides(base_text: str, overrides: dict[str, object]) -> str:
    if not overrides:
        return base_text

    lines = base_text.splitlines()
    strategy_start = None
    strategy_end = len(lines)
    for index, line in enumerate(lines):
        if line.strip() == "[strategy]":
            strategy_start = index
            continue
        if strategy_start is not None and index > strategy_start and _SECTION_PATTERN.match(line.strip()):
            strategy_end = index
            break

    if strategy_start is None:
        raise ValueError("strategy section not found in config")

    line_indexes: dict[str, int] = {}
    for index in range(strategy_start + 1, strategy_end):
        match = _KEY_PATTERN.match(lines[index])
        if match:
            line_indexes[match.group(1)] = index

    for key in _STRATEGY_OVERRIDE_ORDER:
        if key not in overrides:
            continue
        rendered_line = f"{key} = {_render_toml_value(overrides[key])}"
        if key in line_indexes:
            lines[line_indexes[key]] = rendered_line
            continue
        lines.insert(strategy_end, rendered_line)
        line_indexes[key] = strategy_end
        strategy_end += 1

    return "\n".join(lines) + "\n"


def _render_toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, list):
        return "[" + ", ".join(_render_toml_value(item) for item in value) + "]"
    return str(value)
