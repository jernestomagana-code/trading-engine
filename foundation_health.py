"""Offline foundation health report for Stock Ultimus.

This report consolidates evidence quality only. It never authorizes orders and
never changes strategy parameters.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import alert_opportunity_audit
import ibkr_diagnostics
import strategy_performance
import tradingview_signal_ledger


FOUNDATION_HEALTH_VERSION = "foundation_health_v1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _status_rank(status: str) -> int:
    return {
        "OK": 0,
        "WAITING_FOR_DATA": 1,
        "WARN": 2,
        "FAIL": 3,
    }.get(str(status or "").upper(), 2)


def _check(name: str, status: str, detail: str, **metrics: Any) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "detail": detail,
        "metrics": metrics,
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def _overall_status(checks: list[dict[str, Any]]) -> str:
    worst = max((_status_rank(item.get("status")) for item in checks), default=1)
    if worst >= _status_rank("FAIL"):
        return "FAIL"
    if worst >= _status_rank("WARN"):
        return "WARN"
    if any(item.get("status") == "WAITING_FOR_DATA" for item in checks):
        return "WAITING_FOR_DATA"
    return "OK"


def _priorities(checks: list[dict[str, Any]], review_report: dict[str, Any]) -> list[str]:
    priorities = []
    by_name = {item.get("name"): item for item in checks}
    source_check = by_name.get("source_attribution_coverage") or {}
    tv_check = by_name.get("tradingview_signal_ledger") or {}
    ibkr_check = by_name.get("ibkr_chain_coverage") or {}
    outcome_check = by_name.get("outcome_sample") or {}

    if source_check.get("status") in {"FAIL", "WARN"}:
        priorities.append("Generate fresh V31/V32 decisions so candidate_source and confirmation_source coverage can replace historical UNKNOWN records.")
    if tv_check.get("status") in {"FAIL", "WARN", "WAITING_FOR_DATA"}:
        priorities.append("Send or replay at least one TradingView technical payload into the ledger, then compare it with WAIT_TECHNICAL decisions.")
    if ibkr_check.get("status") in {"FAIL", "WARN", "WAITING_FOR_DATA"}:
        priorities.append("Run the IBKR bridge once during the next available data window to populate option-chain coverage diagnostics.")
    if outcome_check.get("status") in {"FAIL", "WARN", "WAITING_FOR_DATA"}:
        priorities.append("Keep journaling paper outcomes until each active strategy reaches at least 30 closed outcomes.")
    if not review_report.get("candidate_count"):
        priorities.append("Do not promote parameter changes yet; current evidence is still accumulation/review only.")
    if not priorities:
        priorities.append("Evidence is reviewable; prepare a versioned human parameter-review package before any rule change.")
    return priorities


def _raw_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item.get("raw") if isinstance(item.get("raw"), dict) else item for item in rows if isinstance(item, dict)]


def build_foundation_health(runtime_dir: str | Path, generated_at: str | None = None) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    generated_at = generated_at or now_iso()
    audit = alert_opportunity_audit.build_alert_opportunity_audit(runtime, generated_at=generated_at)
    decisions, outcomes, source_files = alert_opportunity_audit.load_runtime_inputs(runtime)
    tv_events = tradingview_signal_ledger.load_signal_events(runtime / "v32_signal_events.json", limit=20000)
    ibkr_payload = read_json(runtime / "v32_ibkr_chain_coverage.json", {})
    if not isinstance(ibkr_payload, dict):
        ibkr_payload = {}

    performance = strategy_performance.strategy_performance_report(
        _raw_rows(decisions),
        _raw_rows(outcomes),
        generated_at=generated_at,
    )
    review_report = strategy_performance.parameter_review_evidence_report(
        performance,
        generated_at=generated_at,
        minimum_closed_outcomes=30,
    )

    data_quality = audit.get("data_quality") if isinstance(audit.get("data_quality"), dict) else {}
    decision_count = int(data_quality.get("decision_count") or 0)
    closed_outcomes = int(data_quality.get("closed_outcome_count") or 0)
    source_coverage = float(data_quality.get("source_attribution_coverage_pct") or 0.0)
    ibkr_gap = str(ibkr_payload.get("primary_gap") or ibkr_diagnostics.primary_gap([], []))

    checks = []
    checks.append(
        _check(
            "decision_journal",
            "OK" if decision_count else "WAITING_FOR_DATA",
            "Decision evidence is present." if decision_count else "No decision journal rows available yet.",
            decision_count=decision_count,
            source_files_found=source_files,
        )
    )

    if not decision_count:
        source_status = "WAITING_FOR_DATA"
    elif source_coverage >= 95:
        source_status = "OK"
    elif source_coverage >= 50:
        source_status = "WARN"
    else:
        source_status = "FAIL"
    checks.append(
        _check(
            "source_attribution_coverage",
            source_status,
            f"Source attribution coverage is {source_coverage}%.",
            source_attribution_coverage_pct=source_coverage,
            unknown_source_decisions=data_quality.get("unknown_source_decisions"),
            missing_candidate_source_decisions=data_quality.get("missing_candidate_source_decisions"),
            missing_confirmation_source_decisions=data_quality.get("missing_confirmation_source_decisions"),
        )
    )

    checks.append(
        _check(
            "tradingview_signal_ledger",
            "OK" if tv_events else ("WARN" if source_files.get("tradingview_signal_ledger") else "WAITING_FOR_DATA"),
            "TradingView signal ledger has events." if tv_events else "No TradingView ledger events available yet.",
            event_count=len(tv_events),
            latest_event_at=max([str(item.get("received_at")) for item in tv_events if item.get("received_at")], default=None),
        )
    )

    if not ibkr_payload:
        ibkr_status = "WAITING_FOR_DATA"
    elif ibkr_gap == "COVERAGE_REVIEWABLE":
        ibkr_status = "OK"
    elif ibkr_gap in {"INCOMPLETE_OPTION_MARKET_DATA", "NO_OPTION_ROWS", "NO_IBKR_OPTION_DIAGNOSTICS"}:
        ibkr_status = "WARN"
    else:
        ibkr_status = "FAIL"
    checks.append(
        _check(
            "ibkr_chain_coverage",
            ibkr_status,
            f"IBKR diagnostic primary gap: {ibkr_gap}.",
            primary_gap=ibkr_gap,
            option_row_count=ibkr_payload.get("option_row_count", 0),
            chain_event_count=ibkr_payload.get("chain_event_count", 0),
            missing_execution_field_counts=ibkr_payload.get("missing_execution_field_counts") or {},
        )
    )

    if closed_outcomes >= 30:
        outcome_status = "OK"
    elif closed_outcomes > 0:
        outcome_status = "WARN"
    else:
        outcome_status = "WAITING_FOR_DATA"
    checks.append(
        _check(
            "outcome_sample",
            outcome_status,
            f"Closed outcomes available: {closed_outcomes}.",
            closed_outcomes=closed_outcomes,
            minimum_for_parameter_review=30,
        )
    )

    checks.append(
        _check(
            "parameter_review_readiness",
            "OK" if review_report.get("candidate_count") else "WAITING_FOR_DATA",
            "At least one strategy is ready for human parameter review." if review_report.get("candidate_count") else "No strategy has enough closed outcomes for parameter review yet.",
            candidate_count=review_report.get("candidate_count"),
            blocked_count=review_report.get("blocked_count"),
        )
    )

    status = _overall_status(checks)
    return {
        "engine": "STOCK_ULTIMUS_FOUNDATION_HEALTH",
        "foundation_health_version": FOUNDATION_HEALTH_VERSION,
        "generated_at": generated_at,
        "runtime_dir": str(runtime),
        "status": status,
        "checks": checks,
        "priorities": _priorities(checks, review_report),
        "audit_summary": audit.get("summary") or {},
        "data_quality": data_quality,
        "performance_summary": performance.get("summary") or {},
        "parameter_review_summary": {
            "candidate_count": review_report.get("candidate_count"),
            "blocked_count": review_report.get("blocked_count"),
            "minimum_closed_outcomes": review_report.get("minimum_closed_outcomes"),
        },
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
