#!/usr/bin/env python3
"""Refresh every configured IBKR account sequentially in read-only mode."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import broker_control_tower as control_tower
import portfolio_risk_engine as risk_engine
import portfolio_risk_store as risk_store
import portfolio_stress_engine as stress_engine
import portfolio_factor_engine as factor_engine
import portfolio_rebalance_engine as rebalance_engine
from brokers.ibkr_readonly import IBKRReadOnlyAdapter
from scripts import ibkr_account_profile as profiles


def rooted_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7496)
    parser.add_argument("--client-id", type=int, default=84)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--max-age-minutes", type=float, default=15)
    parser.add_argument("--runtime-dir", default="runtime")
    parser.add_argument("--profiles-file", default="runtime/ibkr_account_profiles.local.json")
    parser.add_argument("--active-file", default="runtime/ibkr_account_active_profile.json")
    parser.add_argument("--json-out", default="runtime/broker_control_tower_latest.json")
    parser.add_argument("--risk-policy", default="config/portfolio_risk_policy.json")
    parser.add_argument("--risk-json-out", default="runtime/portfolio_risk_latest.json")
    parser.add_argument("--risk-history-out", default="runtime/portfolio_risk_history.json")
    parser.add_argument("--stress-policy", default="config/portfolio_stress_policy.json")
    parser.add_argument("--stress-json-out", default="runtime/portfolio_stress_latest.json")
    parser.add_argument("--factor-policy", default="config/portfolio_factor_policy.json")
    parser.add_argument("--factor-json-out", default="runtime/portfolio_factor_latest.json")
    parser.add_argument("--rebalance-policy", default="config/portfolio_rebalance_policy.json")
    parser.add_argument("--rebalance-json-out", default="runtime/portfolio_rebalance_latest.json")
    parser.add_argument("--skip-risk-evaluation", action="store_true")
    parser.add_argument("--skip-stress-evaluation", action="store_true")
    parser.add_argument("--skip-factor-evaluation", action="store_true")
    parser.add_argument("--skip-rebalance-evaluation", action="store_true")
    args = parser.parse_args()

    runtime_dir = rooted_path(args.runtime_dir)
    try:
        profile_data = json.loads(rooted_path(args.profiles_file).read_text(encoding="utf-8"))
    except Exception:
        profile_data = {"profiles": {}}
    profile_map = profile_data.get("profiles") if isinstance(profile_data.get("profiles"), dict) else {}
    try:
        active = json.loads(rooted_path(args.active_file).read_text(encoding="utf-8"))
    except Exception:
        active = {}
    ready = {}
    account_refs = []
    for raw_alias, profile in sorted(profile_map.items()):
        if not isinstance(profile, dict):
            continue
        alias = profiles.normalize_alias(profile.get("alias") or raw_alias)
        account_id = profiles.read_keychain_value(str(profile.get("keychain_service") or profiles.keychain_service(alias)), timeout=10)
        ready[alias] = bool(account_id)
        if account_id:
            account_refs.append({
                "account_alias": alias,
                "account_scope": profiles.normalize_alias(profile.get("account_scope") or alias),
                "account_id": account_id,
            })

    registry = control_tower.build_registry(profile_map, active.get("account_alias") or "", ready)
    adapter = IBKRReadOnlyAdapter(args.host, args.port, args.client_id, args.timeout)
    collected = adapter.collect(account_refs) if account_refs else {}
    for account in registry.get("accounts") or []:
        alias = account["account_alias"]
        snapshot = collected.get(alias)
        if not isinstance(snapshot, dict):
            snapshot = control_tower.account_snapshot(
                broker=account["broker"],
                alias=alias,
                scope=account["account_scope"],
                status="KEYCHAIN_ACCOUNT_MISSING",
                error="Broker account reference is not configured in Keychain.",
            )
        control_tower.write_snapshot(runtime_dir, snapshot)

    snapshots = control_tower.load_snapshots(runtime_dir, registry)
    payload = control_tower.consolidate(registry, snapshots, max_age_minutes=args.max_age_minutes)
    output_path = rooted_path(args.json_out)
    control_tower.write_control_tower(output_path, payload)
    risk_evaluation = {}
    risk_persistence = {}
    if not args.skip_risk_evaluation:
        policy = risk_engine.load_policy(rooted_path(args.risk_policy))
        risk_evaluation = risk_engine.evaluate(payload, policy)
        risk_persistence = risk_store.persist_evaluation(
            runtime_dir,
            risk_evaluation,
            latest_path=rooted_path(args.risk_json_out),
            history_path=rooted_path(args.risk_history_out),
        )
    stress_evaluation = {}
    if not args.skip_stress_evaluation:
        stress_policy = stress_engine.load_policy(rooted_path(args.stress_policy))
        stress_evaluation = stress_engine.evaluate(payload, stress_policy)
        stress_engine.write_result(rooted_path(args.stress_json_out), stress_evaluation)
    factor_evaluation = {}
    if not args.skip_factor_evaluation:
        factor_policy = factor_engine.load_policy(rooted_path(args.factor_policy))
        factor_evaluation = factor_engine.evaluate(payload, factor_policy)
        factor_engine.write_result(rooted_path(args.factor_json_out), factor_evaluation)
    rebalance_evaluation = {}
    if not args.skip_rebalance_evaluation:
        rebalance_evaluation = rebalance_engine.evaluate(
            payload,
            rebalance_engine.load_policy(rooted_path(args.rebalance_policy)),
            stress_engine.load_policy(rooted_path(args.stress_policy)),
            factor_engine.load_policy(rooted_path(args.factor_policy)),
        )
        rebalance_engine.write_result(rooted_path(args.rebalance_json_out), rebalance_evaluation)
    print(json.dumps({
        "status": payload.get("status"),
        "account_count": payload.get("account_count"),
        "ready_account_count": payload.get("ready_account_count"),
        "stale_account_count": payload.get("stale_account_count"),
        "failed_account_count": payload.get("failed_account_count"),
        "warnings": payload.get("warnings"),
        "output": args.json_out,
        "risk_status": risk_evaluation.get("status") or "SKIPPED",
        "risk_score": risk_evaluation.get("risk_score"),
        "risk_alert_count": risk_evaluation.get("alert_count", 0),
        "risk_new_event_count": risk_persistence.get("new_event_count", 0),
        "stress_status": stress_evaluation.get("status") or "SKIPPED",
        "stress_worst_scenario_id": stress_evaluation.get("worst_scenario_id"),
        "stress_worst_loss_nav_ratio": stress_evaluation.get("worst_loss_nav_ratio"),
        "factor_status": factor_evaluation.get("status") or "SKIPPED",
        "factor_history_coverage_ratio": factor_evaluation.get("history_coverage_ratio"),
        "factor_greeks_coverage_ratio": factor_evaluation.get("greeks_coverage_ratio"),
        "rebalance_status": rebalance_evaluation.get("status") or "SKIPPED",
        "rebalance_candidate_count": rebalance_evaluation.get("candidate_count", 0),
        "rebalance_preferred_simulation_id": rebalance_evaluation.get("preferred_simulation_id"),
        "sensitive_identifiers_excluded": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }, indent=2, sort_keys=True))
    return 0 if payload.get("status") == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
