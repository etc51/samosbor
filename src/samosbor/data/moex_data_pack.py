from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from ..domain import Candle, Instrument, InstrumentType


class MoexDataPackDependencyError(RuntimeError):
    """Raised when local parquet dependencies are unavailable."""


def _imports():
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - depends on optional package
        raise MoexDataPackDependencyError(
            "Local data pack support requires pandas and pyarrow."
        ) from exc
    return pd


def timeframe_to_pandas_frequency(timeframe: str) -> str:
    mapping = {
        "1min": "1min",
        "5min": "5min",
        "10min": "10min",
        "15min": "15min",
        "30min": "30min",
        "hour": "1h",
        "day": "1d",
    }
    try:
        return mapping[timeframe.lower()]
    except KeyError as exc:
        raise ValueError(f"Unsupported timeframe for local data pack: {timeframe}") from exc


class MoexDataPackProvider:
    def __init__(self, base_path: Path, *, timeframe: str, history_days: int):
        self.base_path = base_path
        self.timeframe = timeframe
        self.history_days = history_days
        self.candles_root = base_path / "data_pack" / "candles_1m"
        self.metadata_path = base_path / "data_pack" / "metadata" / "instruments.parquet"
        pd = _imports()
        self._metadata = pd.read_parquet(self.metadata_path)

    def resolve_universe(self, instruments: list[Instrument]) -> list[Instrument]:
        return [self.resolve_instrument(instrument) for instrument in instruments]

    def resolve_instrument(self, instrument: Instrument) -> Instrument:
        symbol = instrument.symbol.upper()
        folder = self.candles_root / symbol
        if not folder.exists():
            raise FileNotFoundError(f"Local data pack folder not found for symbol {symbol}: {folder}")

        rows = self._metadata[
            (self._metadata["ticker"].str.upper() == symbol)
            | (self._metadata["root_symbol"].str.upper() == symbol)
            | (self._metadata["display_code"].str.upper() == symbol)
        ].copy()
        if rows.empty:
            raise LookupError(f"No metadata row found for symbol {symbol}")

        rows["ticker_match"] = rows["ticker"].str.upper() == symbol
        rows["display_match"] = rows["display_code"].str.upper() == symbol
        rows["expiration_date"] = rows["expiration_date"].fillna("")
        rows = rows.sort_values(
            by=["ticker_match", "display_match", "is_current", "expiration_date"],
            ascending=[False, False, False, False],
        )
        row = rows.iloc[0]
        instrument_type = (
            InstrumentType.FUTURE
            if str(row["class_code"]).upper() == "SPBFUT"
            else InstrumentType.STOCK
        )
        return Instrument(
            symbol=symbol,
            instrument_type=instrument_type,
            figi=str(row.get("figi", "")),
            uid=str(row["instrument_uid"]),
            class_code=str(row.get("class_code", "")),
            lot_size=int(row.get("lot", 1) or 1),
            tick_size=float(row.get("tick_size", 0.01) or 0.01),
            currency=str(row.get("currency", "rub")),
        )

    def load_history(self, instruments: list[Instrument]) -> dict[str, list[Candle]]:
        resolved = self.resolve_universe(instruments)
        return {instrument.symbol: self.get_candles(instrument) for instrument in resolved}

    def get_candles(self, instrument: Instrument) -> list[Candle]:
        pd = _imports()
        folder = self.candles_root / instrument.symbol
        files = sorted(folder.glob(f"{instrument.uid}_*.parquet"))
        if not files:
            raise FileNotFoundError(
                f"No parquet candles found for symbol {instrument.symbol} and uid {instrument.uid}"
            )

        frames = [pd.read_parquet(path) for path in files]
        frame = pd.concat(frames, ignore_index=True)
        frame = frame.sort_values("utc_ts")
        frame["utc_ts"] = pd.to_datetime(frame["utc_ts"], utc=True)

        if self.history_days > 0 and not frame.empty:
            cutoff = frame["utc_ts"].max() - timedelta(days=self.history_days)
            frame = frame[frame["utc_ts"] >= cutoff]

        if self.timeframe.lower() != "1min":
            frame = self._resample(frame, timeframe_to_pandas_frequency(self.timeframe))

        candles = [
            Candle(
                timestamp=row["utc_ts"].to_pydatetime(),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume_lots"]),
            )
            for row in frame.to_dict(orient="records")
        ]
        return candles

    def _resample(self, frame, frequency: str):
        pd = _imports()
        resampled = (
            frame.set_index("utc_ts")
            .resample(frequency)
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume_lots": "sum",
                }
            )
            .dropna(subset=["open", "high", "low", "close"])
            .reset_index()
        )
        if not isinstance(resampled["utc_ts"].dtype, pd.DatetimeTZDtype):
            resampled["utc_ts"] = pd.to_datetime(resampled["utc_ts"], utc=True)
        return resampled
