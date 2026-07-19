"""Decision-to-outcome intelligence for the Stock Ultimus console."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import strategy_performance


INTELLIGENCE_VERSION = "stock_ultimus_decision_outcome_intelligence_v1"
ACTIONABLE_STATES = {"ENTRY_READY", "MANUAL_REVIEW", "RISK_BLOCKED", "WATCH", "WATCHLIST"}


def _upper(value: Any, default: str = "UNKNOWN") -> str:
    text = str(value or "").strip().upper()
    return text or default


def _timestamp(item: dict[str, Any]) -> str:
    return str(item.get("recorded_at") or item.get("decision_generated_at") or item.get("generated_at") or "")


def build_intelligence(
    decisions: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    *,
    generated_at: str | None = None,
    recent_limit: int = 10,
) -> dict[str, Any]:
    decisions = [item for item in (decisions or []) if isinstance(item, dict)]
    outcomes = [item for item in (outcomes or []) if isinstance(item, dict)]
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    performance = strategy_performance.strategy_performance_report(
        decisions, outcomes, generated_at=generated_at
    )
    summary = performance.get("summary") if isinstance(performance.get("summary"), dict) else {}
    outcome_by_decision = {
        str(item.get("decision_id")): item
        for item in outcomes
        if item.get("decision_id")
    }
    actionable = [item for item in decisions if _upper(item.get("final_state")) in ACTIONABLE_STATES]
    linked_actionable = [item for item in actionable if str(item.get("decision_id") or "") in outcome_by_decision]
    complete = int(summary.get("complete_closed_outcomes") or 0)
    minimum = 30
    coverage = round((len(linked_actionable) / len(actionable)) * 100, 2) if actionable else None

    recent_source = actionable or decisions
    recent_rows = []
    for decision in sorted(recent_source, key=_timestamp, reverse=True)[:max(1, int(recent_limit))]:
        linked = outcome_by_decision.get(str(decision.get("decision_id") or ""))
        embedded = decision.get("latest_outcome") if isinstance(decision.get("latest_outcome"), dict) else {}
        outcome = linked or embedded
        recent_rows.append({
            "decision_id": decision.get("decision_id"),
            "recorded_at": _timestamp(decision),
            "ticker": _upper(decision.get("ticker")),
            "strategy": _upper(decision.get("strategy")),
            "decision": _upper(decision.get("decision") or decision.get("final_state")),
            "final_state": _upper(decision.get("final_state")),
            "action": str(decision.get("action") or decision.get("explanation") or "")[:240],
            "outcome": _upper(outcome.get("outcome"), "PENDIENTE") if outcome else "PENDIENTE",
            "pnl_r": outcome.get("pnl_r") if outcome else None,
            "mfe_r": outcome.get("mfe_r") if outcome else None,
            "mae_r": outcome.get("mae_r") if outcome else None,
        })

    strategy_rows = []
    for row in performance.get("strategies") or []:
        if not isinstance(row, dict):
            continue
        strategy_rows.append({
            "strategy": row.get("strategy"),
            "decisions": row.get("decision_count") or 0,
            "closed_outcomes": row.get("closed_outcomes") or 0,
            "complete_closed_outcomes": row.get("complete_closed_outcomes") or 0,
            "win_rate": row.get("win_rate"),
            "expectancy_r": row.get("expectancy_r"),
            "avg_mfe_r": row.get("avg_mfe_r"),
            "avg_mae_r": row.get("avg_mae_r"),
            "evidence_level": row.get("evidence_level"),
            "parameter_review_ready": row.get("parameter_review_ready") is True,
        })

    return {
        "intelligence_version": INTELLIGENCE_VERSION,
        "generated_at": generated_at,
        "status": "EVIDENCE_READY" if complete >= minimum else "BUILDING_EVIDENCE",
        "decision_count": len(decisions),
        "actionable_decision_count": len(actionable),
        "outcome_count": len(outcomes),
        "linked_actionable_outcome_count": len(linked_actionable),
        "actionable_outcome_coverage_pct": coverage,
        "closed_outcomes": summary.get("closed_outcomes") or 0,
        "complete_closed_outcomes": complete,
        "minimum_complete_outcomes": minimum,
        "evidence_progress_pct": round(min(complete / minimum, 1) * 100, 2),
        "parameter_review_ready": complete >= minimum,
        "recent_decisions": recent_rows,
        "strategies": strategy_rows,
        "manual_review_required": True,
        "automatic_parameter_changes_authorized": False,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
