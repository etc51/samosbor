from __future__ import annotations

import logging
import os
import warnings
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Iterator

from ..config import AppConfig
from ..domain import Candle, Instrument, InstrumentType

LOGGER = logging.getLogger(__name__)


class TBankDependencyError(RuntimeError):
    """Raised when the T-Bank SDK is unavailable."""


def _sdk_imports():
    try:
        from t_tech.invest import CandleInterval, Client, InstrumentType as TInstrumentType
        from t_tech.invest.exceptions import RequestError
        from t_tech.invest.utils import now, quotation_to_decimal
    except ImportError as exc:  # pragma: no cover - depends on external package
        raise TBankDependencyError(
            "T-Bank SDK is not installed. Install requirements-tbank.txt first."
        ) from exc
    return CandleInterval, Client, TInstrumentType, RequestError, now, quotation_to_decimal


def timeframe_to_tbank_interval(timeframe: str):
    candle_interval, _, _, _, _, _ = _sdk_imports()
    mapping = {
        "day": candle_interval.CANDLE_INTERVAL_DAY,
        "hour": candle_interval.CANDLE_INTERVAL_HOUR,
        "30min": candle_interval.CANDLE_INTERVAL_30_MIN,
        "15min": candle_interval.CANDLE_INTERVAL_15_MIN,
        "10min": candle_interval.CANDLE_INTERVAL_10_MIN,
        "5min": candle_interval.CANDLE_INTERVAL_5_MIN,
        "1min": candle_interval.CANDLE_INTERVAL_1_MIN,
    }
    try:
        return mapping[timeframe.lower()]
    except KeyError as exc:
        raise ValueError(f"Unsupported timeframe: {timeframe}") from exc


class TBankMarketDataProvider:
    def __init__(self, config: AppConfig):
        self.config = config

    def _token(self) -> str:
        token = os.environ.get(self.config.tbank.token_env, "")
        if not token:
            raise RuntimeError(
                f"Environment variable {self.config.tbank.token_env} is not set."
            )
        return token

    @contextmanager
    def _client(self) -> Iterator[object]:
        _, client_cls, _, _, _, _ = _sdk_imports()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with client_cls(self._token(), app_name=self.config.tbank.app_name) as client:
                yield client

    def list_accounts(self) -> list[dict[str, str]]:
        with self._client() as client:
            response = client.users.get_accounts()
            return [
                {
                    "id": account.id,
                    "name": account.name,
                    "status": str(account.status),
                    "type": str(account.type),
                    "access_level": str(account.access_level),
                }
                for account in response.accounts
            ]

    def resolve_universe(self, instruments: list[Instrument]) -> list[Instrument]:
        return [self.resolve_instrument(instrument) for instrument in instruments]

    def resolve_instrument(self, instrument: Instrument) -> Instrument:
        if instrument.uid or instrument.figi:
            return instrument

        _, _, tbank_instrument_type, _, _, quotation_to_decimal = _sdk_imports()
        try:
            from t_tech.invest.utils import money_to_decimal
        except ImportError as exc:  # pragma: no cover - depends on external package
            raise TBankDependencyError(
                "T-Bank SDK is not installed. Install requirements-tbank.txt first."
            ) from exc
        try:
            from t_tech.invest import InstrumentIdType
        except ImportError as exc:  # pragma: no cover - depends on external package
            raise TBankDependencyError(
                "T-Bank SDK is not installed. Install requirements-tbank.txt first."
            ) from exc
        kind_map = {
            InstrumentType.STOCK: tbank_instrument_type.INSTRUMENT_TYPE_SHARE,
            InstrumentType.FUTURE: tbank_instrument_type.INSTRUMENT_TYPE_FUTURES,
        }

        with self._client() as client:
            response = client.instruments.find_instrument(
                query=instrument.symbol,
                instrument_kind=kind_map[instrument.instrument_type],
                api_trade_available_flag=True,
            )

        exact_match = None
        for candidate in response.instruments:
            if candidate.ticker.upper() == instrument.symbol.upper():
                exact_match = candidate
                break
        candidate = exact_match or (response.instruments[0] if response.instruments else None)
        if candidate is None:
            raise LookupError(f"Instrument not found for symbol {instrument.symbol}")

        with self._client() as client:
            if instrument.instrument_type == InstrumentType.STOCK:
                full = client.instruments.share_by(
                    id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_UID,
                    id=candidate.uid,
                ).instrument
                margin = None
            else:
                full = client.instruments.future_by(
                    id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_UID,
                    id=candidate.uid,
                ).instrument
                margin = client.instruments.get_futures_margin(instrument_id=candidate.uid)

        resolved = Instrument(
            symbol=instrument.symbol,
            instrument_type=instrument.instrument_type,
            figi=candidate.figi,
            uid=candidate.uid,
            class_code=getattr(full, "class_code", getattr(candidate, "class_code", "")),
            lot_size=int(getattr(full, "lot", instrument.lot_size or 1)),
            tick_size=float(quotation_to_decimal(full.min_price_increment)),
            currency=getattr(full, "currency", instrument.currency),
            initial_margin_buy=(
                float(money_to_decimal(margin.initial_margin_on_buy)) if margin is not None else 0.0
            ),
            initial_margin_sell=(
                float(money_to_decimal(margin.initial_margin_on_sell)) if margin is not None else 0.0
            ),
            tick_value=(
                float(quotation_to_decimal(margin.min_price_increment_amount))
                if margin is not None
                else 0.0
            ),
        )
        LOGGER.info(
            "Resolved %s as uid=%s figi=%s lot=%s margin_buy=%.2f margin_sell=%.2f",
            resolved.symbol,
            resolved.uid,
            resolved.figi,
            resolved.lot_size,
            resolved.initial_margin_buy,
            resolved.initial_margin_sell,
        )
        return resolved

    def get_candles(
        self,
        instrument: Instrument,
        *,
        timeframe: str,
        history_days: int,
    ) -> list[Candle]:
        _, _, _, _, now_fn, _ = _sdk_imports()
        to_dt = now_fn()
        from_dt = to_dt - timedelta(days=history_days)
        return self.get_candles_range(
            instrument,
            timeframe=timeframe,
            from_dt=from_dt,
            to_dt=to_dt,
        )

    def get_candles_range(
        self,
        instrument: Instrument,
        *,
        timeframe: str,
        from_dt: datetime,
        to_dt: datetime | None = None,
    ) -> list[Candle]:
        interval = timeframe_to_tbank_interval(timeframe)
        _, _, _, _, now_fn, quotation_to_decimal = _sdk_imports()
        if to_dt is None:
            to_dt = now_fn()

        with self._client() as client:
            response = list(
                client.get_all_candles(
                    instrument_id=instrument.instrument_id,
                    from_=from_dt,
                    to=to_dt,
                    interval=interval,
                )
            )

        candles = [
            Candle(
                timestamp=item.time,
                open=float(quotation_to_decimal(item.open)),
                high=float(quotation_to_decimal(item.high)),
                low=float(quotation_to_decimal(item.low)),
                close=float(quotation_to_decimal(item.close)),
                volume=float(item.volume),
            )
            for item in response
        ]
        return sorted(candles, key=lambda candle: candle.timestamp)

    def load_history(self, instruments: list[Instrument]) -> dict[str, list[Candle]]:
        resolved = self.resolve_universe(instruments)
        return {
            instrument.symbol: self.get_candles(
                instrument,
                timeframe=self.config.data.timeframe,
                history_days=self.config.data.history_days,
            )
            for instrument in resolved
        }

    def get_last_prices(self, instruments: list[Instrument]) -> dict[str, float]:
        _, _, _, _, _, quotation_to_decimal = _sdk_imports()
        resolved = self.resolve_universe(instruments)
        with self._client() as client:
            response = client.market_data.get_last_prices(
                instrument_id=[instrument.instrument_id for instrument in resolved]
            )

        price_map = {}
        for instrument, item in zip(resolved, response.last_prices):
            price_map[instrument.symbol] = float(quotation_to_decimal(item.price))
        return price_map
