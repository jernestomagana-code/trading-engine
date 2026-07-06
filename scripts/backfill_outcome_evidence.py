#!/usr/bin/env python3
"""Backfill V32 outcome evidence from local runtime journals."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import outcome_backfill


DEFAULT_AUDIT_OUT = ROOT / "runtime" / "outcome_backfill_audit_latest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair missing outcome evidence from saved runtime data.")
    parser.add_argument("--runtime-dir", default=str(ROOT / "runtime"))
    parser.add_argument("--audit-out", default=str(DEFAULT_AUDIT_OUT))
    parser.add_argument("--write", action="store_true", help="Persist repaired v32_outcomes_journal.json.")
    parser.add_argument("--json-only", action="store_true", help="Print only the JSON report.")
    return parser.parse_args()


def print_summary(payload: dict) -> None:
    print("Stock Ultimus Outcome Evidence Backfill")
    print(f"Version: {payload.get('outcome_backfill_version')} | generated_at={payload.get('generated_at')}")
    print(f"Mode: {'WRITE' if not payload.get('dry_run') else 'DRY-RUN'}")
    print(
        "Outcomes={outcomes} | changed={changed} | complete_after={complete} | unmatched={unmatched}".format(
            outcomes=payload.get("outcome_count"),
            changed=payload.get("changed_count"),
            complete=payload.get("complete_after_count"),
            unmatched=payload.get("unmatched_outcome_count"),
        )
    )
    print(f"Field updates: {payload.get('field_update_counts') or {}}")
    print(f"Unresolved fields: {payload.get('unresolved_field_counts') or {}}")
    print("Manual review only. This report does not authorize orders.")


def main() -> int:
    args = parse_args()
    payload = outcome_backfill.build_backfill_report(
        Path(args.runtime_dir),
        write=args.write,
        audit_out=Path(args.audit_out),
    )
    if args.json_only:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print_summary(payload)
        print(f"Audit JSON: {args.audit_out}")
        if payload.get("dry_run"):
            print("Use --write to persist the repaired outcome journal.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
