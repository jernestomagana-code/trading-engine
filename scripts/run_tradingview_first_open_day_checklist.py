#!/usr/bin/env python3
"""Run the first-open-market-day TradingView checklist."""

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
    parser = argparse.ArgumentParser(description="Check first open-market-day TradingView readiness.")
    parser.add_argument("--runtime-dir", default="runtime")
    parser.add_argument("--coverage", default="config/tradingview_alert_coverage_v1.json")
    parser.add_argument("--output", default="runtime/tradingview_first_open_day_checklist.json")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--market-closed-ok", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = tradingview_operational_health.build_first_open_day_checklist(
        args.runtime_dir,
        coverage_path=args.coverage,
        market_closed_ok=args.market_closed_ok,
    )
    if not args.no_write:
        tradingview_operational_health.write_report(report, args.output)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] in {"READY_FOR_MANUAL_REVIEW", "WAITING_FOR_REAL_MARKET_EVIDENCE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
