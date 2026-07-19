#!/usr/bin/env python3
"""Run Stock Ultimus preventive maintenance checks without deleting or restarting."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import preventive_maintenance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", default="runtime")
    args = parser.parse_args()
    runtime = Path(args.runtime)
    if not runtime.is_absolute():
        runtime = ROOT / runtime
    report = preventive_maintenance.build_maintenance_report(runtime)
    preventive_maintenance.persist_report(runtime, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["status"] == "ACTION_REQUIRED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
