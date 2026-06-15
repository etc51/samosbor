from __future__ import annotations

import argparse
import html
import json
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .autonomy.signal_feedback import signal_feedback_path
from .config import AppConfig, load_config


def build_dashboard_payload(
    config_path: str | Path,
    *,
    effective_config_path: str | Path | None = None,
) -> dict[str, object]:
    config = load_config(config_path)
    reporting_dir = config.resolve_path(config.reporting.output_dir)
    state_path = config.resolve_path(config.execution.state_path)
    feedback_path = signal_feedback_path(state_path)

    paper_cycle = _read_latest_json(reporting_dir / "paper", "cycle_summary.json")
    paper_report = _read_latest_json(reporting_dir / "paper-reports", "summary.json")
    nightly = _read_latest_json(reporting_dir / "autotune" / "nightly-autonomy", "nightly_autonomy.json")
    effective_runtime = _read_latest_json(
        reporting_dir / "autotune" / "effective-config",
        "effective_config.json",
    )
    entry_symbols = _read_latest_json(
        reporting_dir / "autotune" / "entry-symbols",
        "symbol_restrictions.json",
    )
    entry_schedule = _read_latest_json(
        reporting_dir / "autotune" / "entry-schedule",
        "schedule_tuning.json",
    )
    entry_quality = _read_latest_json(
        reporting_dir / "autotune" / "entry-quality",
        "entry_quality_tuning.json",
    )
    state_payload = _read_json_file(state_path)
    feedback_payload = _read_json_file(feedback_path)

    portfolio = dict(state_payload.get("portfolio", {}))
    positions = _positions_from_state(portfolio.get("positions", {}))
    latest_summary = paper_cycle if paper_cycle else {}
    report_summary = paper_report.get("summary", {}) if paper_report else {}
    report_portfolio = paper_report.get("portfolio", {}) if paper_report else {}
    overrides = dict(effective_runtime.get("applied_strategy_overrides", {})) if effective_runtime else {}

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "config_path": str(Path(config_path).resolve()),
            "effective_config_path": (
                str(Path(effective_config_path).resolve())
                if effective_config_path is not None
                else str(effective_runtime.get("effective_config_path", ""))
            ),
            "paper_only_mode": config.execution.mode.value,
            "allow_live_trading": config.execution.allow_live_trading,
            "account_name": config.tbank.account_name,
            "instruments": [instrument.symbol for instrument in config.data.instruments],
            "state_path": str(state_path),
            "feedback_path": str(feedback_path),
            "reporting_dir": str(reporting_dir),
        },
        "runtime": {
            "portfolio_state": {
                "cash_rub": round(float(portfolio.get("cash", 0.0)), 2),
                "realized_pnl_rub": round(float(portfolio.get("realized_pnl", 0.0)), 2),
                "peak_equity_rub": round(float(portfolio.get("peak_equity", 0.0)), 2),
                "open_positions": len(positions),
                "trading_halted": bool(portfolio.get("trading_halted", False)),
            },
            "latest_cycle": latest_summary,
            "latest_report_summary": report_summary,
            "latest_report_portfolio": report_portfolio,
            "positions": positions,
            "signal_feedback": {
                "pending_signals": len(feedback_payload.get("pending", [])),
                "resolved_signals": len(feedback_payload.get("resolved", [])),
            },
        },
        "autonomy": {
            "effective_runtime": {
                "output_dir": str(effective_runtime.get("output_dir", "")),
                "applied_strategy_overrides": overrides,
                "rollback_guardrail": dict(effective_runtime.get("rollback_guardrail", {})),
                "sources": list(effective_runtime.get("sources", [])),
            },
            "entry_symbols": {
                "changed": bool(entry_symbols.get("changed", False)),
                "reason": str(entry_symbols.get("reason", "")),
                "evidence_source": str(entry_symbols.get("evidence_source", "")),
                "proposed_blocked_symbols": list(entry_symbols.get("proposed_blocked_symbols", [])),
                "proposed_blocked_long_symbols": list(
                    entry_symbols.get("proposed_blocked_long_symbols", [])
                ),
                "proposed_blocked_short_symbols": list(
                    entry_symbols.get("proposed_blocked_short_symbols", [])
                ),
                "symbol_direction_breakdown": list(
                    entry_symbols.get("symbol_direction_breakdown", [])
                ),
            },
            "entry_schedule": {
                "changed": bool(entry_schedule.get("changed", False)),
                "reason": str(entry_schedule.get("reason", "")),
                "evidence_source": str(entry_schedule.get("evidence_source", "")),
                "proposed_hours": list(entry_schedule.get("proposed_hours", [])),
            },
            "entry_quality": {
                "changed": bool(entry_quality.get("changed", False)),
                "reason": str(entry_quality.get("reason", "")),
                "evidence_source": str(entry_quality.get("evidence_source", "")),
                "recommended_min_signal_strength": float(
                    entry_quality.get("recommended_min_signal_strength", 0.0)
                ),
            },
            "nightly_autonomy": {
                "output_dir": str(nightly.get("output_dir", "")),
                "steps_executed": list(nightly.get("steps_executed", [])),
                "timestamp": str(nightly.get("timestamp", "")),
            },
        },
    }


def render_dashboard_html(payload: dict[str, object]) -> str:
    config = dict(payload["config"])
    runtime = dict(payload["runtime"])
    autonomy = dict(payload["autonomy"])
    portfolio_state = dict(runtime["portfolio_state"])
    latest_cycle = dict(runtime["latest_cycle"])
    latest_report_summary = dict(runtime["latest_report_summary"])
    latest_report_portfolio = dict(runtime["latest_report_portfolio"])
    effective_runtime = dict(autonomy["effective_runtime"])
    entry_symbols = dict(autonomy["entry_symbols"])
    entry_schedule = dict(autonomy["entry_schedule"])
    entry_quality = dict(autonomy["entry_quality"])

    positions_html = _render_positions(list(runtime["positions"]))
    overrides_html = _render_key_values(dict(effective_runtime["applied_strategy_overrides"]))
    sources_html = _render_sources(list(effective_runtime["sources"]))
    direction_rows_html = _render_direction_rows(list(entry_symbols["symbol_direction_breakdown"]))

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Samosbor Paper Dashboard</title>
  <style>
    :root {{
      --bg: #0d1117;
      --panel: #161b22;
      --panel-2: #1f2630;
      --line: #2d3748;
      --text: #e6edf3;
      --muted: #8b949e;
      --good: #3fb950;
      --bad: #f85149;
      --warn: #d29922;
      --accent: #58a6ff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", Tahoma, sans-serif;
      background: radial-gradient(circle at top, #182132 0, var(--bg) 45%);
      color: var(--text);
    }}
    .wrap {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 24px;
    }}
    h1, h2, h3 {{ margin: 0 0 12px; }}
    p {{ margin: 0; color: var(--muted); }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 16px;
      margin-top: 20px;
    }}
    .panel {{
      background: rgba(22, 27, 34, 0.92);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 18px;
      box-shadow: 0 10px 28px rgba(0, 0, 0, 0.24);
    }}
    .metric {{
      font-size: 28px;
      font-weight: 700;
      margin-top: 8px;
    }}
    .good {{ color: var(--good); }}
    .bad {{ color: var(--bad); }}
    .warn {{ color: var(--warn); }}
    .accent {{ color: var(--accent); }}
    .mono {{
      font-family: Consolas, "SFMono-Regular", monospace;
      font-size: 13px;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 10px;
      font-size: 14px;
    }}
    th, td {{
      padding: 8px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }}
    th {{ color: var(--muted); font-weight: 600; }}
    .chips {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 10px;
    }}
    .chip {{
      padding: 6px 10px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--panel-2);
      font-size: 13px;
    }}
    .footer {{
      margin-top: 16px;
      color: var(--muted);
      font-size: 13px;
    }}
    a {{ color: var(--accent); }}
  </style>
  <script>
    setTimeout(() => window.location.reload(), 15000);
  </script>
</head>
<body>
  <div class="wrap">
    <h1>Samosbor Paper Dashboard</h1>
    <p>Отдельный dashboard для текущего samosbor runtime. Автообновление каждые 15 секунд.</p>

    <div class="grid">
      <section class="panel">
        <h2>Runtime</h2>
        <div class="metric">{_fmt_money(float(latest_cycle.get("equity_rub", portfolio_state.get("peak_equity_rub", 0.0))))}</div>
        <p>Equity</p>
        <table>
          <tr><th>Cash</th><td>{_fmt_money(float(latest_cycle.get("cash_rub", portfolio_state.get("cash_rub", 0.0))))}</td></tr>
          <tr><th>Exposure</th><td>{_fmt_money(float(latest_cycle.get("gross_exposure_rub", 0.0)))}</td></tr>
          <tr><th>Open positions</th><td>{int(latest_cycle.get("open_positions", portfolio_state.get("open_positions", 0)))}</td></tr>
          <tr><th>Trading halted</th><td>{_bool_text(bool(latest_cycle.get("trading_halted", portfolio_state.get("trading_halted", False))))}</td></tr>
          <tr><th>Last cycle</th><td class="mono">{_escape(str(latest_cycle.get("timestamp", "")))}</td></tr>
        </table>
      </section>

      <section class="panel">
        <h2>Paper Safety</h2>
        <table>
          <tr><th>Mode</th><td>{_escape(str(config["paper_only_mode"]))}</td></tr>
          <tr><th>Live allowed</th><td>{_bool_text(bool(config["allow_live_trading"]))}</td></tr>
          <tr><th>Account</th><td>{_escape(str(config["account_name"]))}</td></tr>
          <tr><th>Universe</th><td>{_escape(", ".join(config["instruments"]))}</td></tr>
          <tr><th>Resolved feedback</th><td>{int(runtime["signal_feedback"]["resolved_signals"])}</td></tr>
          <tr><th>Pending feedback</th><td>{int(runtime["signal_feedback"]["pending_signals"])}</td></tr>
        </table>
      </section>

      <section class="panel">
        <h2>Active Overrides</h2>
        {overrides_html}
        <div class="footer">Rollback guardrail: {_escape(str(effective_runtime["rollback_guardrail"].get("reason", "")))}</div>
      </section>

      <section class="panel">
        <h2>Daily Summary</h2>
        <table>
          <tr><th>Trades</th><td>{int(latest_report_summary.get("trades", 0))}</td></tr>
          <tr><th>Net PnL</th><td>{_fmt_money(float(latest_report_summary.get("net_pnl_rub", 0.0)))}</td></tr>
          <tr><th>Win rate</th><td>{float(latest_report_summary.get("win_rate_pct", 0.0)):.3f}%</td></tr>
          <tr><th>Profit factor</th><td>{float(latest_report_summary.get("profit_factor", 0.0)):.3f}</td></tr>
          <tr><th>Expectancy</th><td>{_fmt_money(float(latest_report_summary.get("expectancy_rub", 0.0)))}</td></tr>
          <tr><th>Report open positions</th><td>{int(latest_report_portfolio.get("open_positions", 0))}</td></tr>
        </table>
      </section>
    </div>

    <div class="grid">
      <section class="panel">
        <h2>Open Positions</h2>
        {positions_html}
      </section>

      <section class="panel">
        <h2>Directional Restrictions</h2>
        <div class="chips">
          <span class="chip">Blocked symbols: {_escape(", ".join(entry_symbols["proposed_blocked_symbols"]) or "-")}</span>
          <span class="chip">Blocked longs: {_escape(", ".join(entry_symbols["proposed_blocked_long_symbols"]) or "-")}</span>
          <span class="chip">Blocked shorts: {_escape(", ".join(entry_symbols["proposed_blocked_short_symbols"]) or "-")}</span>
        </div>
        <div class="footer">{_escape(str(entry_symbols["reason"]))} | source={_escape(str(entry_symbols["evidence_source"]))}</div>
        {direction_rows_html}
      </section>
    </div>

    <div class="grid">
      <section class="panel">
        <h2>Entry Schedule</h2>
        <div class="chips">{_render_chips(entry_schedule.get("proposed_hours", []))}</div>
        <div class="footer">{_escape(str(entry_schedule["reason"]))} | source={_escape(str(entry_schedule["evidence_source"]))}</div>
      </section>

      <section class="panel">
        <h2>Entry Quality</h2>
        <table>
          <tr><th>Changed</th><td>{_bool_text(bool(entry_quality["changed"]))}</td></tr>
          <tr><th>Recommended min strength</th><td>{float(entry_quality["recommended_min_signal_strength"]):.3f}</td></tr>
          <tr><th>Reason</th><td>{_escape(str(entry_quality["reason"]))}</td></tr>
        </table>
      </section>

      <section class="panel">
        <h2>Autonomy Cycle</h2>
        <div class="mono">{_escape("\\n".join(autonomy["nightly_autonomy"]["steps_executed"])) or "No nightly autonomy artifact yet"}</div>
      </section>
    </div>

    <div class="panel" style="margin-top: 16px;">
      <h2>Active Sources</h2>
      {sources_html}
      <div class="footer">
        Config: <span class="mono">{_escape(str(config["config_path"]))}</span><br/>
        Effective: <span class="mono">{_escape(str(config["effective_config_path"]))}</span><br/>
        JSON API: <a href="/api/payload">/api/payload</a> | Health: <a href="/health">/health</a>
      </div>
    </div>
  </div>
</body>
</html>
"""


def serve_dashboard(
    config_path: str | Path,
    *,
    effective_config_path: str | Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8790,
) -> None:
    config_path = str(Path(config_path).resolve())
    effective_path = str(Path(effective_config_path).resolve()) if effective_config_path else None
    server = ThreadingHTTPServer(
        (host, port),
        _handler_factory(config_path, effective_path),
    )
    print(f"Samosbor dashboard listening on http://{host}:{port}")
    server.serve_forever()


def _handler_factory(config_path: str, effective_config_path: str | None):
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._send_response("ok\n", content_type="text/plain; charset=utf-8")
                return

            payload = build_dashboard_payload(
                config_path,
                effective_config_path=effective_config_path,
            )
            if self.path == "/api/payload":
                self._send_response(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    content_type="application/json; charset=utf-8",
                )
                return
            if self.path != "/":
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                return
            self._send_response(
                render_dashboard_html(payload),
                content_type="text/html; charset=utf-8",
            )

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

        def _send_response(self, body: str, *, content_type: str) -> None:
            encoded = body.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return DashboardHandler


def _read_latest_json(root: Path, filename: str) -> dict[str, object]:
    latest_dir = _latest_timestamped_dir(root)
    if latest_dir is None:
        return {}
    return _read_json_file(latest_dir / filename)


def _latest_timestamped_dir(root: Path) -> Path | None:
    if not root.exists():
        return None
    candidates = [path for path in root.iterdir() if path.is_dir()]
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: path.name)[-1]


def _read_json_file(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _positions_from_state(positions_payload: dict[str, Any]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for symbol, position in sorted(positions_payload.items()):
        rows.append(
            {
                "symbol": symbol,
                "direction": str(position.get("direction", "")),
                "quantity_lots": int(position.get("quantity_lots", 0)),
                "entry_price": float(position.get("entry_price", 0.0)),
                "current_price": float(position.get("current_price", 0.0)),
                "stop_price": float(position.get("stop_price", 0.0)),
                "take_profit": float(position.get("take_profit", 0.0)),
                "margin_requirement": float(position.get("margin_requirement", 0.0)),
                "signal_strength": float(position.get("signal_strength", 0.0)),
                "opened_at": str(position.get("opened_at", "")),
                "updated_at": str(position.get("updated_at", "")),
            }
        )
    return rows


def _render_positions(rows: list[dict[str, object]]) -> str:
    if not rows:
        return "<p>Нет открытых paper-позиций.</p>"
    body = "".join(
        [
            "<tr>"
            f"<td>{_escape(str(row['symbol']))}</td>"
            f"<td>{_escape(str(row['direction']))}</td>"
            f"<td>{int(row['quantity_lots'])}</td>"
            f"<td>{float(row['entry_price']):.6f}</td>"
            f"<td>{float(row['current_price']):.6f}</td>"
            f"<td>{float(row['stop_price']):.6f}</td>"
            f"<td>{float(row['take_profit']):.6f}</td>"
            f"<td>{_fmt_money(float(row['margin_requirement']))}</td>"
            "</tr>"
            for row in rows
        ]
    )
    return (
        "<table><tr><th>Symbol</th><th>Dir</th><th>Lots</th><th>Entry</th><th>Current</th>"
        "<th>Stop</th><th>Take</th><th>Margin</th></tr>"
        f"{body}</table>"
    )


def _render_direction_rows(rows: list[dict[str, object]]) -> str:
    if not rows:
        return "<p>Нет direction-level статистики.</p>"
    body = "".join(
        [
            "<tr>"
            f"<td>{_escape(str(row.get('symbol', '')))}</td>"
            f"<td>{_escape(str(row.get('direction', '')))}</td>"
            f"<td>{int(row.get('trades', 0))}</td>"
            f"<td>{float(row.get('win_rate_pct', 0.0)):.3f}%</td>"
            f"<td>{_fmt_money(float(row.get('net_pnl_rub', 0.0)))}</td>"
            f"<td>{float(row.get('profit_factor', 0.0)):.3f}</td>"
            f"<td>{_fmt_money(float(row.get('expectancy_rub', 0.0)))}</td>"
            "</tr>"
            for row in rows
        ]
    )
    return (
        "<table><tr><th>Symbol</th><th>Direction</th><th>Trades</th><th>Win rate</th>"
        "<th>Net PnL</th><th>PF</th><th>Expectancy</th></tr>"
        f"{body}</table>"
    )


def _render_sources(rows: list[dict[str, object]]) -> str:
    if not rows:
        return "<p>Нет active autotune sources.</p>"
    body = "".join(
        [
            "<tr>"
            f"<td>{_escape(str(row.get('source', '')))}</td>"
            f"<td>{_bool_text(bool(row.get('changed', False)))}</td>"
            f"<td>{_escape(json.dumps(row.get('selected_values', {}), ensure_ascii=False))}</td>"
            f"<td>{_escape(str(row.get('activation', {}).get('reason', '')))}</td>"
            "</tr>"
            for row in rows
        ]
    )
    return (
        "<table><tr><th>Source</th><th>Changed</th><th>Selected values</th><th>Activation</th></tr>"
        f"{body}</table>"
    )


def _render_key_values(values: dict[str, object]) -> str:
    if not values:
        return "<p>Активных overrides сейчас нет.</p>"
    body = "".join(
        [
            f"<tr><th>{_escape(str(key))}</th><td class=\"mono\">{_escape(json.dumps(value, ensure_ascii=False))}</td></tr>"
            for key, value in values.items()
        ]
    )
    return f"<table>{body}</table>"


def _render_chips(values: list[object]) -> str:
    if not values:
        return "<span class=\"chip\">-</span>"
    return "".join(f"<span class=\"chip\">{_escape(str(value))}</span>" for value in values)


def _fmt_money(value: float) -> str:
    return f"{value:,.2f} RUB".replace(",", " ")


def _bool_text(value: bool) -> str:
    return "yes" if value else "no"


def _escape(value: str) -> str:
    return html.escape(value, quote=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Samosbor paper dashboard")
    parser.add_argument("--config", required=True, help="Path to the runtime config")
    parser.add_argument(
        "--effective-config",
        help="Optional effective runtime config path for display purposes",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8790, help="Bind port")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    serve_dashboard(
        args.config,
        effective_config_path=args.effective_config,
        host=args.host,
        port=args.port,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
