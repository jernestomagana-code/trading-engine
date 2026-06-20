"""Versioned V31 decision and selected-contract payload contracts."""

from __future__ import annotations

from typing import Any

from strategy_intelligence import safe_upper, selected_contract_from_decision


V31_DECISION_CONTRACT_SCHEMA_VERSION = "v31_decision_contract_schema_v1"
SELECTED_CONTRACT_VERSION = "selected_contract_v1"
ENGINE = "V31_CANONICAL_DECISION_CONTRACT"
V31_CANONICAL_STATES = {
    "NO_DATA",
    "WAIT_MARKET",
    "WAIT_ACCOUNT_CONTEXT",
    "WAIT_OPTIONS_DATA",
    "WAIT_TECHNICAL",
    "RISK_BLOCKED",
    "MANUAL_REVIEW",
    "ENTRY_READY",
}


def canonical_state(v29_state: Any, canonical_states: set[str] | list[str] | tuple[str, ...] | None = None) -> str:
    mapping = {
        "WAIT_MARKET_OPEN": "WAIT_MARKET",
        "MANUAL_REVIEW_BLOCKED": "MANUAL_REVIEW",
        "RADAR": "MANUAL_REVIEW",
    }
    allowed = set(canonical_states or V31_CANONICAL_STATES)
    state = mapping.get(str(v29_state or ""), v29_state)
    if state not in allowed:
        return "NO_DATA"
    return str(state)


def selected_contract_from_v29(v29_decision: dict[str, Any]) -> dict[str, Any]:
    contract = selected_contract_from_decision(v29_decision)
    return {
        "selected_contract_version": SELECTED_CONTRACT_VERSION,
        **contract,
    }


def normalized_blockers(blockers: list[Any] | None, main_blocker: Any) -> list[Any]:
    result = list(blockers or [])
    if main_blocker and main_blocker not in result:
        result.insert(0, main_blocker)
    return result


def apply_registry_cap(
    final_state: str,
    main_blocker: Any,
    blockers: list[Any],
    registry_entry: dict[str, Any],
) -> tuple[str, Any, list[Any]]:
    registry_state = safe_upper(registry_entry.get("state"), "ENABLED")
    capped_state = final_state
    capped_blocker = main_blocker
    capped_blockers = normalized_blockers(blockers, main_blocker)

    if final_state == "ENTRY_READY" and registry_state == "RADAR_ONLY":
        capped_state = "MANUAL_REVIEW"
        capped_blocker = "STRATEGY_RADAR_ONLY"
    elif final_state == "ENTRY_READY" and registry_state == "DISABLED":
        capped_state = "RISK_BLOCKED"
        capped_blocker = "STRATEGY_DISABLED"

    return capped_state, capped_blocker, normalized_blockers(capped_blockers, capped_blocker)


def decision_contract(
    v29_decision: dict[str, Any],
    *,
    generated_at: str,
    decision_version: str,
    strategy_version: str,
    ruleset_version: str,
    snapshot_version: str,
    final_state: str,
    strategy: str,
    main_blocker: Any,
    blockers: list[Any],
    registry_entry: dict[str, Any],
    selected_contract: dict[str, Any],
    freshness: dict[str, Any],
    score_components: dict[str, Any],
) -> dict[str, Any]:
    return {
        "engine": ENGINE,
        "contract_schema_version": V31_DECISION_CONTRACT_SCHEMA_VERSION,
        "source_engine": v29_decision.get("engine"),
        "decision_id": v29_decision.get("decision_id"),
        "decision_version": decision_version,
        "strategy_version": strategy_version,
        "ruleset_version": ruleset_version,
        "snapshot_version": snapshot_version,
        "generated_at": generated_at,
        "ticker": v29_decision.get("ticker"),
        "strategy": strategy,
        "status": v29_decision.get("status", "OK"),
        "final_state": final_state,
        "decision": final_state,
        "main_blocker": main_blocker,
        "blockers": list(blockers or []),
        "required_missing_fields": list(v29_decision.get("required_missing_fields") or []),
        "risk_notes": [
            v29_decision.get("risk_note"),
            "ENTRY_READY means ready for manual review, not authorization to trade.",
        ],
        "explanation": v29_decision.get("executive_summary") or v29_decision.get("action"),
        "next_required_action": v29_decision.get("action"),
        "not_order_instruction": True,
        "ready_for_manual_review": final_state == "ENTRY_READY",
        "execution_authorized": False,
        "strategy_registry": registry_entry,
        "selected_contract": selected_contract,
        "technical": {
            "bias": v29_decision.get("technical_bias"),
            "score": v29_decision.get("technical_score"),
            "fit": v29_decision.get("technical_fit"),
            "raw": v29_decision.get("technical"),
        },
        "risk": {
            "fit": v29_decision.get("risk_fit"),
            "manual_review_fit": v29_decision.get("manual_review_fit"),
            "gate": v29_decision.get("risk_gate"),
        },
        "score_components": score_components,
        "freshness": freshness,
        "source_context": v29_decision.get("source_context"),
        "market": v29_decision.get("market"),
        "audit": {
            "contract_schema_version": V31_DECISION_CONTRACT_SCHEMA_VERSION,
            "decision_id": v29_decision.get("decision_id"),
            "master_source": v29_decision.get("master_source"),
            "snapshot_generated_at": v29_decision.get("snapshot_generated_at"),
            "snapshot_received_at": v29_decision.get("snapshot_received_at"),
            "rows_found_for_ticker": v29_decision.get("rows_found_for_ticker"),
            "total_rows_found": v29_decision.get("total_rows_found"),
            "executable_rows_found": v29_decision.get("executable_rows_found"),
            "source_final_state": v29_decision.get("final_state"),
            "source_decision": v29_decision.get("decision"),
            "strategy_registry_state": registry_entry.get("state"),
            "strategy_entry_ready_cap": registry_entry.get("entry_ready_cap"),
            "source_context": v29_decision.get("source_context"),
        },
    }
