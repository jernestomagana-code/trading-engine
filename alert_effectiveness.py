"""Evidence-based alert effectiveness metrics for Stock Ultimus."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import alert_opportunity_audit
import decision_outcome_intelligence


EFFECTIVENESS_VERSION = "stock_ultimus_alert_effectiveness_v1"
CLOSED = {"WIN", "LOSS", "BREAKEVEN", "EXPIRED", "CANCELLED"}
POSITIVE = {"WIN"}
NEGATIVE = {"LOSS"}
ENTRY_STATES = {"ENTRY_READY"}
FILTERED_STATES = {"RISK_BLOCKED", "WAIT_TECHNICAL", "WAIT_OPTIONS_DATA", "NO_SETUP", "MANUAL_REVIEW"}


def _upper(value: Any, default: str = "UNKNOWN") -> str:
    text = str(value or "").strip().upper()
    return text or default


def _time(value: Any) -> datetime | None:
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text) if text else None
    except Exception:
        return None
    if parsed and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _rows(path: Path, key: str) -> list[dict[str, Any]]:
    payload = alert_opportunity_audit.read_json(path, [])
    return alert_opportunity_audit.list_from_payload(payload, [key, "rows", "items"])


def build_effectiveness(
    decisions: list[dict[str, Any]], outcomes: list[dict[str, Any]], *, generated_at: str | None = None
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    normalized = [alert_opportunity_audit.normalize_decision(item, "decision_journal") for item in decisions]
    logical = alert_opportunity_audit.dedupe_decisions(normalized)
    deduped = [item.get("raw") or {} for item in logical]
    links = decision_outcome_intelligence.link_decisions_to_outcomes(deduped, outcomes)
    entry = [item for item in deduped if _upper(item.get("final_state") or item.get("decision")) in ENTRY_STATES]
    filtered = [item for item in deduped if _upper(item.get("final_state") or item.get("decision")) in FILTERED_STATES]

    def linked(item: dict[str, Any]) -> dict[str, Any] | None:
        return links.get(str(item.get("decision_id") or ""))

    tracked_entry = [(item, linked(item)) for item in entry if linked(item)]
    resolved_entry = [(item, outcome) for item, outcome in tracked_entry if _upper(outcome.get("outcome")) in CLOSED]
    useful = [(item, outcome) for item, outcome in resolved_entry if _upper(outcome.get("outcome")) in POSITIVE]
    false_positive = [(item, outcome) for item, outcome in resolved_entry if _upper(outcome.get("outcome")) in NEGATIVE]
    neutral = [(item, outcome) for item, outcome in resolved_entry if _upper(outcome.get("outcome")) not in POSITIVE | NEGATIVE]
    tracked_filtered = [(item, linked(item)) for item in filtered if linked(item)]
    missed = [(item, outcome) for item, outcome in tracked_filtered if _upper(outcome.get("outcome")) in POSITIVE]
    correct_blocks = [(item, outcome) for item, outcome in tracked_filtered if _upper(outcome.get("outcome")) in NEGATIVE]

    latencies = []
    for decision, outcome in resolved_entry:
        start = _time(decision.get("recorded_at") or decision.get("generated_at"))
        end = _time(outcome.get("evaluated_at") or outcome.get("recorded_at"))
        if start and end and end >= start:
            latencies.append((end - start).total_seconds() / 3600)
    precision_denominator = len(useful) + len(false_positive)
    audit = alert_opportunity_audit.build_alert_opportunity_audit_from_rows(
        decisions, outcomes, generated_at=generated_at
    )
    data_quality = audit.get("data_quality") if isinstance(audit.get("data_quality"), dict) else {}
    source_counts = (audit.get("summary") or {}).get("source_counts") or {}
    resolved_count = len(resolved_entry)
    status = "REVIEWABLE" if resolved_count >= 30 else "BUILDING_EVIDENCE" if resolved_count else "WAITING_FOR_OUTCOMES"
    return {
        "effectiveness_version": EFFECTIVENESS_VERSION,
        "generated_at": generated_at,
        "status": status,
        "raw_decision_count": len(decisions),
        "logical_alert_count": len(deduped),
        "duplicate_decisions_collapsed": max(0, len(decisions) - len(deduped)),
        "entry_alert_count": len(entry),
        "tracked_entry_alert_count": len(tracked_entry),
        "entry_tracking_coverage_pct": round(len(tracked_entry) / len(entry) * 100, 2) if entry else None,
        "resolved_entry_alert_count": resolved_count,
        "useful_alert_count": len(useful),
        "false_positive_count": len(false_positive),
        "neutral_or_cancelled_count": len(neutral),
        "verified_precision_pct": round(len(useful) / precision_denominator * 100, 2) if precision_denominator else None,
        "filtered_alert_count": len(filtered),
        "tracked_filtered_count": len(tracked_filtered),
        "missed_opportunity_count": len(missed),
        "correct_risk_block_count": len(correct_blocks),
        "average_resolution_hours": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "minimum_resolved_sample": 30,
        "resolved_sample_progress_pct": round(min(resolved_count / 30, 1) * 100, 2),
        "source_attribution_coverage_pct": data_quality.get("source_attribution_coverage_pct"),
        "source_counts": source_counts,
        "primary_gap": data_quality.get("primary_gap"),
        "manual_review_required": True,
        "automatic_rule_changes_authorized": False,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def build_from_runtime(runtime_dir: Path) -> dict[str, Any]:
    return build_effectiveness(
        _rows(runtime_dir / "v32_decision_journal.json", "decisions"),
        _rows(runtime_dir / "v32_outcomes_journal.json", "outcomes"),
    )
