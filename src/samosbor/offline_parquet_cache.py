from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from .domain import Candle


class OfflineParquetCacheDependencyError(RuntimeError):
    """Raised when parquet cache dependencies are unavailable."""


def _imports():
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - depends on optional package
        raise OfflineParquetCacheDependencyError(
            "Offline parquet cache support requires pandas and pyarrow."
        ) from exc
    return pd


def load_candle_frame(path: Path):
    pd = _imports()
    if not path.exists():
        return _empty_candle_frame(pd)

    frame = pd.read_parquet(path)
    timestamp_series = _timestamp_series(frame)
    normalized = frame.copy()
    normalized["__timestamp"] = pd.to_datetime(timestamp_series, utc=True)
    columns = [column for column in ("open", "high", "low", "close", "volume") if column in normalized.columns]
    normalized = normalized[columns + ["__timestamp"]]
    normalized = normalized.set_index("__timestamp").sort_index()
    normalized.index.name = "time"
    return normalized


def candles_to_frame(candles: list[Candle]):
    pd = _imports()
    if not candles:
        return _empty_candle_frame(pd)

    frame = pd.DataFrame(
        [
            {
                "time": candle.timestamp.astimezone(timezone.utc),
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
            }
            for candle in candles
        ]
    )
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    frame = frame.set_index("time").sort_index()
    frame.index.name = "time"
    return frame


def merge_candle_frames(existing, fresh):
    pd = _imports()
    if existing.empty:
        merged = fresh.copy()
    elif fresh.empty:
        merged = existing.copy()
    else:
        merged = pd.concat([existing, fresh], axis=0)
        merged = merged[~merged.index.duplicated(keep="last")]
    merged = merged.sort_index()
    merged.index = pd.to_datetime(merged.index, utc=True)
    merged.index.name = "time"
    return merged


def write_candle_frame(path: Path, frame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.sort_index().to_parquet(path)


def latest_candle_timestamp(frame) -> datetime | None:
    if frame.empty:
        return None
    latest = frame.index.max()
    return latest.to_pydatetime().astimezone(timezone.utc)


def incremental_fetch_start(
    latest_timestamp: datetime | None,
    *,
    bootstrap_history_days: int,
    overlap_hours: int,
) -> datetime:
    now = datetime.now(timezone.utc)
    if latest_timestamp is None:
        return now - timedelta(days=max(1, bootstrap_history_days))
    return latest_timestamp - timedelta(hours=max(1, overlap_hours))


def _empty_candle_frame(pd):
    frame = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    frame.index = pd.DatetimeIndex([], tz="UTC", name="time")
    return frame


def _timestamp_series(frame):
    for key in ("time", "timestamp", "utc_ts", "datetime"):
        if key in frame.columns:
            return frame[key]
    if getattr(frame.index, "name", "") in {"time", "timestamp", "utc_ts", "datetime"}:
        return frame.index
    raise ValueError(
        "Unsupported parquet schema: expected a time/timestamp/utc_ts column or index."
    )
