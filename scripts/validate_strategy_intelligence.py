#!/usr/bin/env python3
"""Validate Strategy Intelligence registry and Morgan research notes."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "strategy_registry.json"
NOTES_DIR = ROOT / "docs" / "strategy_research_notes"
FRESHNESS_FIXTURES = ROOT / "fixtures" / "strategy_intelligence" / "freshness_cases.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import strategy_intelligence

ALLOWED_STATES = {"ENABLED", "RADAR_ONLY", "DISABLED"}
ALLOWED_STAGES = {
    "OBSERVED_PRACTICE",
    "RESEARCH_HYPOTHESIS",
    "RADAR_ONLY",
    "FORWARD_TEST",
    "RULE_PROPOSAL",
    "REVIEWED_RULE",
    "PRODUCTION_PLAYBOOK",
}
ALLOWED_TIME_HORIZONS = {"INTRADAY", "NON_INTRADAY"}
ALLOWED_ENTRY_CAPS = {
    "MANUAL_REVIEW_ONLY",
    "FILTER_ONLY",
    "RADAR_ONLY_RESEARCH_ONLY",
    "RADAR_ONLY_UNTIL_CASH_RESERVE_GATE_IMPLEMENTED",
    "RADAR_ONLY_UNTIL_MULTI_LEG_CONTRACT_AND_EXIT_PLAN_ARE_CANONICAL",
    "RADAR_ONLY_UNTIL_INTRADAY_GOVERNANCE_IMPLEMENTED",
}
REQUIRED_STRATEGIES = {
    "NAKED_PUT",
    "CASH_SECURED_PUT",
    "COVERED_CALL",
    "IRON_CONDOR",
    "FUTURES_INTRADAY",
    "ZERO_DTE_INDEX_OPTIONS",
    "CANSLIM_FILTER",
}
FORBIDDEN_ACTION_WORDS = {
    "place_order",
    "submit_order",
    "auto_execute",
    "automatic_execution",
    "copy_trade",
}


def load_json(path: Path) -> tuple[object | None, list[str]]:
    try:
        return json.loads(path.read_text()), []
    except FileNotFoundError:
        return None, [f"missing file: {path.relative_to(ROOT)}"]
    except json.JSONDecodeError as exc:
        return None, [f"{path.relative_to(ROOT)} invalid JSON: {exc}"]


def text_contains_forbidden_action(value: object) -> list[str]:
    text = json.dumps(value, sort_keys=True).lower()
    hits = sorted(word for word in FORBIDDEN_ACTION_WORDS if word in text)
    return hits


def require_string(obj: dict, field: str, errors: list[str], path: str) -> None:
    value = obj.get(field)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path}.{field} must be a non-empty string")


def require_string_list(obj: dict, field: str, errors: list[str], path: str) -> None:
    value = obj.get(field)
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        errors.append(f"{path}.{field} must be a list of non-empty strings")


def validate_registry() -> list[str]:
    data, errors = load_json(REGISTRY)
    if errors:
        return errors
    if not isinstance(data, dict):
        return ["config/strategy_registry.json root must be an object"]

    for field in ["registry_version", "playbook_version", "intelligence_loop_version", "updated_at"]:
        require_string(data, field, errors, "registry")

    governance = data.get("governance")
    if not isinstance(governance, dict):
        errors.append("registry.governance must be an object")
    else:
        if governance.get("automatic_order_execution_allowed") is not False:
            errors.append("registry.governance.automatic_order_execution_allowed must be false")
        if governance.get("research_to_rule_required") is not True:
            errors.append("registry.governance.research_to_rule_required must be true")

    strategies = data.get("strategies")
    if not isinstance(strategies, list) or not strategies:
        errors.append("registry.strategies must be a non-empty list")
        return errors

    seen: set[str] = set()
    for index, strategy in enumerate(strategies):
        path = f"registry.strategies[{index}]"
        if not isinstance(strategy, dict):
            errors.append(f"{path} must be an object")
            continue

        for field in ["strategy", "family", "time_horizon", "state", "strategy_version", "ruleset_version", "entry_ready_cap", "research_stage", "notes"]:
            require_string(strategy, field, errors, path)

        name = strategy.get("strategy")
        if isinstance(name, str):
            if not re.fullmatch(r"[A-Z0-9_]{3,40}", name):
                errors.append(f"{path}.strategy must be uppercase snake case")
            if name in seen:
                errors.append(f"duplicate strategy: {name}")
            seen.add(name)

        if strategy.get("state") not in ALLOWED_STATES:
            errors.append(f"{path}.state must be one of {sorted(ALLOWED_STATES)}")
        if strategy.get("research_stage") not in ALLOWED_STAGES:
            errors.append(f"{path}.research_stage must be one of {sorted(ALLOWED_STAGES)}")
        if strategy.get("time_horizon") not in ALLOWED_TIME_HORIZONS:
            errors.append(f"{path}.time_horizon must be one of {sorted(ALLOWED_TIME_HORIZONS)}")
        if strategy.get("entry_ready_cap") not in ALLOWED_ENTRY_CAPS:
            errors.append(f"{path}.entry_ready_cap must be one of {sorted(ALLOWED_ENTRY_CAPS)}")

        require_string_list(strategy, "required_inputs", errors, path)
        require_string_list(strategy, "must_block_on_missing", errors, path)

        state = strategy.get("state")
        cap = strategy.get("entry_ready_cap")
        if state == "RADAR_ONLY" and isinstance(cap, str) and not cap.startswith("RADAR_ONLY"):
            errors.append(f"{path} RADAR_ONLY strategy must have a RADAR_ONLY entry_ready_cap")
        if state == "ENABLED" and cap not in {"MANUAL_REVIEW_ONLY", "FILTER_ONLY"}:
            errors.append(f"{path} ENABLED strategy must remain manual-review or filter-only capped")

    missing = sorted(REQUIRED_STRATEGIES - seen)
    if missing:
        errors.append(f"registry missing required strategies: {missing}")

    forbidden = text_contains_forbidden_action(data)
    if forbidden:
        errors.append(f"registry contains forbidden action words: {forbidden}")

    return errors


def validate_research_note(path: Path) -> list[str]:
    data, errors = load_json(path)
    rel = path.relative_to(ROOT)
    if errors:
        return errors
    if not isinstance(data, dict):
        return [f"{rel} root must be an object"]

    for field in ["note_version", "created_at", "owner", "status", "summary"]:
        require_string(data, field, errors, str(rel))

    hypotheses = data.get("hypotheses")
    if not isinstance(hypotheses, list) or not hypotheses:
        errors.append(f"{rel}.hypotheses must be a non-empty list")
        return errors

    ids: set[str] = set()
    for index, hypothesis in enumerate(hypotheses):
        hpath = f"{rel}.hypotheses[{index}]"
        if not isinstance(hypothesis, dict):
            errors.append(f"{hpath} must be an object")
            continue

        for field in [
            "id",
            "stage",
            "strategy",
            "time_horizon",
            "observed_practice",
            "hypothesis",
            "blocked_from_entry_ready_until",
        ]:
            require_string(hypothesis, field, errors, hpath)

        hid = hypothesis.get("id")
        if isinstance(hid, str):
            if hid in ids:
                errors.append(f"{hpath}.id duplicates {hid}")
            ids.add(hid)

        if hypothesis.get("stage") not in ALLOWED_STAGES:
            errors.append(f"{hpath}.stage must be one of {sorted(ALLOWED_STAGES)}")
        if hypothesis.get("time_horizon") not in ALLOWED_TIME_HORIZONS:
            errors.append(f"{hpath}.time_horizon must be one of {sorted(ALLOWED_TIME_HORIZONS)}")

        require_string_list(hypothesis, "required_data", errors, hpath)
        require_string_list(hypothesis, "promotion_requirements", errors, hpath)

    forbidden = text_contains_forbidden_action(data)
    if forbidden:
        errors.append(f"{rel} contains forbidden action words: {forbidden}")

    return errors


def validate_research_notes() -> list[str]:
    if not NOTES_DIR.exists():
        return [f"missing research notes directory: {NOTES_DIR.relative_to(ROOT)}"]

    paths = sorted(NOTES_DIR.glob("*.json"))
    if not paths:
        return [f"missing Morgan research notes in {NOTES_DIR.relative_to(ROOT)}"]

    errors: list[str] = []
    for path in paths:
        errors.extend(validate_research_note(path))
    return errors


def timestamp_from_offset(now: datetime, offset_minutes: object) -> str | None:
    if offset_minutes is None:
        return None
    if not isinstance(offset_minutes, (int, float)) or isinstance(offset_minutes, bool):
        raise ValueError(f"offset must be numeric minutes, got {offset_minutes!r}")
    return (now + timedelta(minutes=float(offset_minutes))).isoformat()


def build_freshness_decision(offsets: dict, now: datetime) -> dict:
    ibkr_ts = timestamp_from_offset(now, offsets.get("ibkr_snapshot"))
    technical_ts = timestamp_from_offset(now, offsets.get("technical"))
    market_ts = timestamp_from_offset(now, offsets.get("market_regime"))
    canslim_ts = timestamp_from_offset(now, offsets.get("fundamental_canslim"))
    account_ts = timestamp_from_offset(now, offsets.get("account_context"))

    source_context = {
        "context_version": "source_context_timestamps_v1",
        "ibkr_snapshot": {
            "timestamp": ibkr_ts,
            "available": bool(ibkr_ts),
        },
        "fundamental_canslim": {
            "timestamp": canslim_ts,
            "available": bool(canslim_ts),
            "sensitive_values_excluded": True,
        },
        "account_context": {
            "timestamp": account_ts,
            "available": bool(account_ts),
            "sensitive_values_excluded": True,
        },
    }

    return {
        "ticker": "AAPL",
        "strategy": "NAKED_PUT",
        "snapshot_received_at": ibkr_ts,
        "snapshot_generated_at": ibkr_ts,
        "source_context": source_context,
        "technical": {
            "raw": {
                "received_at": technical_ts,
            }
        },
        "market": {
            "generated_at": market_ts,
            "label": "FRESHNESS_FIXTURE",
            "is_regular_market_open": True,
            "options_bidask_expected": True,
        },
        "risk_gate": {
            "canslim": {
                "status": "PASS" if canslim_ts else "NOT_PROVIDED",
                "score": 82 if canslim_ts else None,
                "raw": {
                    "canslim_received_at": canslim_ts,
                },
            }
        },
    }


def validate_freshness_fixtures() -> list[str]:
    data, errors = load_json(FRESHNESS_FIXTURES)
    if errors:
        return errors
    if not isinstance(data, dict):
        return [f"{FRESHNESS_FIXTURES.relative_to(ROOT)} root must be an object"]

    if data.get("fixture_version") != "strategy_intelligence_freshness_cases_v1":
        errors.append("freshness fixture version mismatch")

    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.append("freshness fixture cases must be a non-empty list")
        return errors

    now = datetime.now(timezone.utc)
    names: set[str] = set()
    for index, case in enumerate(cases):
        path = f"{FRESHNESS_FIXTURES.relative_to(ROOT)}.cases[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{path} must be an object")
            continue

        name = case.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{path}.name must be a non-empty string")
            continue
        if name in names:
            errors.append(f"{path}.name duplicates {name}")
        names.add(name)

        offsets = case.get("source_offsets_minutes")
        expected = case.get("expected")
        if not isinstance(offsets, dict):
            errors.append(f"{path}.source_offsets_minutes must be an object")
            continue
        if not isinstance(expected, dict):
            errors.append(f"{path}.expected must be an object")
            continue

        try:
            decision = build_freshness_decision(offsets, now)
        except ValueError as exc:
            errors.append(f"{path}: {exc}")
            continue

        result = strategy_intelligence.freshness_gates(decision)
        if result.get("freshness_version") != "freshness_gates_v1":
            errors.append(f"{path}: freshness version mismatch: {result.get('freshness_version')}")

        for key in ["blocks_actionable_ranking", "all_required_fresh"]:
            if key in expected and result.get(key) is not expected.get(key):
                errors.append(f"{path}: expected {key}={expected.get(key)}, got {result.get(key)}")

        expected_blockers = expected.get("required_blockers") or []
        blockers = result.get("blockers") or []
        for blocker in expected_blockers:
            if blocker not in blockers:
                errors.append(f"{path}: expected blocker {blocker}, got {blockers}")

        expected_status = expected.get("gate_status") or {}
        gates = result.get("gates") or {}
        if not isinstance(expected_status, dict):
            errors.append(f"{path}.expected.gate_status must be an object")
            continue
        for gate, status in expected_status.items():
            actual = (gates.get(gate) or {}).get("status")
            if actual != status:
                errors.append(f"{path}: expected {gate} status {status}, got {actual}")

        source_context = result.get("source_context") or {}
        for sensitive_key in ["account_id", "balance", "buying_power", "cash", "token", "secret"]:
            if sensitive_key in json.dumps(source_context).lower():
                errors.append(f"{path}: source_context leaked sensitive key {sensitive_key}")

    return errors


def main() -> int:
    failures = validate_registry()
    failures.extend(validate_research_notes())
    failures.extend(validate_freshness_fixtures())

    if failures:
        print("\n".join(failures))
        return 1

    print("Validated Strategy Intelligence registry, Morgan research notes, and freshness fixtures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
