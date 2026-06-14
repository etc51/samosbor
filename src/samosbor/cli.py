from __future__ import annotations

import argparse
import json
import sys

from .config import load_config
from .logging_utils import configure_logging
from .orchestrator import TradingOrchestrator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="samosbor paper-trading system")
    parser.add_argument(
        "--config",
        default="configs/paper.toml",
        help="Path to TOML configuration file",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("accounts", help="List T-Bank accounts visible to the configured token")
    subparsers.add_parser("backtest", help="Run a historical backtest")
    subparsers.add_parser("paper-cycle", help="Run one paper-trading cycle")
    subparsers.add_parser("optimize", help="Search parameter sets and instrument subsets")
    subparsers.add_parser("monte-carlo", help="Run Monte Carlo robustness analysis on a fresh backtest")
    subparsers.add_parser("walk-forward", help="Run rolling walk-forward validation with re-optimization")

    sandbox_parser = subparsers.add_parser("sandbox-init", help="Create/fund a sandbox account")
    sandbox_parser.add_argument("--fund-rub", type=float, default=1_000_000)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config)

    log_path = config.resolve_path(config.reporting.output_dir) / "logs" / "samosbor.log"
    configure_logging(log_path, verbose=args.verbose)
    orchestrator = TradingOrchestrator(config)

    if args.command == "accounts":
        print(json.dumps(orchestrator.list_accounts(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "backtest":
        print(json.dumps(orchestrator.run_backtest(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "paper-cycle":
        print(json.dumps(orchestrator.run_paper_cycle(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "optimize":
        print(json.dumps(orchestrator.optimize_strategy(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "monte-carlo":
        print(json.dumps(orchestrator.run_monte_carlo(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "walk-forward":
        print(json.dumps(orchestrator.run_walk_forward(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "sandbox-init":
        print(
            json.dumps(
                orchestrator.init_sandbox(args.fund_rub),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
