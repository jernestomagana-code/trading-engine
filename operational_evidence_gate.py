"""Operational evidence gate for Stock Ultimus.

This gate turns the foundation reports into explicit operating modes. It is
read-only, never authorizes orders, and never changes strategy parameters.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import foundation_evidence_recovery
import foundation_health


OPERATIONAL_EVIDENCE_GATE_VERSION = "operational_evidence_gate_v1"
MIN_SOURCE_COVERAGE_FOR_ENTRY_READY = 95.0
MIN_COMPLETE_OUTCOMES_FOR_PARAMETER_REVIEW = 30


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def _checks_by_name(health: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("name")): item
        for item in health.get("checks") or []
        if isinstance(item, dict) and item.get("name")
    }


def _status(checks: dict[str, dict[str, Any]], name: str) -> str:
    return str((checks.get(name) or {}).get("status") or "UNKNOWN").upper()


def _metrics(checks: dict[str, dict[str, Any]], name: str) -> dict[str, Any]:
    metrics = (checks.get(name) or {}).get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or str(value).strip() == "":
            return default
        return float(value)
    except Exception:
        return default


def _capability(name: str, allowed: bool, blockers: list[str], detail: str) -> dict[str, Any]:
    return {
        "name": name,
        "allowed": bool(allowed),
        "blockers": blockers,
        "detail": detail,
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def _dedupe(items: list[str]) -> list[str]:
    deduped = []
    for item in items:
        if item and item not in deduped:
            deduped.append(item)
    return deduped


def _operational_state(capabilities: dict[str, dict[str, Any]], health_status: str) -> str:
    if health_status == "FAIL" and not capabilities["can_collect_signals"]["allowed"]:
        return "FOUNDATION_BLOCKED"
    if capabilities["can_review_parameters"]["allowed"]:
        return "PARAMETER_REVIEW_READY"
    if capabilities["can_evaluate_outcomes"]["allowed"]:
        return "OUTCOME_COLLECTION_READY"
    if capabilities["can_create_entry_ready"]["allowed"]:
        return "SIGNAL_COLLECTION_READY"
    if capabilities["can_collect_signals"]["allowed"]:
        return "EVIDENCE_COLLECTION_ONLY"
    return "FOUNDATION_BLOCKED"


def _next_actions(state: str, blockers: list[str]) -> list[str]:
    actions = []
    if "NO_DECISION_JOURNAL" in blockers:
        actions.append("Generate or recover a decision journal before trusting downstream evidence.")
    if "SOURCE_ATTRIBUTION_BELOW_ENTRY_READY_MINIMUM" in blockers:
        actions.append("Run source attribution recovery or generate fresh V31/V32 decisions with source fields.")
    if "NO_TRADINGVIEW_LEDGER_EVENTS" in blockers:
        actions.append("Send or replay real TradingView payloads into v32_signal_events.json.")
    if "IBKR_CHAIN_COVERAGE_NOT_REVIEWABLE" in blockers:
        actions.append("Run IBKR bridge during a data window to refresh greeks, IV, bid/ask, spread, OI, and volume.")
    if "INSUFFICIENT_COMPLETE_OUTCOMES" in blockers:
        actions.append("Keep journaling paper outcomes until each strategy/regime reaches 30 complete closed outcomes.")
    if state == "PARAMETER_REVIEW_READY":
        actions.append("Prepare a versioned human parameter-review package; production rule changes remain blocked.")
    if not actions:
        actions.append("Continue manual evidence collection; no automated execution is authorized.")
    return actions


def build_operational_evidence_gate(
    runtime_dir: str | Path,
    *,
    generated_at: str | None = None,
    include_recovery_preview: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    generated_at = generated_at or now_iso()
    health = foundation_health.build_foundation_health(runtime, generated_at=generated_at)
    checks = _checks_by_name(health)
    data_quality = health.get("data_quality") if isinstance(health.get("data_quality"), dict) else {}
    performance = health.get("performance_summary") if isinstance(health.get("performance_summary"), dict) else {}
    parameter_review = health.get("parameter_review_summary") if isinstance(health.get("parameter_review_summary"), dict) else {}
    outcome_completeness = health.get("outcome_completeness_summary") if isinstance(health.get("outcome_completeness_summary"), dict) else {}
    source_coverage = _safe_float(data_quality.get("source_attribution_coverage_pct"))
    decision_count = _safe_int(data_quality.get("decision_count"))
    tv_events = _safe_int(_metrics(checks, "tradingview_signal_ledger").get("event_count"))
    ibkr_gap = str(_metrics(checks, "ibkr_chain_coverage").get("primary_gap") or "NO_IBKR_OPTION_DIAGNOSTICS")
    complete_outcomes = _safe_int(outcome_completeness.get("complete_closed_outcomes"))
    incomplete_outcomes = _safe_int(outcome_completeness.get("incomplete_closed_outcomes"))
    guard_allowed = _safe_int(parameter_review.get("guard_allowed_count"))

    collect_blockers = []
    if decision_count <= 0:
        collect_blockers.append("NO_DECISION_JOURNAL")
    can_collect_signals = decision_count > 0

    entry_blockers = []
    if source_coverage < MIN_SOURCE_COVERAGE_FOR_ENTRY_READY:
        entry_blockers.append("SOURCE_ATTRIBUTION_BELOW_ENTRY_READY_MINIMUM")
    if tv_events <= 0:
        entry_blockers.append("NO_TRADINGVIEW_LEDGER_EVENTS")
    if ibkr_gap != "COVERAGE_REVIEWABLE":
        entry_blockers.append("IBKR_CHAIN_COVERAGE_NOT_REVIEWABLE")
    can_create_entry_ready = can_collect_signals and not entry_blockers

    outcome_blockers = []
    if not can_create_entry_ready:
        outcome_blockers.extend(entry_blockers)
    if complete_outcomes <= 0 and incomplete_outcomes <= 0:
        outcome_blockers.append("NO_OUTCOME_SAMPLE")
    can_evaluate_outcomes = can_create_entry_ready and (complete_outcomes > 0 or incomplete_outcomes > 0)

    parameter_blockers = []
    if guard_allowed <= 0:
        parameter_blockers.append("PARAMETER_CHANGE_GUARD_BLOCKED")
    if complete_outcomes < MIN_COMPLETE_OUTCOMES_FOR_PARAMETER_REVIEW:
        parameter_blockers.append("INSUFFICIENT_COMPLETE_OUTCOMES")
    if incomplete_outcomes:
        parameter_blockers.append("INCOMPLETE_CLOSED_OUTCOME_EVIDENCE")
    can_review_parameters = guard_allowed > 0 and complete_outcomes >= MIN_COMPLETE_OUTCOMES_FOR_PARAMETER_REVIEW and not incomplete_outcomes

    capabilities = {
        "can_collect_signals": _capability(
            "can_collect_signals",
            can_collect_signals,
            collect_blockers,
            "Runtime has a decision journal and can collect more evidence." if can_collect_signals else "No decision journal is available.",
        ),
        "can_create_entry_ready": _capability(
            "can_create_entry_ready",
            can_create_entry_ready,
            _dedupe(entry_blockers),
            "ENTRY_READY can be considered only when source, TV, and IBKR evidence are reviewable.",
        ),
        "can_evaluate_outcomes": _capability(
            "can_evaluate_outcomes",
            can_evaluate_outcomes,
            _dedupe(outcome_blockers),
            "Outcome evaluation requires reviewable ENTRY_READY evidence and an outcome sample.",
        ),
        "can_review_parameters": _capability(
            "can_review_parameters",
            can_review_parameters,
            _dedupe(parameter_blockers),
            "Parameter review requires 30 complete closed outcomes per strategy/regime.",
        ),
        "can_change_production_rules": _capability(
            "can_change_production_rules",
            False,
            ["VERSIONED_HUMAN_RULE_CHANGE_REQUIRED"],
            "This gate never authorizes production rule changes.",
        ),
        "can_execute_orders": _capability(
            "can_execute_orders",
            False,
            ["AUTOMATED_EXECUTION_NOT_AUTHORIZED"],
            "Stock Ultimus remains decision-support only.",
        ),
    }
    all_blockers = _dedupe(
        collect_blockers
        + entry_blockers
        + outcome_blockers
        + parameter_blockers
        + ["VERSIONED_HUMAN_RULE_CHANGE_REQUIRED", "AUTOMATED_EXECUTION_NOT_AUTHORIZED"]
    )
    state = _operational_state(capabilities, str(health.get("status") or "UNKNOWN").upper())
    recovery_preview = None
    if include_recovery_preview:
        recovery = foundation_evidence_recovery.recover_foundation_evidence(
            runtime,
            generated_at=generated_at,
            write=False,
        )
        recovery_preview = {
            "source_attribution_changes_available": (recovery.get("source_attribution_backfill") or {}).get("changed_count"),
            "ibkr_recovered_option_rows": (recovery.get("ibkr_diagnostics_recovery") or {}).get("option_row_count"),
            "tradingview_replayable_payloads": (recovery.get("tradingview_ledger_replay") or {}).get("replayable_payload_count"),
            "outcome_changes_available": (recovery.get("outcome_backfill") or {}).get("changed_count"),
            "collection_readiness": recovery.get("collection_readiness") or {},
        }

    return {
        "engine": "OPERATIONAL_EVIDENCE_GATE",
        "operational_evidence_gate_version": OPERATIONAL_EVIDENCE_GATE_VERSION,
        "generated_at": generated_at,
        "runtime_dir": str(runtime),
        "state": state,
        "status": state,
        "capabilities": capabilities,
        "blocked_reasons": all_blockers,
        "next_actions": _next_actions(state, all_blockers),
        "evidence_summary": {
            "foundation_health_status": health.get("status"),
            "decision_count": decision_count,
            "source_attribution_coverage_pct": source_coverage,
            "tradingview_event_count": tv_events,
            "ibkr_primary_gap": ibkr_gap,
            "closed_outcomes": _safe_int(performance.get("closed_outcomes")),
            "complete_closed_outcomes": complete_outcomes,
            "incomplete_closed_outcomes": incomplete_outcomes,
            "parameter_guard_allowed_count": guard_allowed,
            "minimum_source_coverage_for_entry_ready": MIN_SOURCE_COVERAGE_FOR_ENTRY_READY,
            "minimum_complete_outcomes_for_parameter_review": MIN_COMPLETE_OUTCOMES_FOR_PARAMETER_REVIEW,
        },
        "foundation_priorities": health.get("priorities") or [],
        "recovery_preview": recovery_preview,
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
