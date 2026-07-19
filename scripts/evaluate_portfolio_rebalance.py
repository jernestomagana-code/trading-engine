#!/usr/bin/env python3
"""Generate virtual-only portfolio rebalance comparisons from sanitized data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import portfolio_factor_engine as factor_engine
import portfolio_rebalance_engine as rebalance_engine
import portfolio_stress_engine as stress_engine


def rooted(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control-tower", default="runtime/broker_control_tower_latest.json")
    parser.add_argument("--policy", default="config/portfolio_rebalance_policy.json")
    parser.add_argument("--stress-policy", default="config/portfolio_stress_policy.json")
    parser.add_argument("--factor-policy", default="config/portfolio_factor_policy.json")
    parser.add_argument("--json-out", default="runtime/portfolio_rebalance_latest.json")
    parser.add_argument("--ticker", default="")
    parser.add_argument("--reduction-pct", type=float)
    args = parser.parse_args()
    try:
        tower = json.loads(rooted(args.control_tower).read_text(encoding="utf-8"))
        if not isinstance(tower, dict):
            raise ValueError("Control Tower payload must be an object")
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": f"CONTROL_TOWER_LOAD_FAILED:{type(exc).__name__}"}))
        return 1
    result = rebalance_engine.evaluate(
        tower,
        rebalance_engine.load_policy(rooted(args.policy)),
        stress_engine.load_policy(rooted(args.stress_policy)),
        factor_engine.load_policy(rooted(args.factor_policy)),
        custom_ticker=args.ticker,
        custom_reduction_pct=args.reduction_pct,
    )
    rebalance_engine.write_result(rooted(args.json_out), result)
    print(json.dumps({
        "status": result["status"],
        "candidate_count": result["candidate_count"],
        "preferred_simulation_id": result["preferred_simulation_id"],
        "custom_ticker": str(args.ticker or "").upper(),
        "simulation_only": True,
        "orders_created": 0,
        "execution_authorized": False,
        "not_order_instruction": True,
    }, indent=2, sort_keys=True))
    return 0 if result["status"] in {"READY", "NO_CHANGE_NEEDED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
