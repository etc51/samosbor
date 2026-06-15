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


def default_effective_config_path(config_path: str | Path) -> Path:
    path = Path(config_path).resolve()
    if path.name.endswith(".effective.toml"):
        return path
    suffix = path.suffix or ".toml"
    return path.with_name(f"{path.stem}.effective{suffix}")


def build_effective_strategy_overrides(config: AppConfig) -> dict[str, object]:
    autotune_dir = config.resolve_path(config.reporting.output_dir) / "autotune"
    overrides: dict[str, object] = {}
    for item in summarize_effective_config_sources(autotune_dir):
        overrides.update(item["selected_values"])
    return overrides


def summarize_effective_config_sources(autotune_dir: Path) -> list[dict[str, object]]:
    return [
        _build_source_summary(
            autotune_dir=autotune_dir,
            source_name="strategy",
            json_name="strategy_tuning.json",
            value_builder=_strategy_values,
        ),
        _build_source_summary(
            autotune_dir=autotune_dir,
            source_name="exits",
            json_name="exit_tuning.json",
            value_builder=_exit_values,
        ),
        _build_source_summary(
            autotune_dir=autotune_dir,
            source_name="entry-schedule",
            json_name="schedule_tuning.json",
            value_builder=_entry_schedule_values,
        ),
        _build_source_summary(
            autotune_dir=autotune_dir,
            source_name="entry-quality",
            json_name="entry_quality_tuning.json",
            value_builder=_entry_quality_values,
        ),
    ]


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
    value_builder,
) -> dict[str, object]:
    payload_path = _latest_payload_path(autotune_dir / source_name, json_name)
    if payload_path is None:
        return {
            "source": source_name,
            "artifact_path": "",
            "changed": False,
            "selected_values": {},
            "reason": "no tuning artifacts found",
        }

    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    return {
        "source": source_name,
        "artifact_path": str(payload_path),
        "changed": bool(payload.get("changed", False)),
        "selected_values": value_builder(payload),
        "reason": str(payload.get("reason", "latest tuning payload loaded")),
    }


def _latest_payload_path(source_dir: Path, json_name: str) -> Path | None:
    if not source_dir.exists():
        return None
    candidates = [
        path / json_name
        for path in source_dir.iterdir()
        if path.is_dir() and (path / json_name).exists()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.parent.name)


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
