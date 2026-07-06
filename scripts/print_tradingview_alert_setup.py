#!/usr/bin/env python3
"""Print TradingView alert names and JSON messages from the coverage matrix."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tradingview_alert_coverage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Print TradingView alert setup records.")
    parser.add_argument("--coverage", default=str(tradingview_alert_coverage.DEFAULT_COVERAGE_PATH))
    parser.add_argument("--event-code", help="Print only one event_code.")
    parser.add_argument("--required-only", action="store_true")
    parser.add_argument("--messages-only", action="store_true")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    coverage = tradingview_alert_coverage.load_coverage(args.coverage)
    validation = tradingview_alert_coverage.validate_coverage(coverage)
    if args.validate:
        print(json.dumps(validation, indent=2, sort_keys=True))
        return 0 if validation["valid"] else 1

    if args.event_code:
        alert = tradingview_alert_coverage.alert_by_code(coverage, args.event_code)
        if not alert:
            print(f"Unknown event_code: {args.event_code}", file=sys.stderr)
            return 2
        records = [tradingview_alert_coverage.setup_record(alert, coverage)]
    else:
        records = tradingview_alert_coverage.setup_records(coverage, required_only=args.required_only)

    if args.json:
        print(json.dumps({"coverage_validation": validation, "alerts": records}, indent=2, sort_keys=True))
        return 0 if validation["valid"] else 1

    for index, record in enumerate(records, start=1):
        if args.messages_only:
            print(record["message_json"])
            if index != len(records):
                print()
            continue
        print(f"{index}. {record['alert_name']}")
        print(f"   Symbol: {record['symbol']} | Timeframe: {record['timeframe']}")
        print(f"   Condition hint: {record['condition_hint']}")
        print(f"   Webhook: {record['webhook_url_template']}")
        print("   Message:")
        print(record["message_json"])
        if index != len(records):
            print()
    return 0 if validation["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
