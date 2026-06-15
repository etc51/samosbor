from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..domain import Candle, Signal, SignalDirection, TradeRecord


def signal_feedback_path(state_path: Path) -> Path:
    suffix = state_path.suffix or ".json"
    return state_path.with_name(f"{state_path.stem}_signal_feedback{suffix}")


def load_signal_feedback(path: Path) -> dict[str, list[dict[str, object]]]:
    if not path.exists():
        return {"pending": [], "resolved": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "pending": list(payload.get("pending", [])),
        "resolved": list(payload.get("resolved", [])),
    }


def save_signal_feedback(path: Path, payload: dict[str, list[dict[str, object]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def record_shadow_signal(
    payload: dict[str, list[dict[str, object]]],
    signal: Signal,
    *,
    timestamp: datetime,
    horizon_bars: int,
) -> None:
    if any(item["symbol"] == signal.instrument.symbol for item in payload.get("pending", [])):
        return
    signature = (
        signal.instrument.symbol,
        signal.direction.value,
        timestamp.isoformat(),
    )
    for item in payload.get("pending", []) + payload.get("resolved", []):
        existing_signature = (
            item["symbol"],
            item["direction"],
            item["created_at"],
        )
        if existing_signature == signature:
            return

    payload.setdefault("pending", []).append(
        {
            "symbol": signal.instrument.symbol,
            "direction": signal.direction.value,
            "created_at": timestamp.isoformat(),
            "entry_price": signal.entry_price,
            "stop_price": signal.stop_price,
            "take_profit": signal.take_profit,
            "signal_strength": signal.strength,
            "horizon_bars": max(1, horizon_bars),
        }
    )


def resolve_pending_signals(
    payload: dict[str, list[dict[str, object]]],
    history_by_symbol: dict[str, list[Candle]],
) -> list[dict[str, object]]:
    resolved_items: list[dict[str, object]] = []
    remaining: list[dict[str, object]] = []

    for item in payload.get("pending", []):
        candles = history_by_symbol.get(item["symbol"], [])
        resolved = _resolve_signal_item(item, candles)
        if resolved is None:
            remaining.append(item)
            continue
        resolved_items.append(resolved)

    payload["pending"] = remaining
    payload.setdefault("resolved", []).extend(resolved_items)
    return resolved_items


def resolved_feedback_to_trades(payload: dict[str, list[dict[str, object]]]) -> list[TradeRecord]:
    trades: list[TradeRecord] = []
    for item in payload.get("resolved", []):
        trades.append(
            TradeRecord(
                symbol=str(item["symbol"]),
                direction=SignalDirection(str(item["direction"])),
                quantity_lots=1,
                entry_time=datetime.fromisoformat(str(item["created_at"])),
                exit_time=datetime.fromisoformat(str(item["resolved_at"])),
                entry_price=float(item["entry_price"]),
                exit_price=float(item["exit_price"]),
                gross_pnl=float(item["gross_pnl"]),
                net_pnl=float(item["gross_pnl"]),
                reason=str(item["outcome_reason"]),
                signal_strength=float(item.get("signal_strength", 0.0)),
            )
        )
    return trades


def default_signal_horizon_bars(timeframe: str) -> int:
    mapping = {
        "day": 5,
        "hour": 24,
        "30min": 32,
        "15min": 48,
        "10min": 60,
        "5min": 96,
        "1min": 180,
    }
    return mapping.get(timeframe.lower(), 24)


def _resolve_signal_item(item: dict[str, object], candles: list[Candle]) -> dict[str, object] | None:
    created_at = datetime.fromisoformat(str(item["created_at"]))
    future_candles = [candle for candle in candles if candle.timestamp > created_at]
    if not future_candles:
        return None

    direction = SignalDirection(str(item["direction"]))
    stop_price = float(item["stop_price"])
    take_profit = float(item["take_profit"])
    entry_price = float(item["entry_price"])
    horizon_bars = int(item.get("horizon_bars", 24))

    for index, candle in enumerate(future_candles, start=1):
        exit_price = None
        outcome_reason = None
        if direction == SignalDirection.LONG:
            if candle.low <= stop_price:
                exit_price = stop_price
                outcome_reason = "stop-loss"
            elif candle.high >= take_profit:
                exit_price = take_profit
                outcome_reason = "take-profit"
        else:
            if candle.high >= stop_price:
                exit_price = stop_price
                outcome_reason = "stop-loss"
            elif candle.low <= take_profit:
                exit_price = take_profit
                outcome_reason = "take-profit"

        if exit_price is None and index >= horizon_bars:
            exit_price = candle.close
            outcome_reason = "expired"

        if exit_price is None:
            continue

        gross_pnl = (
            exit_price - entry_price
            if direction == SignalDirection.LONG
            else entry_price - exit_price
        )
        return {
            **item,
            "resolved_at": candle.timestamp.isoformat(),
            "exit_price": exit_price,
            "gross_pnl": round(gross_pnl, 6),
            "bars_held": index,
            "outcome_reason": outcome_reason,
        }

    return None
