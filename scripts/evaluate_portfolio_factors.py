#!/usr/bin/env python3
"""Evaluate advanced factors, history, correlations and Greeks from Control Tower."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import portfolio_factor_engine as factor_engine


def rooted(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control-tower", default="runtime/broker_control_tower_latest.json")
    parser.add_argument("--policy", default="config/portfolio_factor_policy.json")
    parser.add_argument("--json-out", default="runtime/portfolio_factor_latest.json")
    args = parser.parse_args()
    try:
        tower = json.loads(rooted(args.control_tower).read_text(encoding="utf-8"))
        if not isinstance(tower, dict):
            raise ValueError("Control Tower payload must be an object")
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": f"CONTROL_TOWER_LOAD_FAILED:{type(exc).__name__}"}))
        return 1
    result = factor_engine.evaluate(tower, factor_engine.load_policy(rooted(args.policy)))
    factor_engine.write_result(rooted(args.json_out), result)
    print(json.dumps({
        "status": result["status"],
        "history_coverage_ratio": result["history_coverage_ratio"],
        "greeks_coverage_ratio": result["greeks_coverage_ratio"],
        "annualized_volatility": result["historical_risk"]["annualized_volatility"],
        "high_correlation_pair_count": result["high_correlation_pair_count"],
        "warnings": result["warnings"],
        "execution_authorized": False,
        "not_order_instruction": True,
    }, indent=2, sort_keys=True))
    return 0 if result["status"] in {"READY", "PARTIAL"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
