"""Versioned strategy registry and playbook helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REGISTRY_VERSION = "strategy_registry_v1"
DEFAULT_REGISTRY_PATH = Path("config/strategy_registry_v1.json")


def load_registry(path: str | Path = DEFAULT_REGISTRY_PATH) -> dict[str, Any]:
    data = json.loads(Path(path).read_text())
    validate_registry(data)
    return data


def normalize_strategy(value: Any) -> str:
    return str(value or "").strip().upper() or "UNKNOWN"


def strategy_map(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for item in registry.get("strategies") or []:
        sid = normalize_strategy(item.get("id"))
        mapping[sid] = item
        for alias in item.get("aliases") or []:
            mapping[normalize_strategy(alias)] = item
    return mapping


def get_strategy(registry: dict[str, Any], strategy: Any) -> dict[str, Any] | None:
    return strategy_map(registry).get(normalize_strategy(strategy))


def validate_registry(registry: dict[str, Any]) -> None:
    if registry.get("registry_version") != REGISTRY_VERSION:
        raise ValueError(f"expected {REGISTRY_VERSION}")
    if registry.get("not_order_instruction") is not True:
        raise ValueError("registry must preserve not_order_instruction")

    seen = set()
    required = {
        "id",
        "status",
        "asset_class",
        "market_regime",
        "technical_required",
        "account_context_required",
        "option_contract_required",
        "primary_blockers",
        "recommendation_text",
    }
    for item in registry.get("strategies") or []:
        missing = sorted(required - set(item.keys()))
        if missing:
            raise ValueError(f"strategy {item.get('id')} missing {missing}")
        sid = normalize_strategy(item.get("id"))
        if sid in seen:
            raise ValueError(f"duplicate strategy id {sid}")
        seen.add(sid)
        if item.get("status") not in {"ACTIVE_MANUAL_REVIEW", "RESEARCH_ONLY", "FILTER_ONLY"}:
            raise ValueError(f"invalid strategy status for {sid}")

    for sid in ["CASH_SECURED_PUT", "COVERED_CALL", "IRON_CONDOR", "INTRADAY_INDEX_FUTURES", "CANSLIM_GROWTH_FILTER"]:
        if sid not in seen:
            raise ValueError(f"missing required strategy {sid}")


def playbook_summary(registry: dict[str, Any]) -> dict[str, Any]:
    strategies = registry.get("strategies") or []
    return {
        "registry_version": registry.get("registry_version"),
        "ruleset_version": registry.get("ruleset_version"),
        "status": registry.get("status"),
        "active_manual_review": [item["id"] for item in strategies if item.get("status") == "ACTIVE_MANUAL_REVIEW"],
        "research_only": [item["id"] for item in strategies if item.get("status") == "RESEARCH_ONLY"],
        "filters": [item["id"] for item in strategies if item.get("status") == "FILTER_ONLY"],
        "research_loop": registry.get("research_loop") or {},
        "not_order_instruction": True,
        "execution_authorized": False,
    }


def recommendation_overlay(decision: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    strategy = get_strategy(registry, decision.get("strategy")) or {}
    status = strategy.get("status") or "UNKNOWN"
    state = normalize_strategy(decision.get("final_state"))
    blockers = list(decision.get("blockers") or [])

    if status == "RESEARCH_ONLY" and "RESEARCH_ONLY" not in blockers:
        blockers.append("RESEARCH_ONLY")
    if strategy.get("option_contract_required") and state in {"NO_DATA", "WAIT_OPTIONS_DATA"}:
        if "WAIT_OPTIONS_DATA" not in blockers and state != "NO_DATA":
            blockers.append("WAIT_OPTIONS_DATA")

    return {
        "strategy_registry_version": registry.get("registry_version"),
        "strategy_id": strategy.get("id") or normalize_strategy(decision.get("strategy")),
        "strategy_status": status,
        "asset_class": strategy.get("asset_class") or decision.get("asset_class"),
        "market_regime": strategy.get("market_regime") or [],
        "strategy_recommendation_text": strategy.get("recommendation_text"),
        "strategy_primary_blockers": strategy.get("primary_blockers") or [],
        "strategy_blockers": blockers,
        "research_only": status == "RESEARCH_ONLY",
        "manual_review_required": True,
        "not_order_instruction": True,
        "execution_authorized": False,
    }
