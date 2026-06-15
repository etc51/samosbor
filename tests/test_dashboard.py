from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from samosbor.dashboard import build_dashboard_payload, render_dashboard_html


class DashboardTest(unittest.TestCase):
    def test_dashboard_reads_latest_samosbor_runtime_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config_dir = root / "configs"
            state_dir = root / "state"
            runs_dir = root / "runs"
            config_dir.mkdir(parents=True)
            state_dir.mkdir(parents=True)
            runs_dir.mkdir(parents=True)

            config_path = config_dir / "paper.toml"
            config_path.write_text(
                "\n".join(
                    [
                        "[app]",
                        'timezone = "Europe/Moscow"',
                        "",
                        "[tbank]",
                        'account_name = "Акции"',
                        "",
                        "[data]",
                        'source = "csv"',
                        'csv_path = "data/demo.csv"',
                        "",
                        "[[data.instruments]]",
                        'symbol = "LKOH"',
                        'instrument_type = "stock"',
                        "",
                        "[[data.instruments]]",
                        'symbol = "TATN"',
                        'instrument_type = "stock"',
                        "",
                        "[strategy]",
                        'style = "ema_adx_macd"',
                        "",
                        "[execution]",
                        'mode = "local-paper"',
                        "allow_live_trading = false",
                        'state_path = "state/demo_state.json"',
                        "",
                        "[backtest]",
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

            (state_dir / "demo_state.json").write_text(
                json.dumps(
                    {
                        "portfolio": {
                            "cash": 299999.59,
                            "realized_pnl": -4.9,
                            "peak_equity": 300100.0,
                            "trading_halted": False,
                            "positions": {
                                "LKOH": {
                                    "direction": "long",
                                    "quantity_lots": 1,
                                    "entry_price": 7025.0,
                                    "current_price": 7080.0,
                                    "stop_price": 6960.0,
                                    "take_profit": 7155.0,
                                    "margin_requirement": 0.0,
                                    "signal_strength": 0.77,
                                    "opened_at": "2026-06-15T09:00:00+00:00",
                                    "updated_at": "2026-06-15T09:35:00+00:00",
                                }
                            },
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (state_dir / "demo_state_signal_feedback.json").write_text(
                json.dumps({"pending": [{"symbol": "TATN"}], "resolved": [{"symbol": "LKOH"}]}),
                encoding="utf-8",
            )

            self._write_json(
                runs_dir / "paper" / "20260615-093644" / "cycle_summary.json",
                {
                    "timestamp": "2026-06-15T09:36:44.918301+00:00",
                    "equity_rub": 299995.1,
                    "cash_rub": 299999.59,
                    "gross_exposure_rub": 2058.39,
                    "open_positions": 2,
                    "trading_halted": False,
                },
            )
            self._write_json(
                runs_dir / "paper-reports" / "20260615-091418" / "summary.json",
                {
                    "summary": {
                        "trades": 4,
                        "net_pnl_rub": 125.0,
                        "win_rate_pct": 50.0,
                        "profit_factor": 1.2,
                        "expectancy_rub": 31.25,
                    },
                    "portfolio": {"open_positions": 2},
                },
            )
            self._write_json(
                runs_dir / "autotune" / "effective-config" / "20260615-093614" / "effective_config.json",
                {
                    "effective_config_path": str(config_dir / "paper.effective.toml"),
                    "applied_strategy_overrides": {
                        "allowed_entry_hours": [9, 10, 12],
                        "blocked_long_symbols": ["LKOH"],
                    },
                    "rollback_guardrail": {"rollback_to_base": False, "reason": "ok"},
                    "sources": [
                        {
                            "source": "entry-symbols",
                            "changed": True,
                            "selected_values": {"blocked_long_symbols": ["LKOH"]},
                            "activation": {"reason": "confirmed"},
                        }
                    ],
                    "output_dir": str(runs_dir / "autotune" / "effective-config" / "20260615-093614"),
                },
            )
            self._write_json(
                runs_dir / "autotune" / "entry-symbols" / "20260615-093603" / "symbol_restrictions.json",
                {
                    "changed": True,
                    "reason": "entry symbol restrictions updated from paper results",
                    "evidence_source": "signal-feedback",
                    "proposed_blocked_symbols": [],
                    "proposed_blocked_long_symbols": ["LKOH"],
                    "proposed_blocked_short_symbols": [],
                    "symbol_direction_breakdown": [
                        {
                            "symbol": "LKOH",
                            "direction": "long",
                            "trades": 8,
                            "win_rate_pct": 37.5,
                            "net_pnl_rub": -0.01,
                            "profit_factor": 0.98,
                            "expectancy_rub": -0.001,
                        }
                    ],
                },
            )
            self._write_json(
                runs_dir / "autotune" / "entry-schedule" / "20260615-091418" / "schedule_tuning.json",
                {
                    "changed": True,
                    "reason": "hours updated from paper results",
                    "evidence_source": "signal-feedback",
                    "proposed_hours": [9, 10, 12],
                },
            )
            self._write_json(
                runs_dir / "autotune" / "entry-quality" / "20260615-081025" / "entry_quality_tuning.json",
                {
                    "changed": False,
                    "reason": "no change",
                    "evidence_source": "signal-feedback",
                    "recommended_min_signal_strength": 0.0,
                },
            )
            self._write_json(
                runs_dir / "autotune" / "nightly-autonomy" / "20260615-081500" / "nightly_autonomy.json",
                {
                    "timestamp": "2026-06-15T08:15:00+00:00",
                    "steps_executed": ["paper-report", "bootstrap-entry-feedback", "tune-entry-symbols"],
                    "output_dir": str(runs_dir / "autotune" / "nightly-autonomy" / "20260615-081500"),
                },
            )

            payload = build_dashboard_payload(config_path, effective_config_path=config_dir / "paper.effective.toml")
            html = render_dashboard_html(payload)

            self.assertEqual(payload["runtime"]["latest_cycle"]["equity_rub"], 299995.1)
            self.assertEqual(
                payload["autonomy"]["effective_runtime"]["applied_strategy_overrides"]["blocked_long_symbols"],
                ["LKOH"],
            )
            self.assertEqual(payload["runtime"]["signal_feedback"]["resolved_signals"], 1)
            self.assertIn("Samosbor Paper Dashboard", html)
            self.assertIn("LKOH", html)
            self.assertIn("blocked_long_symbols", html)

    def test_dashboard_ignores_stale_futures_autonomy_artifacts_for_stock_runtime(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config_dir = root / "configs"
            state_dir = root / "state"
            runs_dir = root / "runs"
            config_dir.mkdir(parents=True)
            state_dir.mkdir(parents=True)
            runs_dir.mkdir(parents=True)

            config_path = config_dir / "paper.toml"
            config_path.write_text(
                "\n".join(
                    [
                        "[app]",
                        'timezone = "Europe/Moscow"',
                        "",
                        "[tbank]",
                        'account_name = "Акции"',
                        "",
                        "[data]",
                        'source = "csv"',
                        'csv_path = "data/demo.csv"',
                        "",
                        "[[data.instruments]]",
                        'symbol = "LKOH"',
                        'instrument_type = "stock"',
                        "",
                        "[[data.instruments]]",
                        'symbol = "TATN"',
                        'instrument_type = "stock"',
                        "",
                        "[strategy]",
                        'style = "ema_adx_macd"',
                        "allowed_entry_hours = [10, 11, 12]",
                        "",
                        "[execution]",
                        'mode = "local-paper"',
                        "allow_live_trading = false",
                        'state_path = "state/demo_state.json"',
                        "",
                        "[backtest]",
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

            (state_dir / "demo_state.json").write_text(
                json.dumps({"portfolio": {"cash": 300000.0, "positions": {}}}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (state_dir / "demo_state_signal_feedback.json").write_text(
                json.dumps({"pending": [], "resolved": []}),
                encoding="utf-8",
            )

            self._write_json(
                runs_dir / "autotune" / "entry-symbols" / "20260615-090000" / "symbol_restrictions.json",
                {
                    "changed": True,
                    "reason": "stock restriction",
                    "evidence_source": "signal-feedback",
                    "proposed_blocked_symbols": [],
                    "proposed_blocked_long_symbols": ["LKOH"],
                    "proposed_blocked_short_symbols": [],
                    "symbol_direction_breakdown": [
                        {
                            "symbol": "LKOH",
                            "direction": "long",
                            "trades": 4,
                            "win_rate_pct": 25.0,
                            "net_pnl_rub": -120.0,
                            "profit_factor": 0.7,
                            "expectancy_rub": -30.0,
                        }
                    ],
                },
            )
            self._write_json(
                runs_dir / "autotune" / "entry-symbols" / "20260615-100000" / "symbol_restrictions.json",
                {
                    "changed": True,
                    "reason": "stale futures restriction",
                    "evidence_source": "signal-feedback",
                    "proposed_blocked_symbols": [],
                    "proposed_blocked_long_symbols": ["CNYRUBF"],
                    "proposed_blocked_short_symbols": [],
                    "symbol_direction_breakdown": [
                        {
                            "symbol": "CNYRUBF",
                            "direction": "long",
                            "trades": 12,
                            "win_rate_pct": 33.3,
                            "net_pnl_rub": -420.0,
                            "profit_factor": 0.5,
                            "expectancy_rub": -35.0,
                        }
                    ],
                },
            )
            self._write_json(
                runs_dir / "autotune" / "entry-schedule" / "20260615-090000" / "schedule_tuning.json",
                {
                    "changed": True,
                    "reason": "stock schedule",
                    "evidence_source": "signal-feedback",
                    "proposed_hours": [10, 11],
                },
            )
            self._write_json(
                runs_dir / "autotune" / "entry-schedule" / "20260615-100000" / "schedule_tuning.json",
                {
                    "changed": True,
                    "reason": "stale futures schedule",
                    "evidence_source": "signal-feedback",
                    "proposed_hours": [9, 20],
                },
            )

            payload = build_dashboard_payload(config_path)
            html = render_dashboard_html(payload)

            self.assertEqual(
                payload["autonomy"]["entry_symbols"]["proposed_blocked_long_symbols"],
                ["LKOH"],
            )
            self.assertEqual(
                payload["autonomy"]["entry_schedule"]["proposed_hours"],
                [10, 11],
            )
            self.assertNotIn("CNYRUBF", html)
            self.assertIn("LKOH", html)

    def test_dashboard_sanitizes_incompatible_only_autonomy_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config_dir = root / "configs"
            state_dir = root / "state"
            runs_dir = root / "runs"
            config_dir.mkdir(parents=True)
            state_dir.mkdir(parents=True)
            runs_dir.mkdir(parents=True)

            config_path = config_dir / "paper.toml"
            config_path.write_text(
                "\n".join(
                    [
                        "[app]",
                        'timezone = "Europe/Moscow"',
                        "",
                        "[tbank]",
                        'account_name = "Акции"',
                        "",
                        "[data]",
                        'source = "csv"',
                        'csv_path = "data/demo.csv"',
                        "",
                        "[[data.instruments]]",
                        'symbol = "LKOH"',
                        'instrument_type = "stock"',
                        "",
                        "[[data.instruments]]",
                        'symbol = "TATN"',
                        'instrument_type = "stock"',
                        "",
                        "[strategy]",
                        'style = "ema_adx_macd"',
                        "allowed_entry_hours = [10, 11, 12]",
                        "",
                        "[execution]",
                        'mode = "local-paper"',
                        "allow_live_trading = false",
                        'state_path = "state/demo_state.json"',
                        "",
                        "[backtest]",
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

            (state_dir / "demo_state.json").write_text(
                json.dumps({"portfolio": {"cash": 300000.0, "positions": {}}}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (state_dir / "demo_state_signal_feedback.json").write_text(
                json.dumps({"pending": [], "resolved": []}),
                encoding="utf-8",
            )

            self._write_json(
                runs_dir / "autotune" / "entry-symbols" / "20260615-100000" / "symbol_restrictions.json",
                {
                    "changed": True,
                    "reason": "stale futures restriction",
                    "evidence_source": "signal-feedback",
                    "proposed_blocked_symbols": [],
                    "proposed_blocked_long_symbols": ["CNYRUBF"],
                    "proposed_blocked_short_symbols": [],
                    "symbol_direction_breakdown": [
                        {
                            "symbol": "CNYRUBF",
                            "direction": "long",
                            "trades": 12,
                            "win_rate_pct": 33.3,
                            "net_pnl_rub": -420.0,
                            "profit_factor": 0.5,
                            "expectancy_rub": -35.0,
                        }
                    ],
                },
            )
            self._write_json(
                runs_dir / "autotune" / "entry-schedule" / "20260615-100000" / "schedule_tuning.json",
                {
                    "changed": True,
                    "reason": "stale futures schedule",
                    "evidence_source": "signal-feedback",
                    "proposed_hours": [9, 20],
                },
            )

            payload = build_dashboard_payload(config_path)
            html = render_dashboard_html(payload)

            self.assertEqual(payload["autonomy"]["entry_symbols"]["proposed_blocked_long_symbols"], [])
            self.assertEqual(payload["autonomy"]["entry_symbols"]["symbol_direction_breakdown"], [])
            self.assertIn(
                "not compatible with current runtime universe",
                payload["autonomy"]["entry_symbols"]["reason"],
            )
            self.assertEqual(payload["autonomy"]["entry_schedule"]["proposed_hours"], [])
            self.assertIn(
                "not compatible with current runtime hours",
                payload["autonomy"]["entry_schedule"]["reason"],
            )
            self.assertNotIn("CNYRUBF", html)

    @staticmethod
    def _write_json(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
