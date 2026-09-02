#!/usr/bin/env python3
"""Build the local premium-strategy research data readiness report."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import premium_strategy_data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-dir", default=os.getenv("STOCK_ULTIMUS_RUNTIME_DIR", str(ROOT / "runtime")))
    parser.add_argument("--output")
    parser.add_argument("--capture-live", action="store_true", help="Preserve usable quotes already present in local Runtime")
    args = parser.parse_args()
    runtime_dir = Path(args.runtime_dir)
    capture = premium_strategy_data.capture_runtime_observations(runtime_dir) if args.capture_live else None
    report = premium_strategy_data.write_readiness(runtime_dir, Path(args.output) if args.output else None)
    if capture is not None:
        report["capture"] = capture
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
