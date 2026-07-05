#!/usr/bin/env python3
"""Run the Stock Ultimus operational evidence gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import operational_evidence_gate


DEFAULT_JSON_OUT = ROOT / "runtime" / "operational_evidence_gate_latest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Stock Ultimus operating mode from evidence.")
    parser.add_argument("--runtime-dir", default=str(ROOT / "runtime"))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--no-write", action="store_true", help="Do not write the latest gate JSON file.")
    parser.add_argument("--no-recovery-preview", action="store_true", help="Skip read-only recovery preview.")
    parser.add_argument("--json-only", action="store_true", help="Print only JSON.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero unless state is outcome or parameter ready.")
    return parser.parse_args()


def print_summary(payload: dict) -> None:
    evidence = payload.get("evidence_summary") or {}
    caps = payload.get("capabilities") or {}
    print("Stock Ultimus Operational Evidence Gate")
    print(f"Version: {payload.get('operational_evidence_gate_version')} | generated_at={payload.get('generated_at')}")
    print(f"State: {payload.get('state')}")
    print(
        "Evidence: source={source}% TV={tv} IBKR={ibkr} complete_outcomes={complete}".format(
            source=evidence.get("source_attribution_coverage_pct"),
            tv=evidence.get("tradingview_event_count"),
            ibkr=evidence.get("ibkr_primary_gap"),
            complete=evidence.get("complete_closed_outcomes"),
        )
    )
    print("Capabilities:")
    for name in [
        "can_collect_signals",
        "can_create_entry_ready",
        "can_evaluate_outcomes",
        "can_review_parameters",
        "can_change_production_rules",
        "can_execute_orders",
    ]:
        item = caps.get(name) or {}
        print(f"- {name}: allowed={item.get('allowed')} blockers={item.get('blockers') or []}")
    print("Next actions:")
    for action in payload.get("next_actions") or []:
        print(f"- {action}")
    print("Manual review only. This gate does not authorize orders.")


def main() -> int:
    args = parse_args()
    payload = operational_evidence_gate.build_operational_evidence_gate(
        Path(args.runtime_dir),
        include_recovery_preview=not args.no_recovery_preview,
    )
    if not args.no_write:
        out = Path(args.json_out)
        operational_evidence_gate.write_json(out, payload)
    if args.json_only:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print_summary(payload)
        if not args.no_write:
            print(f"JSON: {args.json_out}")
    if args.strict and payload.get("state") not in {"OUTCOME_COLLECTION_READY", "PARAMETER_REVIEW_READY"}:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
