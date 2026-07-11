"""Alert and opportunity coverage audit for Stock Ultimus.

The audit is evidence for strategy review only. It does not authorize
execution or weaken deterministic gates.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AUDIT_VERSION = "alert_opportunity_deep_audit_v1"
UNKNOWN = "UNKNOWN"


def safe_upper(value: Any, default: str = UNKNOWN) -> str:
    text = str(value or "").strip().upper()
    return text or default


def safe_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in {float("inf"), float("-inf")}:
        return None
    return result


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def list_from_payload(payload: Any, keys: list[str]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def selected_contract(item: dict[str, Any]) -> dict[str, Any]:
    contract = item.get("selected_contract")
    if isinstance(contract, dict):
        return contract
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    options = evidence.get("options") if isinstance(evidence.get("options"), dict) else {}
    contract = options.get("contract")
    return contract if isinstance(contract, dict) else {}


def flatten_blockers(item: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    for key in [
        "main_blocker",
        "risk_blocker",
        "broker_check_status",
        "parameter_review_status",
    ]:
        value = safe_upper(item.get(key), "")
        if value:
            blockers.append(value)
    for key in [
        "blockers",
        "risk_profile_blockers",
        "broker_check_blockers",
        "parameter_review_blockers",
    ]:
        value = item.get(key)
        if isinstance(value, list):
            blockers.extend(safe_upper(part, "") for part in value if safe_upper(part, ""))
    deduped = []
    seen = set()
    for blocker in blockers:
        if not blocker or blocker == UNKNOWN or blocker in seen:
            continue
        seen.add(blocker)
        deduped.append(blocker)
    return deduped


def infer_signal_source(item: dict[str, Any]) -> str:
    explicit = safe_upper(
        item.get("signal_source")
        or item.get("source")
        or item.get("validation_source")
        or item.get("candidate_source")
        or item.get("confirmation_source"),
        "",
    )
    if explicit and explicit != UNKNOWN:
        return explicit

    haystack = json.dumps(item, sort_keys=True, default=str).upper()
    if "TRADINGVIEW" in haystack or "TRADING_VIEW" in haystack:
        return "TRADINGVIEW_ALERT"
    if "LOCAL_TECHNICAL" in haystack or "LOCAL_STRATEGY_SCANNER" in haystack:
        return "LOCAL_TECHNICAL_OR_SCANNER"
    if "IBKR" in haystack or "OPTION_CHAIN" in haystack:
        return "IBKR_DATA"
    return UNKNOWN


def decision_key(item: dict[str, Any]) -> str:
    for key in ["decision_id", "id", "outcome_id", "event_id", "signal_id"]:
        value = safe_text(item.get(key))
        if value:
            return value
    parts = [
        safe_upper(item.get("ticker")),
        safe_upper(item.get("strategy")),
        safe_upper(item.get("final_state") or item.get("decision_state") or item.get("decision")),
        safe_text(item.get("recorded_at") or item.get("decision_generated_at")),
    ]
    return "::".join(parts)


def normalize_decision(item: dict[str, Any], origin: str) -> dict[str, Any]:
    contract = selected_contract(item)
    blockers = flatten_blockers(item)
    attribution = item.get("source_attribution") if isinstance(item.get("source_attribution"), dict) else {}
    candidate_source = safe_upper(item.get("candidate_source") or attribution.get("candidate_source"), UNKNOWN)
    confirmation_source = safe_upper(item.get("confirmation_source") or attribution.get("confirmation_source"), UNKNOWN)
    return {
        "id": decision_key(item),
        "origin": origin,
        "recorded_at": item.get("recorded_at")
        or item.get("decision_generated_at")
        or item.get("generated_at"),
        "ticker": safe_upper(item.get("ticker")),
        "strategy": safe_upper(item.get("strategy") or item.get("best_strategy") or item.get("strategy_context")),
        "final_state": safe_upper(item.get("final_state") or item.get("decision_state") or item.get("decision") or item.get("state")),
        "main_blocker": safe_upper(item.get("main_blocker") or (blockers[0] if blockers else "")),
        "blockers": blockers,
        "candidate_source": candidate_source,
        "confirmation_source": confirmation_source,
        "signal_source": infer_signal_source(item),
        "source_confidence": item.get("source_confidence") or attribution.get("source_confidence"),
        "signal_id": item.get("signal_id") or attribution.get("signal_id"),
        "snapshot_id": item.get("snapshot_id") or attribution.get("snapshot_id"),
        "manual_review_ready": bool(item.get("manual_review_ready") or item.get("ready_for_manual_review")),
        "score": safe_float(item.get("conviction_score") or item.get("ranking_score") or item.get("score")),
        "required_missing_fields": list(item.get("required_missing_fields") or []),
        "contract": {
            key: contract.get(key)
            for key in ["strike", "expiration", "dte", "bid", "ask", "mid", "spread", "spread_pct", "delta"]
            if contract.get(key) is not None
        },
        "raw": item,
    }


def normalize_outcome(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": safe_text(item.get("outcome_id") or item.get("id")),
        "decision_id": safe_text(item.get("decision_id")),
        "recorded_at": item.get("recorded_at") or item.get("evaluated_at"),
        "ticker": safe_upper(item.get("ticker")),
        "strategy": safe_upper(item.get("strategy")),
        "outcome": safe_upper(item.get("outcome") or item.get("classification")),
        "pnl_r": safe_float(item.get("pnl_r") or item.get("hypothetical_result_r") or item.get("real_trade_result_r")),
        "mfe_r": safe_float(item.get("mfe_r")),
        "mae_r": safe_float(item.get("mae_r")),
        "paper_outcome": item.get("paper_outcome"),
        "raw": item,
    }


def logical_decision_key(item: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    recorded = safe_text(item.get("recorded_at"))
    day = recorded[:10] if len(recorded) >= 10 else ""
    contract = item.get("contract") if isinstance(item.get("contract"), dict) else {}
    return (
        day,
        safe_upper(item.get("ticker")),
        safe_upper(item.get("strategy")),
        safe_upper(item.get("final_state")),
        safe_text(contract.get("expiration") or "NOEXP"),
        safe_text(contract.get("strike") if contract.get("strike") is not None else "NOSTRIKE"),
    )


def dedupe_decisions(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}
    for item in decisions:
        key = logical_decision_key(item)
        current = latest.get(key)
        if current is None or safe_text(item.get("recorded_at")) >= safe_text(current.get("recorded_at")):
            latest[key] = item
    return sorted(latest.values(), key=lambda row: safe_text(row.get("recorded_at")))


def counter_dict(counter: Counter[str], limit: int | None = None) -> dict[str, int]:
    items = counter.most_common(limit)
    return {key: value for key, value in items}


def group_decisions(decisions: list[dict[str, Any]], key: str) -> dict[str, int]:
    return counter_dict(Counter(item.get(key) or UNKNOWN for item in decisions))


def build_strategy_rows(decisions: list[dict[str, Any]], outcomes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    strategies = sorted(
        {
            item["strategy"]
            for item in decisions + outcomes
            if item.get("strategy") and item.get("strategy") != UNKNOWN
        }
    )
    rows = []
    for strategy in strategies:
        strategy_decisions = [item for item in decisions if item["strategy"] == strategy]
        strategy_outcomes = [item for item in outcomes if item["strategy"] == strategy]
        closed_outcomes = [
            item
            for item in strategy_outcomes
            if item["outcome"] in {"WIN", "LOSS", "BREAKEVEN", "EXPIRED", "CANCELLED"}
        ]
        rows.append(
            {
                "strategy": strategy,
                "decision_count": len(strategy_decisions),
                "entry_ready_count": sum(1 for item in strategy_decisions if item["final_state"] == "ENTRY_READY"),
                "manual_review_ready_count": sum(1 for item in strategy_decisions if item["manual_review_ready"]),
                "state_counts": group_decisions(strategy_decisions, "final_state"),
                "blocker_counts": group_decisions(
                    [item for item in strategy_decisions if item.get("main_blocker") != UNKNOWN],
                    "main_blocker",
                ),
                "source_counts": group_decisions(strategy_decisions, "signal_source"),
                "outcome_count": len(strategy_outcomes),
                "closed_outcomes": len(closed_outcomes),
                "sample_size_warning": len(closed_outcomes) < 30,
                "parameter_review_ready": len(closed_outcomes) >= 30,
            }
        )
    return rows


def build_missed_opportunity_rows(decisions: list[dict[str, Any]], limit: int = 100) -> list[dict[str, Any]]:
    rows = []
    for item in decisions:
        state = item.get("final_state")
        if state in {"ENTRY_READY", "UNKNOWN"}:
            continue
        blockers = item.get("blockers") or []
        rows.append(
            {
                "id": item["id"],
                "recorded_at": item.get("recorded_at"),
                "ticker": item["ticker"],
                "strategy": item["strategy"],
                "final_state": state,
                "main_blocker": item.get("main_blocker"),
                "signal_source": item.get("signal_source"),
                "score": item.get("score"),
                "missing_fields": item.get("required_missing_fields"),
                "blockers": blockers,
                "audit_question": audit_question_for_state(state, item.get("main_blocker"), blockers),
            }
        )
    return sorted(rows, key=lambda row: (safe_text(row.get("recorded_at")), row.get("ticker") or ""), reverse=True)[:limit]


def audit_question_for_state(state: str, blocker: str, blockers: list[str]) -> str:
    blocker_text = " ".join([blocker] + blockers)
    if state == "WAIT_OPTIONS_DATA":
        return "Are option-chain/liquidity fields missing, or is the candidate universe too narrow?"
    if state == "WAIT_TECHNICAL":
        return "Did TradingView/local technical confirmation fail to arrive, or was the rule too strict?"
    if state == "NO_DATA":
        return "Was the ticker absent from the scanner, stale snapshot, or missing market data?"
    if state == "RISK_BLOCKED":
        return "Was this a correct risk block, or is the risk profile missing context?"
    if "CANSLIM" in blocker_text:
        return "Did the quality filter correctly reject the setup, or should it be watchlisted?"
    if "MANUAL" in blocker_text:
        return "Does manual review need clearer promotion/rejection labels?"
    return "Review whether this was a correct filter or a missed opportunity."


def build_data_quality(decisions: list[dict[str, Any]], outcomes: list[dict[str, Any]], source_files: dict[str, bool]) -> dict[str, Any]:
    unknown_source = sum(1 for item in decisions if item["signal_source"] == UNKNOWN)
    missing_candidate_source = sum(1 for item in decisions if item.get("candidate_source") in [UNKNOWN, ""])
    missing_confirmation_source = sum(1 for item in decisions if item.get("confirmation_source") in [UNKNOWN, ""])
    closed_outcomes = sum(1 for item in outcomes if item["outcome"] in {"WIN", "LOSS", "BREAKEVEN", "EXPIRED", "CANCELLED"})
    return {
        "source_files_found": source_files,
        "decision_count": len(decisions),
        "outcome_count": len(outcomes),
        "closed_outcome_count": closed_outcomes,
        "unknown_source_decisions": unknown_source,
        "unknown_source_pct": round((unknown_source / len(decisions)) * 100, 2) if decisions else 0.0,
        "missing_candidate_source_decisions": missing_candidate_source,
        "missing_confirmation_source_decisions": missing_confirmation_source,
        "source_attribution_coverage_pct": round(
            ((len(decisions) - max(missing_candidate_source, missing_confirmation_source)) / len(decisions)) * 100,
            2,
        ) if decisions else 0.0,
        "can_review_parameters": closed_outcomes >= 30,
        "primary_gap": primary_gap(decisions, outcomes),
    }


def primary_gap(decisions: list[dict[str, Any]], outcomes: list[dict[str, Any]]) -> str:
    if not decisions:
        return "NO_DECISION_JOURNAL"
    closed_outcomes = [
        item for item in outcomes if item["outcome"] in {"WIN", "LOSS", "BREAKEVEN", "EXPIRED", "CANCELLED"}
    ]
    if len(closed_outcomes) < 30:
        return "INSUFFICIENT_OUTCOME_SAMPLE"
    unknown_source = sum(1 for item in decisions if item["signal_source"] == UNKNOWN)
    if unknown_source / len(decisions) > 0.25:
        return "SIGNAL_SOURCE_ATTRIBUTION_GAP"
    return "REVIEWABLE_SAMPLE"


def load_runtime_inputs(runtime_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, bool]]:
    decisions_payload = read_json(runtime_dir / "v32_decision_journal.json", [])
    outcomes_payload = read_json(runtime_dir / "v32_outcomes_journal.json", [])
    radar_payload = read_json(runtime_dir / "daily_radar_latest.json", {})

    decisions = [
        normalize_decision(item, "v32_decision_journal")
        for item in list_from_payload(decisions_payload, ["decisions", "rows", "items"])
    ]
    radar_items = list_from_payload(radar_payload, ["items", "all_ranked", "top_recommendations", "blocked_or_waiting"])
    decisions.extend(normalize_decision(item, "daily_radar_latest") for item in radar_items)
    decisions = dedupe_decisions(decisions)

    outcomes = [
        normalize_outcome(item)
        for item in list_from_payload(outcomes_payload, ["outcomes", "rows", "items"])
    ]
    source_files = {
        "v32_decision_journal": (runtime_dir / "v32_decision_journal.json").exists(),
        "v32_outcomes_journal": (runtime_dir / "v32_outcomes_journal.json").exists(),
        "daily_radar_latest": (runtime_dir / "daily_radar_latest.json").exists(),
        "intraday_futures_alert_events": (runtime_dir / "intraday_futures_alert_events.json").exists(),
        "signals_history": (runtime_dir / "signals_history.json").exists(),
        "tradingview_signal_ledger": (runtime_dir / "v32_signal_events.json").exists(),
        "ibkr_chain_coverage": (runtime_dir / "v32_ibkr_chain_coverage.json").exists(),
    }
    return decisions, outcomes, source_files


def build_alert_opportunity_audit(runtime_dir: Path, generated_at: str | None = None) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    decisions, outcomes, source_files = load_runtime_inputs(runtime_dir)
    state_counts = group_decisions(decisions, "final_state")
    blocker_counts = group_decisions(
        [item for item in decisions if item.get("main_blocker") != UNKNOWN],
        "main_blocker",
    )
    source_counts = group_decisions(decisions, "signal_source")
    strategy_rows = build_strategy_rows(decisions, outcomes)
    return {
        "engine": "ALERT_OPPORTUNITY_DEEP_AUDIT",
        "audit_version": AUDIT_VERSION,
        "generated_at": generated_at,
        "runtime_dir": str(runtime_dir),
        "summary": {
            "decision_count": len(decisions),
            "entry_ready_count": state_counts.get("ENTRY_READY", 0),
            "blocked_or_waiting_count": sum(
                count for state, count in state_counts.items() if state not in {"ENTRY_READY", UNKNOWN}
            ),
            "outcome_count": len(outcomes),
            "closed_outcome_count": sum(
                1 for item in outcomes if item["outcome"] in {"WIN", "LOSS", "BREAKEVEN", "EXPIRED", "CANCELLED"}
            ),
            "state_counts": state_counts,
            "blocker_counts": blocker_counts,
            "source_counts": source_counts,
        },
        "data_quality": build_data_quality(decisions, outcomes, source_files),
        "strategy_coverage": strategy_rows,
        "missed_opportunity_review": build_missed_opportunity_rows(decisions),
        "recommendations": recommendations(state_counts, source_counts, outcomes, source_files),
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def recommendations(
    state_counts: dict[str, int],
    source_counts: dict[str, int],
    outcomes: list[dict[str, Any]],
    source_files: dict[str, bool],
) -> list[str]:
    recs = []
    closed = sum(1 for item in outcomes if item["outcome"] in {"WIN", "LOSS", "BREAKEVEN", "EXPIRED", "CANCELLED"})
    if source_counts.get(UNKNOWN, 0):
        recs.append("Tag every decision with candidate_source and confirmation_source before changing strategy thresholds.")
    if not source_files.get("intraday_futures_alert_events"):
        recs.append("Persist or export TradingView/intraday alert events so alert volume can be compared with local candidates.")
    if closed < 30:
        recs.append("Accumulate at least 30 closed/paper outcomes before promoting parameter changes to production rules.")
    if state_counts.get("WAIT_TECHNICAL", 0):
        recs.append("Compare WAIT_TECHNICAL rows against TradingView and local technical snapshots to identify missing confirmations.")
    if state_counts.get("WAIT_OPTIONS_DATA", 0):
        recs.append("Review WAIT_OPTIONS_DATA rows for option-chain coverage, spread thresholds, bid/ask availability, and universe breadth.")
    if not recs:
        recs.append("Sample is reviewable; inspect strategy_coverage and missed_opportunity_review before versioning rule changes.")
    return recs


CSV_FIELDS = [
    "id",
    "recorded_at",
    "ticker",
    "strategy",
    "final_state",
    "main_blocker",
    "signal_source",
    "score",
    "missing_fields",
    "blockers",
    "audit_question",
]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            serialized = dict(row)
            serialized["missing_fields"] = json.dumps(serialized.get("missing_fields") or [])
            serialized["blockers"] = json.dumps(serialized.get("blockers") or [])
            writer.writerow({field: serialized.get(field) for field in CSV_FIELDS})
