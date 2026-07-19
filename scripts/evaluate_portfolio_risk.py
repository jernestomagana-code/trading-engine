#!/usr/bin/env python3
"""Evaluate sanitized multi-account portfolio risk without placing orders."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import portfolio_risk_engine as risk_engine
import portfolio_risk_store as risk_store


def rooted_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", default="runtime")
    parser.add_argument("--control-tower", default="runtime/broker_control_tower_latest.json")
    parser.add_argument("--policy", default="config/portfolio_risk_policy.json")
    parser.add_argument("--json-out", default="runtime/portfolio_risk_latest.json")
    parser.add_argument("--history-out", default="runtime/portfolio_risk_history.json")
    parser.add_argument("--strict-exit", action="store_true", help="Return a non-zero exit code for domain risk states.")
    args = parser.parse_args()

    try:
        tower = json.loads(rooted_path(args.control_tower).read_text(encoding="utf-8"))
        if not isinstance(tower, dict):
            raise ValueError("Control Tower payload must be a JSON object")
    except Exception as exc:
        tower = {
            "status": "WAIT_ACCOUNT_REFRESH",
            "accounts": [],
            "consolidated_capacity": {},
            "warnings": [f"CONTROL_TOWER_LOAD_FAILED:{type(exc).__name__}"],
        }
    policy = risk_engine.load_policy(rooted_path(args.policy))
    evaluation = risk_engine.evaluate(tower, policy)
    persistence = risk_store.persist_evaluation(
        rooted_path(args.runtime_dir),
        evaluation,
        latest_path=rooted_path(args.json_out),
        history_path=rooted_path(args.history_out),
    )
    print(json.dumps({
        "status": evaluation.get("status"),
        "decision_support": evaluation.get("decision_support"),
        "risk_score": evaluation.get("risk_score"),
        "highest_severity": evaluation.get("highest_severity"),
        "alert_count": evaluation.get("alert_count"),
        "alert_counts": evaluation.get("alert_counts"),
        "new_event_count": persistence.get("new_event_count"),
        "sensitive_identifiers_excluded": True,
        "execution_authorized": False,
        "automatic_liquidation_authorized": False,
        "not_order_instruction": True,
    }, indent=2, sort_keys=True))
    if args.strict_exit:
        return 2 if evaluation.get("status") == "BLOCKED" else 1 if evaluation.get("status") == "ACTION_REQUIRED" else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
