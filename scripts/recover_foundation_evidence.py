#!/usr/bin/env python3
"""Recover Stock Ultimus foundation evidence from local runtime files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import foundation_evidence_recovery


DEFAULT_AUDIT_OUT = ROOT / "runtime" / "foundation_evidence_recovery_latest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recover source, IBKR, TV, and outcome evidence as one block.")
    parser.add_argument("--runtime-dir", default=str(ROOT / "runtime"))
    parser.add_argument("--audit-out", default=str(DEFAULT_AUDIT_OUT))
    parser.add_argument("--write", action="store_true", help="Persist repaired runtime evidence files.")
    parser.add_argument("--json-only", action="store_true", help="Print only the JSON recovery report.")
    return parser.parse_args()


def print_summary(payload: dict) -> None:
    source = payload.get("source_attribution_backfill") or {}
    ibkr = payload.get("ibkr_diagnostics_recovery") or {}
    tv = payload.get("tradingview_ledger_replay") or {}
    outcome = payload.get("outcome_backfill") or {}
    health = payload.get("foundation_health") or {}
    readiness = payload.get("collection_readiness") or {}
    print("Stock Ultimus Foundation Evidence Recovery")
    print(f"Version: {payload.get('recovery_version')} | generated_at={payload.get('generated_at')}")
    print(f"Mode: {'WRITE' if not payload.get('dry_run') else 'DRY-RUN'}")
    print(f"Source attribution: decisions_changed={source.get('changed_count')} fields={source.get('field_update_counts') or {}}")
    print(f"IBKR diagnostics: rows={ibkr.get('option_row_count')} gap={ibkr.get('primary_gap')}")
    print(f"TradingView ledger: replayable={tv.get('replayable_payload_count')} existing={tv.get('existing_event_count')}")
    print(
        "Outcomes: changed={changed} complete_after={complete} unresolved={unresolved}".format(
            changed=outcome.get("changed_count"),
            complete=outcome.get("complete_after_count"),
            unresolved=outcome.get("unresolved_field_counts") or {},
        )
    )
    print(f"Foundation Health: {health.get('status')}")
    print(f"Collection readiness: {readiness.get('status')} blockers={readiness.get('blockers') or []}")
    print("Manual review only. This report does not authorize orders.")


def main() -> int:
    args = parse_args()
    payload = foundation_evidence_recovery.recover_foundation_evidence(
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
            print("Use --write to persist recovered runtime evidence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
