#!/usr/bin/env python3
"""Print TradingView setup records for options-underlying alerts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.print_tradingview_alert_setup as base_setup


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    if "--coverage" not in argv:
        argv = ["--coverage", "config/tradingview_options_underlying_alert_coverage_v1.json"] + argv
    return base_setup.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
