#!/usr/bin/env python3
"""Build one TradingView health report across futures and options-underlying alerts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tradingview_operational_health


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check combined TradingView alert health.")
    parser.add_argument("--runtime-dir", default="runtime")
    parser.add_argument("--output", default="runtime/tradingview_alert_bundle_health.json")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--market-closed-ok", action="store_true")
    parser.add_argument(
        "--local-replay-validation",
        action="store_true",
        help="Validate each coverage contract locally without writing synthetic runtime events.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = tradingview_operational_health.build_alert_bundle_health(
        args.runtime_dir,
        market_closed_ok=args.market_closed_ok,
        allow_local_replay_validation=args.local_replay_validation,
    )
    if not args.no_write:
        tradingview_operational_health.write_report(report, args.output)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["coverage_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
