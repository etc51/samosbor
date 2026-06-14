from __future__ import annotations

from typing import Protocol

from ..domain import Candle, Instrument


class ExternalContextProvider(Protocol):
    def score(self, instrument: Instrument, candles: list[Candle]) -> float:
        ...


class NeutralContextProvider:
    def score(self, instrument: Instrument, candles: list[Candle]) -> float:
        return 0.0


class StaticContextProvider:
    def __init__(self, scores: dict[str, float]):
        self.scores = {symbol.upper(): score for symbol, score in scores.items()}

    def score(self, instrument: Instrument, candles: list[Candle]) -> float:
        return self.scores.get(instrument.symbol.upper(), 0.0)
