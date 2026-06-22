"""Versioned strategy input contracts for candidate and signal sourcing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CONTRACT_VERSION = "strategy_input_contract_v1"
DEFAULT_INPUT_CONTRACT_PATH = Path("config/strategy_input_contract_v1.json")
REQUIRED_STRATEGIES = {
    "CASH_SECURED_PUT",
    "COVERED_CALL",
    "IRON_CONDOR",
    "INTRADAY_INDEX_FUTURES",
    "CANSLIM_GROWTH_FILTER",
}
ALLOWED_TRADINGVIEW_DEPENDENCIES = {
    "OPTIONAL_CONFIRMATION",
    "OPTIONAL_CONFIRMATION_RESEARCH_ONLY",
    "PREFERRED_BUT_NOT_EXCLUSIVE",
}


def normalize_strategy(value: Any) -> str:
    return str(value or "").strip().upper() or "UNKNOWN"


def load_input_contracts(path: str | Path = DEFAULT_INPUT_CONTRACT_PATH) -> dict[str, Any]:
    data = json.loads(Path(path).read_text())
    validate_input_contracts(data)
    return data


def input_contract_map(contracts: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for item in contracts.get("contracts") or []:
        sid = normalize_strategy(item.get("strategy_id"))
        mapping[sid] = item
        for alias in item.get("aliases") or []:
            mapping[normalize_strategy(alias)] = item
    return mapping


def get_input_contract(contracts: dict[str, Any], strategy: Any) -> dict[str, Any] | None:
    return input_contract_map(contracts).get(normalize_strategy(strategy))


def validate_input_contracts(contracts: dict[str, Any]) -> None:
    if contracts.get("contract_version") != CONTRACT_VERSION:
        raise ValueError(f"expected {CONTRACT_VERSION}")
    if contracts.get("not_order_instruction") is not True:
        raise ValueError("input contracts must preserve not_order_instruction")
    if contracts.get("execution_authorized") is not False:
        raise ValueError("input contracts must never authorize execution")

    global_policy = contracts.get("global_policy") or {}
    if global_policy.get("candidate_generation_does_not_require_tradingview") is not True:
        raise ValueError("candidate generation must not require TradingView")
    if global_policy.get("execution_authorized") is not False:
        raise ValueError("global policy must never authorize execution")

    seen = set()
    required_fields = {
        "strategy_id",
        "candidate_sources",
        "confirmation_sources",
        "fallback_sources",
        "tradingview_dependency",
        "required_for_candidate",
        "required_for_entry_ready",
        "freshness_minutes",
        "state_when_missing",
        "no_tradingview_alert_behavior",
        "not_order_instruction",
        "execution_authorized",
    }
    for item in contracts.get("contracts") or []:
        missing = sorted(required_fields - set(item.keys()))
        if missing:
            raise ValueError(f"input contract {item.get('strategy_id')} missing {missing}")
        sid = normalize_strategy(item.get("strategy_id"))
        if sid in seen:
            raise ValueError(f"duplicate input contract {sid}")
        seen.add(sid)
        if item.get("tradingview_dependency") not in ALLOWED_TRADINGVIEW_DEPENDENCIES:
            raise ValueError(f"invalid tradingview dependency for {sid}")
        for list_key in ["candidate_sources", "confirmation_sources", "fallback_sources", "required_for_candidate", "required_for_entry_ready"]:
            if not isinstance(item.get(list_key), list) or not item.get(list_key):
                raise ValueError(f"{sid} {list_key} must be a non-empty list")
        if "TRADINGVIEW_ALERT" not in item.get("confirmation_sources", []):
            raise ValueError(f"{sid} must document TradingView as a possible confirmation source")
        if item.get("not_order_instruction") is not True:
            raise ValueError(f"{sid} missing no-order guardrail")
        if item.get("execution_authorized") is not False:
            raise ValueError(f"{sid} must never authorize execution")

    missing_strategies = sorted(REQUIRED_STRATEGIES - seen)
    if missing_strategies:
        raise ValueError(f"missing required strategy input contracts {missing_strategies}")


def input_contract_summary(contracts: dict[str, Any]) -> dict[str, Any]:
    items = contracts.get("contracts") or []
    optional_tradingview = [
        item["strategy_id"]
        for item in items
        if item.get("tradingview_dependency") in {"OPTIONAL_CONFIRMATION", "OPTIONAL_CONFIRMATION_RESEARCH_ONLY"}
    ]
    preferred_tradingview = [
        item["strategy_id"]
        for item in items
        if item.get("tradingview_dependency") == "PREFERRED_BUT_NOT_EXCLUSIVE"
    ]
    local_fallbacks = [
        item["strategy_id"]
        for item in items
        if any("LOCAL" in str(source) or "IBKR_HISTORICAL_BARS" in str(source) for source in item.get("fallback_sources", []))
    ]
    return {
        "contract_version": contracts.get("contract_version"),
        "ruleset_version": contracts.get("ruleset_version"),
        "strategy_count": len(items),
        "tradingview_not_required_for_candidate_generation": (
            (contracts.get("global_policy") or {}).get("candidate_generation_does_not_require_tradingview") is True
        ),
        "tradingview_optional_confirmation": optional_tradingview,
        "tradingview_preferred_but_not_exclusive": preferred_tradingview,
        "local_or_ibkr_fallback_available": local_fallbacks,
        "manual_review_required": True,
        "not_order_instruction": True,
        "execution_authorized": False,
    }


def input_overlay(strategy: Any, contracts: dict[str, Any]) -> dict[str, Any]:
    contract = get_input_contract(contracts, strategy) or {}
    return {
        "strategy_input_contract_version": contracts.get("contract_version"),
        "strategy_id": contract.get("strategy_id") or normalize_strategy(strategy),
        "candidate_sources": contract.get("candidate_sources") or [],
        "confirmation_sources": contract.get("confirmation_sources") or [],
        "fallback_sources": contract.get("fallback_sources") or [],
        "tradingview_dependency": contract.get("tradingview_dependency") or "UNKNOWN",
        "required_for_candidate": contract.get("required_for_candidate") or [],
        "required_for_entry_ready": contract.get("required_for_entry_ready") or [],
        "state_when_missing": contract.get("state_when_missing") or {},
        "no_tradingview_alert_behavior": contract.get("no_tradingview_alert_behavior"),
        "manual_review_required": True,
        "not_order_instruction": True,
        "execution_authorized": False,
    }
