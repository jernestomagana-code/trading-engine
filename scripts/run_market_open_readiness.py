#!/usr/bin/env python3
"""Build the Stock Ultimus market-open go/no-go report and checklist."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import operator_readiness


DEFAULT_OUT = ROOT / "runtime" / "market_open_readiness_latest.json"
DEFAULT_CHECKLIST_OUT = ROOT / "runtime" / "market_open_checklist_latest.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Stock Ultimus market-open readiness.")
    parser.add_argument("--runtime-dir", default=str(ROOT / "runtime"))
    parser.add_argument("--json-out", default=str(DEFAULT_OUT))
    parser.add_argument("--checklist-out", default=str(DEFAULT_CHECKLIST_OUT))
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--market-closed-ok", action="store_true")
    parser.add_argument("--json-only", action="store_true")
    return parser


def print_human(report: dict, checklist: dict) -> None:
    print("Stock Ultimus Market Open Readiness")
    print(f"Estado: {report.get('status')} | ok={report.get('ok')}")
    print(f"Siguiente accion: {report.get('next_required_action')}")
    tv = report.get("tradingview_bundle") or {}
    print(
        "TradingView: coverage={coverage} e2e={e2e} received={received}/{required} quarantine={quarantine}".format(
            coverage=tv.get("coverage_valid"),
            e2e=tv.get("real_e2e_confirmed"),
            received=tv.get("total_received_required_event_count"),
            required=tv.get("total_required_alert_count"),
            quarantine=tv.get("total_quarantine_event_count"),
        )
    )
    print(f"IBKR: {report.get('ibkr_primary_gap')}")
    print(f"Foundation: {report.get('foundation_status')} | Gate: {report.get('operational_gate_state')}")
    print("\nChecklist:")
    for step in checklist.get("steps") or []:
        print(f"- {step.get('name')}: {step.get('status')} | {step.get('command')}")
    print("\nGuardrail: decision-support only; execution_authorized=false; not_order_instruction=true.")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = operator_readiness.build_go_no_go(
        args.runtime_dir,
        market_closed_ok=args.market_closed_ok,
    )
    checklist = operator_readiness.build_market_open_checklist(
        args.runtime_dir,
        generated_at=report["generated_at"],
        market_closed_ok=args.market_closed_ok,
    )
    if not args.no_write:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
        checklist_out = Path(args.checklist_out)
        checklist_out.parent.mkdir(parents=True, exist_ok=True)
        checklist_out.write_text(json.dumps(checklist, indent=2, sort_keys=True, default=str) + "\n")
    if args.json_only:
        print(json.dumps({"readiness": report, "checklist": checklist}, indent=2, sort_keys=True, default=str))
    else:
        print_human(report, checklist)
    return 0 if report.get("ok") or report.get("status") in {"WAITING_TV", "WAITING_IBKR"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
