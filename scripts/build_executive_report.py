#!/usr/bin/env python3
"""Build a sanitized Stock Ultimus daily or weekly executive report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import executive_reporting


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", choices=["daily", "weekly"], default="daily")
    parser.add_argument("--runtime", default="runtime")
    args = parser.parse_args()
    runtime = Path(args.runtime)
    if not runtime.is_absolute():
        runtime = ROOT / runtime
    report = executive_reporting.build_report(runtime, args.period)
    paths = executive_reporting.persist_report(runtime, report)
    print(json.dumps({**report, "paths": paths}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
