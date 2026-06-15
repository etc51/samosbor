from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from samosbor.config import load_config
from samosbor.domain import Candle, ExitReason, Instrument, InstrumentType, Signal, SignalDirection
from samosbor.execution.paper import LocalPaperBroker
from samosbor.orchestrator import TradingOrchestrator


class _FakeProvider:
    def __init__(self, instruments: list[Instrument], history: dict[str, list[Candle]]):
        self._instruments = instruments
        self._history = history

    def resolve_universe(self, instruments: list[Instrument]) -> list[Instrument]:
        return self._instruments

    def load_history(self, instruments: list[Instrument]) -> dict[str, list[Candle]]:
        return self._history


class _PaperCycleOrchestrator(TradingOrchestrator):
    def __init__(self, config, provider):
        super().__init__(config)
        self._provider = provider

    def _data_provider(self):
        return self._provider


class PaperCycleSessionFlatTest(unittest.TestCase):
    def test_paper_cycle_flattens_existing_position_in_session_window(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config_dir = root / "configs"
            config_dir.mkdir(parents=True)
            config_path = config_dir / "paper.toml"
            config_path.write_text(
                "\n".join(
                    [
                        "[app]",
                        'timezone = "Europe/Moscow"',
                        "",
                        "[data]",
                        'source = "csv"',
                        'csv_path = "data/demo.csv"',
                        'timeframe = "30min"',
                        "",
                        "[[data.instruments]]",
                        'symbol = "SBER"',
                        'instrument_type = "stock"',
                        "lot_size = 1",
                        "",
                        "[strategy]",
                        "min_liquidity_rub = 1.0",
                        "allowed_entry_hours = [10, 11, 12, 13, 14, 15, 16, 17]",
                        "allowed_entry_weekdays = [0, 1, 2, 3, 4]",
                        "forced_flat_hours = [18, 19, 20, 21, 22, 23]",
                        "forced_flat_weekdays = [0, 1, 2, 3, 4]",
                        "",
                        "[execution]",
                        'mode = "local-paper"',
                        "allow_live_trading = false",
                        'state_path = "state/paper_state.json"',
                        "",
                        "[backtest]",
                        "initial_cash = 100000",
                        "",
                        "[reporting]",
                        'output_dir = "runs"',
                        "",
                        "[research]",
                        "",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            config = load_config(config_path)
            instrument = Instrument(symbol="SBER", instrument_type=InstrumentType.STOCK, lot_size=1)
            state_path = config.resolve_path(config.execution.state_path)
            broker = LocalPaperBroker.fresh(100_000, slippage_bps=0, commission_bps=0)
            broker.open_position(
                Signal(
                    instrument=instrument,
                    direction=SignalDirection.LONG,
                    strength=0.8,
                    entry_price=100.0,
                    stop_price=95.0,
                    take_profit=110.0,
                    reason="bootstrap-position",
                ),
                10,
                datetime(2025, 1, 1, 13, 0, tzinfo=timezone.utc),
            )
            broker.save(state_path)

            latest_candle = Candle(
                timestamp=datetime(2025, 1, 1, 15, 0, tzinfo=timezone.utc),
                open=100.0,
                high=100.4,
                low=99.9,
                close=100.1,
                volume=5_000_000,
            )
            orchestrator = _PaperCycleOrchestrator(
                config,
                _FakeProvider([instrument], {"SBER": [latest_candle]}),
            )

            orchestrator.run_paper_cycle()
            reloaded = LocalPaperBroker.load(
                state_path,
                initial_cash=config.backtest.initial_cash,
                slippage_bps=config.execution.slippage_bps,
                commission_bps=config.execution.commission_bps,
            )

            self.assertEqual(len(reloaded.portfolio.positions), 0)
            self.assertEqual(len(reloaded.trades), 1)
            self.assertEqual(reloaded.trades[0].reason, ExitReason.SESSION_FLAT.value)


if __name__ == "__main__":
    unittest.main()
