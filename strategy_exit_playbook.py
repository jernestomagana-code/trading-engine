"""Versioned exit and position-management playbook helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


EXIT_PLAYBOOK_VERSION = "strategy_exit_playbook_v1"
DEFAULT_EXIT_PLAYBOOK_PATH = Path("config/strategy_exit_playbook_v1.json")


def normalize_strategy(value: Any) -> str:
    return str(value or "").strip().upper() or "UNKNOWN"


def load_exit_playbook(path: str | Path = DEFAULT_EXIT_PLAYBOOK_PATH) -> dict[str, Any]:
    data = json.loads(Path(path).read_text())
    validate_exit_playbook(data)
    return data


def exit_strategy_map(playbook: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for item in playbook.get("strategies") or []:
        sid = normalize_strategy(item.get("id"))
        mapping[sid] = item
        for alias in item.get("aliases") or []:
            mapping[normalize_strategy(alias)] = item
    return mapping


def get_exit_strategy(playbook: dict[str, Any], strategy: Any) -> dict[str, Any] | None:
    return exit_strategy_map(playbook).get(normalize_strategy(strategy))


def validate_exit_playbook(playbook: dict[str, Any]) -> None:
    if playbook.get("exit_playbook_version") != EXIT_PLAYBOOK_VERSION:
        raise ValueError(f"expected {EXIT_PLAYBOOK_VERSION}")
    if playbook.get("not_order_instruction") is not True:
        raise ValueError("exit playbook must preserve not_order_instruction")
    if playbook.get("execution_authorized") is not False:
        raise ValueError("exit playbook must never authorize execution")

    required_states = {
        "NO_POSITION",
        "MONITOR",
        "TAKE_PROFIT_REVIEW",
        "ROLL_REVIEW",
        "ASSIGNMENT_REVIEW",
        "EXIT_REVIEW",
        "RISK_REVIEW",
        "EXPIRED_OR_CLOSED",
    }
    states = set(playbook.get("canonical_exit_states") or [])
    missing_states = sorted(required_states - states)
    if missing_states:
        raise ValueError(f"missing exit states {missing_states}")

    required = {
        "id",
        "status",
        "position_required",
        "required_inputs",
        "take_profit_review",
        "roll_review",
        "assignment_review",
        "risk_review",
        "outcome_metrics",
        "manual_review_text",
    }
    seen = set()
    for item in playbook.get("strategies") or []:
        missing = sorted(required - set(item.keys()))
        sid = normalize_strategy(item.get("id"))
        if missing:
            raise ValueError(f"exit strategy {sid} missing {missing}")
        if sid in seen:
            raise ValueError(f"duplicate exit strategy id {sid}")
        seen.add(sid)
        if item.get("status") != "ACTIVE_MANUAL_REVIEW":
            raise ValueError(f"exit strategy {sid} must be manual-review active")
        for block in ["take_profit_review", "roll_review", "assignment_review", "risk_review"]:
            state = (item.get(block) or {}).get("state")
            if state not in states:
                raise ValueError(f"exit strategy {sid} has invalid state {state} in {block}")

    for sid in ["CASH_SECURED_PUT", "COVERED_CALL"]:
        if sid not in seen:
            raise ValueError(f"missing required exit strategy {sid}")


def exit_playbook_summary(playbook: dict[str, Any]) -> dict[str, Any]:
    strategies = playbook.get("strategies") or []
    return {
        "exit_playbook_version": playbook.get("exit_playbook_version"),
        "ruleset_version": playbook.get("ruleset_version"),
        "status": playbook.get("status"),
        "active_exit_strategies": [item["id"] for item in strategies if item.get("status") == "ACTIVE_MANUAL_REVIEW"],
        "canonical_exit_states": playbook.get("canonical_exit_states") or [],
        "promotion_policy": playbook.get("promotion_policy") or {},
        "manual_review_required": True,
        "not_order_instruction": True,
        "execution_authorized": False,
    }


def exit_overlay(position: dict[str, Any], playbook: dict[str, Any]) -> dict[str, Any]:
    strategy = get_exit_strategy(playbook, position.get("strategy")) or {}
    current_state = normalize_strategy(position.get("exit_state") or position.get("state") or "MONITOR")
    blockers = list(position.get("blockers") or [])

    if not strategy:
        blockers.append("EXIT_PLAYBOOK_NOT_REGISTERED")
    if strategy.get("position_required") and position.get("position_open") is False:
        current_state = "NO_POSITION"
    if strategy.get("position_required") and position.get("position_open") is None:
        blockers.append("POSITION_STATUS_REQUIRED")

    return {
        "exit_playbook_version": playbook.get("exit_playbook_version"),
        "strategy_id": strategy.get("id") or normalize_strategy(position.get("strategy")),
        "exit_state": current_state,
        "required_inputs": strategy.get("required_inputs") or [],
        "take_profit_review": strategy.get("take_profit_review") or {},
        "roll_review": strategy.get("roll_review") or {},
        "assignment_review": strategy.get("assignment_review") or {},
        "risk_review": strategy.get("risk_review") or {},
        "outcome_metrics": strategy.get("outcome_metrics") or [],
        "exit_blockers": blockers,
        "manual_review_text": strategy.get("manual_review_text"),
        "manual_review_required": True,
        "not_order_instruction": True,
        "execution_authorized": False,
    }
