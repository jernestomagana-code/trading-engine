#!/usr/bin/env python3
"""Evaluate read-only multi-account stress scenarios from Control Tower data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import portfolio_stress_engine as stress_engine


def rooted(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control-tower", default="runtime/broker_control_tower_latest.json")
    parser.add_argument("--policy", default="config/portfolio_stress_policy.json")
    parser.add_argument("--json-out", default="runtime/portfolio_stress_latest.json")
    args = parser.parse_args()
    try:
        tower = json.loads(rooted(args.control_tower).read_text(encoding="utf-8"))
        if not isinstance(tower, dict):
            raise ValueError("Control Tower payload must be an object")
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": f"CONTROL_TOWER_LOAD_FAILED:{type(exc).__name__}"}))
        return 1
    result = stress_engine.evaluate(tower, stress_engine.load_policy(rooted(args.policy)))
    stress_engine.write_result(rooted(args.json_out), result)
    print(json.dumps({
        "status": result["status"],
        "scenario_count": result["scenario_count"],
        "worst_scenario_id": result["worst_scenario_id"],
        "worst_loss_nav_ratio": result["worst_loss_nav_ratio"],
        "valuation_coverage_ratio": result["valuation_coverage_ratio"],
        "warnings": result["warnings"],
        "execution_authorized": False,
        "not_order_instruction": True,
    }, indent=2, sort_keys=True))
    return 0 if result["status"] in {"READY", "PARTIAL"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
