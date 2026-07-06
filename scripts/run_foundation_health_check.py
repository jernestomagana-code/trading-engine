#!/usr/bin/env python3
"""Generate the offline Stock Ultimus foundation health report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import foundation_health


DEFAULT_JSON_OUT = ROOT / "runtime" / "foundation_health_latest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Stock Ultimus foundation health.")
    parser.add_argument("--runtime-dir", default=str(ROOT / "runtime"))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--strict", action="store_true", help="Return non-zero when the report status is FAIL.")
    parser.add_argument("--no-write", action="store_true", help="Do not write the latest health JSON file.")
    parser.add_argument("--json-only", action="store_true", help="Print only the JSON payload.")
    return parser.parse_args()


def print_summary(payload: dict) -> None:
    print("Stock Ultimus Foundation Health")
    print(f"Version: {payload.get('foundation_health_version')} | generated_at={payload.get('generated_at')}")
    print(f"Status: {payload.get('status')}")
    print("\nChecks:")
    for item in payload.get("checks") or []:
        print(f"- {item.get('name')}: {item.get('status')} | {item.get('detail')}")
    print("\nPriorities:")
    for item in payload.get("priorities") or []:
        print(f"- {item}")
    print("\nManual review only. This report does not authorize orders.")


def main() -> int:
    args = parse_args()
    payload = foundation_health.build_foundation_health(Path(args.runtime_dir))
    out = Path(args.json_out)
    if not args.no_write:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    if args.json_only:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print_summary(payload)
        if not args.no_write:
            print(f"\nJSON: {out}")
    return 1 if args.strict and payload.get("status") == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
