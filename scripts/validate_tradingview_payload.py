#!/usr/bin/env python3
"""Validate a TradingView payload against the Stock Ultimus contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tradingview_payload_contract
import tradingview_signal_ledger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a TradingView alert payload.")
    parser.add_argument("--payload", help="Path to a JSON payload file.")
    parser.add_argument("--sample", action="store_true", help="Validate the built-in concrete sample.")
    parser.add_argument("--template", action="store_true", help="Print the TradingView placeholder template.")
    parser.add_argument("--append-ledger", action="store_true", help="Append the payload to the local signal ledger if valid.")
    parser.add_argument("--ledger-path", default=str(ROOT / "runtime" / "v32_signal_events.json"))
    parser.add_argument("--endpoint", default="/technical_snapshot")
    parser.add_argument("--no-placeholders", action="store_true", help="Fail template-style {{placeholders}}.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when invalid.")
    parser.add_argument("--json-only", action="store_true", help="Print only JSON.")
    return parser.parse_args()


def load_payload(args: argparse.Namespace) -> dict:
    if args.template:
        return tradingview_payload_contract.tradingview_placeholder_template()
    if args.sample or not args.payload:
        return tradingview_payload_contract.sample_payload()
    path = Path(args.payload)
    return json.loads(path.read_text())


def print_summary(payload: dict) -> None:
    print("Stock Ultimus TradingView Payload Validator")
    print(f"Version: {payload.get('payload_contract_version')} | valid={payload.get('valid')}")
    print(f"Completeness: {payload.get('context_completeness_pct')}%")
    print(f"Missing: {payload.get('missing_fields') or []}")
    print(f"Invalid numeric: {payload.get('invalid_numeric_fields') or []}")
    print(f"Warnings: {payload.get('warnings') or []}")
    if payload.get("ledger_append"):
        append = payload.get("ledger_append") or {}
        print(f"Ledger: {append.get('status')} event_id={append.get('event_id')} count={append.get('event_count')}")
    print("Manual review only. This validator does not authorize orders.")


def main() -> int:
    args = parse_args()
    payload = load_payload(args)
    result = tradingview_payload_contract.validate_payload(
        payload,
        allow_placeholders=not args.no_placeholders,
    )
    if args.append_ledger and result.get("valid"):
        result["ledger_append"] = tradingview_signal_ledger.append_signal_event(
            payload,
            raw_text=json.dumps(payload, sort_keys=True, default=str),
            endpoint=args.endpoint,
            path=args.ledger_path,
        )
    if args.template and not args.json_only:
        print("TradingView alert message template:")
        print(tradingview_payload_contract.dumps_template())
        print()
    if args.json_only:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    else:
        print_summary(result)
    if args.strict and not result.get("valid"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
