#!/usr/bin/env python3
"""Run a Stock Ultimus post-open monitor cycle."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import operator_readiness


DEFAULT_OUT = ROOT / "runtime" / "post_open_monitor_latest.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Stock Ultimus post-open monitor.")
    parser.add_argument("--runtime-dir", default=str(ROOT / "runtime"))
    parser.add_argument("--json-out", default=str(DEFAULT_OUT))
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--market-closed-ok", action="store_true")
    parser.add_argument("--json-only", action="store_true")
    parser.add_argument("--watch", action="store_true", help="Repeat monitor cycles.")
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--cycles", type=int, default=1, help="Number of cycles in watch mode; 0 means forever.")
    return parser


def print_human(report: dict) -> None:
    print("Stock Ultimus Post Open Monitor")
    print(f"Nivel: {report.get('alert_level')} | status={report.get('status')}")
    print(f"Siguiente accion: {report.get('next_required_action')}")
    for finding in report.get("findings") or []:
        print(f"- {finding.get('severity')} {finding.get('code')}: {finding.get('detail')}")
    if not report.get("findings"):
        print("- OK: sin hallazgos operativos.")
    print("Guardrail: no order execution; manual review only.")


def write_report(report: dict, path: str) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")


def run_once(args: argparse.Namespace) -> dict:
    report = operator_readiness.build_post_open_monitor(
        args.runtime_dir,
        market_closed_ok=args.market_closed_ok,
    )
    if not args.no_write:
        write_report(report, args.json_out)
    if args.json_only:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        print_human(report)
    return report


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cycles = 1 if not args.watch else max(0, int(args.cycles or 0))
    completed = 0
    last_report = {}
    while True:
        last_report = run_once(args)
        completed += 1
        if not args.watch:
            break
        if cycles and completed >= cycles:
            break
        time.sleep(max(10, int(args.interval_seconds or 300)))
    return 1 if last_report.get("alert_level") == "ACTION" else 0


if __name__ == "__main__":
    raise SystemExit(main())
