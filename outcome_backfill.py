"""Backfill paper outcome evidence from existing Stock Ultimus runtime data.

This module is intentionally conservative: it only fills missing outcome fields
when the value can be derived from saved decisions, follow-ups, signal events,
or diagnostics. It never fabricates market data and never authorizes orders.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import market_regime_detector
import source_attribution
import strategy_performance
import tradingview_signal_ledger


OUTCOME_BACKFILL_VERSION = "outcome_backfill_repair_v1"
DEFAULT_OUTCOMES_FILE = "v32_outcomes_journal.json"
DEFAULT_DECISIONS_FILE = "v32_decision_journal.json"
DEFAULT_AUDIT_FILE = "outcome_backfill_audit_latest.json"
MISSING_SOURCE_VALUES = {
    "",
    "UNKNOWN",
    "NONE",
    "NO_CANDIDATE_SOURCE",
    "NO_CONFIRMATION_SOURCE",
}


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


def list_from_payload(payload: Any, keys: list[str] | None = None) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in keys or ["outcomes", "decisions", "rows", "items", "events"]:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def replace_list_in_payload(original: Any, rows: list[dict[str, Any]], keys: list[str] | None = None) -> Any:
    if isinstance(original, list):
        return rows
    if isinstance(original, dict):
        clone = dict(original)
        for key in keys or ["outcomes", "rows", "items"]:
            if isinstance(clone.get(key), list):
                clone[key] = rows
                return clone
        clone["outcomes"] = rows
        return clone
    return rows


def has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip()) and value.strip().upper() not in MISSING_SOURCE_VALUES
    return True


def safe_upper(value: Any, default: str = "") -> str:
    text = str(value or "").strip().upper()
    return text or default


def safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        result = float(value)
        if result != result or result in {float("inf"), float("-inf")}:
            return None
        return result
    except Exception:
        return None


def outcome_key(outcome: dict[str, Any]) -> str:
    for key in ["outcome_id", "id", "signal_id", "decision_id"]:
        if has_value(outcome.get(key)):
            return str(outcome.get(key))
    return "::".join(
        str(part)
        for part in [
            safe_upper(outcome.get("ticker"), "UNKNOWN"),
            safe_upper(outcome.get("strategy"), "UNKNOWN"),
            outcome.get("recorded_at") or outcome.get("evaluated_at") or "",
        ]
    )


def decision_indexes(decisions: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    by_decision_id: dict[str, dict[str, Any]] = {}
    by_signal_id: dict[str, dict[str, Any]] = {}
    by_latest_outcome_id: dict[str, dict[str, Any]] = {}
    for decision in decisions:
        if has_value(decision.get("decision_id")):
            by_decision_id[str(decision.get("decision_id"))] = decision
        if has_value(decision.get("signal_id")):
            by_signal_id[str(decision.get("signal_id"))] = decision
        latest = decision.get("latest_outcome") if isinstance(decision.get("latest_outcome"), dict) else {}
        if has_value(latest.get("outcome_id")):
            by_latest_outcome_id[str(latest.get("outcome_id"))] = decision
    return {
        "by_decision_id": by_decision_id,
        "by_signal_id": by_signal_id,
        "by_latest_outcome_id": by_latest_outcome_id,
    }


def match_decision(outcome: dict[str, Any], indexes: dict[str, dict[str, dict[str, Any]]]) -> tuple[dict[str, Any] | None, str]:
    decision_id = str(outcome.get("decision_id") or "")
    signal_id = str(outcome.get("signal_id") or "")
    out_id = str(outcome.get("outcome_id") or outcome.get("id") or "")
    if decision_id and decision_id in indexes["by_decision_id"]:
        return indexes["by_decision_id"][decision_id], "decision_id"
    if signal_id and signal_id in indexes["by_signal_id"]:
        return indexes["by_signal_id"][signal_id], "signal_id"
    if out_id and out_id in indexes["by_latest_outcome_id"]:
        return indexes["by_latest_outcome_id"][out_id], "latest_outcome.outcome_id"
    return None, "NO_DECISION_MATCH"


def contract_from_decision(decision: dict[str, Any]) -> dict[str, Any]:
    contract = decision.get("selected_contract")
    return contract if isinstance(contract, dict) else {}


def contract_match_key(source: dict[str, Any]) -> tuple[str, str, str, str]:
    source = source if isinstance(source, dict) else {}
    return (
        safe_upper(source.get("ticker") or source.get("symbol"), ""),
        safe_upper(source.get("strategy") or source.get("strategy_hint"), ""),
        str(source.get("expiration") or source.get("expiry") or ""),
        str(source.get("strike") or ""),
    )


def ibkr_option_row_lookup(ibkr_diagnostic: dict[str, Any] | None) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    payload = ibkr_diagnostic if isinstance(ibkr_diagnostic, dict) else {}
    lookup: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in payload.get("option_rows") or []:
        if not isinstance(row, dict):
            continue
        key = contract_match_key(row)
        if key[0] and key[2] and key[3]:
            lookup[key] = row
    return lookup


def fill_field(target: dict[str, Any], field: str, value: Any, source: str, repairs: list[dict[str, Any]]) -> None:
    if has_value(target.get(field)) or not has_value(value):
        return
    target[field] = value
    repairs.append({"field": field, "source": source})


def fill_contract(target: dict[str, Any], decision: dict[str, Any], repairs: list[dict[str, Any]]) -> None:
    contract = target.get("selected_contract") if isinstance(target.get("selected_contract"), dict) else {}
    source_contract = contract_from_decision(decision)
    if not source_contract:
        return
    changed = []
    for field in [
        "strike",
        "expiration",
        "dte",
        "bid",
        "ask",
        "mid",
        "spread",
        "spread_pct",
        "delta",
        "iv",
        "volume",
        "open_interest",
        "option_market_data_source",
        "option_market_data_attempts",
        "option_discard_reasons",
        "data_quality",
    ]:
        value = source_contract.get(field)
        if field == "iv" and not has_value(value):
            value = source_contract.get("implied_volatility")
        if not has_value(contract.get(field)) and has_value(value):
            contract[field] = value
            changed.append(field)
    if changed:
        target["selected_contract"] = contract
        repairs.append({"field": "selected_contract", "source": "matched_decision.selected_contract", "fields": changed})


def fill_contract_from_ibkr_diagnostic(
    target: dict[str, Any],
    lookup: dict[tuple[str, str, str, str], dict[str, Any]],
    repairs: list[dict[str, Any]],
) -> None:
    contract = target.get("selected_contract") if isinstance(target.get("selected_contract"), dict) else {}
    key_source = {
        "ticker": target.get("ticker") or contract.get("ticker"),
        "strategy": target.get("strategy") or contract.get("strategy"),
        "expiration": contract.get("expiration"),
        "strike": contract.get("strike"),
    }
    row = lookup.get(contract_match_key(key_source))
    if not row:
        key_without_strategy = (
            safe_upper(key_source.get("ticker"), ""),
            "",
            str(key_source.get("expiration") or ""),
            str(key_source.get("strike") or ""),
        )
        row = next(
            (
                candidate
                for candidate_key, candidate in lookup.items()
                if (candidate_key[0], "", candidate_key[2], candidate_key[3]) == key_without_strategy
            ),
            None,
        )
    if not row:
        return

    changed = []
    for field in [
        "bid",
        "ask",
        "mid",
        "spread",
        "spread_pct",
        "delta",
        "iv",
        "volume",
        "open_interest",
        "option_market_data_source",
        "market_data_source",
        "market_data_attempts",
        "data_quality",
    ]:
        target_field = "option_market_data_source" if field == "market_data_source" else field
        value = row.get(field)
        if field == "iv" and not has_value(value):
            value = row.get("implied_volatility")
        if not has_value(contract.get(target_field)) and has_value(value):
            contract[target_field] = value
            changed.append(target_field)
    if changed:
        target["selected_contract"] = contract
        repairs.append({"field": "selected_contract", "source": "ibkr_chain_coverage.option_rows", "fields": changed})


def pnl_observations(outcome: dict[str, Any], decision: dict[str, Any]) -> list[float]:
    values: list[float] = []
    for source in [
        outcome.get("latest_auto_evaluation"),
        outcome.get("latest_manual_review_evaluation"),
    ]:
        if isinstance(source, dict):
            for key in ["current_paper_pnl_r", "pnl_r", "observed_mfe_r", "observed_mae_r"]:
                value = safe_float(source.get(key))
                if value is not None:
                    values.append(value)
    for key in ["auto_evaluations", "manual_review_auto_evaluations"]:
        for item in outcome.get(key) or []:
            if isinstance(item, dict):
                value = safe_float(item.get("current_paper_pnl_r") or item.get("pnl_r"))
                if value is not None:
                    values.append(value)
    latest_outcome = decision.get("latest_outcome") if isinstance(decision.get("latest_outcome"), dict) else {}
    for key in ["pnl_r", "hypothetical_result_r", "real_trade_result_r"]:
        value = safe_float(latest_outcome.get(key))
        if value is not None:
            values.append(value)
    for followup in decision.get("followups") or []:
        if isinstance(followup, dict):
            value = safe_float(followup.get("pnl_r") or followup.get("current_paper_pnl_r"))
            if value is not None:
                values.append(value)
    return values


def fill_outcome_metrics(target: dict[str, Any], decision: dict[str, Any], repairs: list[dict[str, Any]]) -> None:
    observations = pnl_observations(target, decision)
    if observations:
        fill_field(target, "pnl_r", observations[-1], "pnl_observations.latest", repairs)
        fill_field(target, "mfe_r", round(max(observations), 4), "pnl_observations.max", repairs)
        fill_field(target, "mae_r", round(min(observations), 4), "pnl_observations.min", repairs)
        return

    summary = decision.get("followup_summary") if isinstance(decision.get("followup_summary"), dict) else {}
    fill_field(target, "mfe_r", summary.get("mfe_r"), "matched_decision.followup_summary", repairs)
    fill_field(target, "mae_r", summary.get("mae_r"), "matched_decision.followup_summary", repairs)


def fill_sources(target: dict[str, Any], decision: dict[str, Any], repairs: list[dict[str, Any]]) -> None:
    attribution = decision.get("source_attribution")
    if not isinstance(attribution, dict):
        attribution = source_attribution.build_source_attribution(decision, decision.get("source_decision"))
    for field in [
        "candidate_source",
        "confirmation_source",
        "signal_source",
        "source_confidence",
        "signal_id",
        "snapshot_id",
        "data_lineage",
        "source_attribution",
    ]:
        fill_field(target, field, attribution.get(field), "source_attribution.from_matched_decision", repairs)


def fill_regime(target: dict[str, Any], decision: dict[str, Any], repairs: list[dict[str, Any]]) -> None:
    if has_value(target.get("market_regime")):
        return
    for source in [
        target,
        decision,
        decision.get("regime_overlay") if isinstance(decision.get("regime_overlay"), dict) else {},
        decision.get("market") if isinstance(decision.get("market"), dict) else {},
    ]:
        if isinstance(source, dict):
            regime = market_regime_detector.explicit_regime(source)
            if regime:
                target["market_regime"] = regime
                repairs.append({"field": "market_regime", "source": "explicit_regime"})
                return

    detected = market_regime_detector.detect_market_regime(
        decision.get("market") if isinstance(decision.get("market"), dict) else {},
        {"primary": decision.get("technical")} if isinstance(decision.get("technical"), dict) else {},
    )
    if detected.get("market_regime") and detected.get("market_regime") != "UNKNOWN":
        target["market_regime"] = detected.get("market_regime")
        target["regime_detection"] = target.get("regime_detection") or detected
        repairs.append({"field": "market_regime", "source": "market_regime_detector"})


def unresolved_fields(outcome: dict[str, Any]) -> list[str]:
    diagnostic = strategy_performance.outcome_completeness(outcome)
    unresolved = list(diagnostic.get("missing_fields") or [])
    unresolved.extend(f"selected_contract.{field}" for field in diagnostic.get("missing_contract_fields") or [])
    return unresolved


def repair_outcome(
    outcome: dict[str, Any],
    decision: dict[str, Any] | None,
    match_source: str,
    generated_at: str,
    ibkr_lookup: dict[tuple[str, str, str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    original = dict(outcome or {})
    repaired = dict(outcome or {})
    repairs: list[dict[str, Any]] = []
    if decision:
        fill_sources(repaired, decision, repairs)
        fill_contract(repaired, decision, repairs)
        fill_regime(repaired, decision, repairs)
        fill_outcome_metrics(repaired, decision, repairs)
    fill_contract_from_ibkr_diagnostic(repaired, ibkr_lookup or {}, repairs)

    unresolved = unresolved_fields(repaired)
    evidence_changed = bool(repairs)
    if repairs or not isinstance(original.get("backfill_audit"), dict):
        repaired["backfill_audit"] = {
            "outcome_backfill_version": OUTCOME_BACKFILL_VERSION,
            "generated_at": generated_at,
            "matched_decision_id": decision.get("decision_id") if decision else None,
            "match_source": match_source,
            "repaired_fields": repairs,
            "unresolved_fields": unresolved,
            "complete_after_backfill": not unresolved and strategy_performance.outcome_completeness(repaired).get("complete") is True,
            "manual_review_required": True,
            "execution_authorized": False,
            "not_order_instruction": True,
        }
    if repaired.get("not_order_instruction") is not True:
        repaired["not_order_instruction"] = True
        evidence_changed = True
    if repaired.get("execution_authorized") is not False:
        repaired["execution_authorized"] = False
        evidence_changed = True
    return {
        "original": original,
        "outcome": repaired,
        "changed": evidence_changed,
        "repaired_fields": repairs,
        "unresolved_fields": unresolved,
    }


def build_backfill_report(
    runtime_dir: str | Path,
    *,
    generated_at: str | None = None,
    write: bool = False,
    audit_out: str | Path | None = None,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    generated_at = generated_at or now_iso()
    outcomes_path = runtime / DEFAULT_OUTCOMES_FILE
    decisions_path = runtime / DEFAULT_DECISIONS_FILE
    outcomes_payload = read_json(outcomes_path, [])
    decisions_payload = read_json(decisions_path, [])
    outcomes = list_from_payload(outcomes_payload, ["outcomes", "rows", "items"])
    decisions = list_from_payload(decisions_payload, ["decisions", "rows", "items"])
    indexes = decision_indexes(decisions)
    tv_events = tradingview_signal_ledger.load_signal_events(runtime / "v32_signal_events.json", limit=20000)
    ibkr_diagnostic = read_json(runtime / "v32_ibkr_chain_coverage.json", {})
    ibkr_lookup = ibkr_option_row_lookup(ibkr_diagnostic)

    repaired_rows = []
    repair_summaries = []
    field_counts: Counter[str] = Counter()
    unresolved_counts: Counter[str] = Counter()
    changed_count = 0

    for outcome in outcomes:
        decision, match_source = match_decision(outcome, indexes)
        result = repair_outcome(outcome, decision, match_source, generated_at, ibkr_lookup)
        repaired = result["outcome"]
        repaired_rows.append(repaired)
        if result["changed"]:
            changed_count += 1
        for repair in result["repaired_fields"]:
            field_counts[str(repair.get("field"))] += 1
        for field in result["unresolved_fields"]:
            unresolved_counts[field] += 1
        repair_summaries.append(
            {
                "outcome_id": repaired.get("outcome_id") or repaired.get("id"),
                "decision_id": repaired.get("decision_id"),
                "ticker": repaired.get("ticker"),
                "strategy": repaired.get("strategy"),
                "changed": result["changed"],
                "repaired_fields": result["repaired_fields"],
                "unresolved_fields": result["unresolved_fields"],
                "match_source": match_source,
                "matched_decision_id": decision.get("decision_id") if decision else None,
            }
        )

    payload_to_write = replace_list_in_payload(outcomes_payload, repaired_rows, ["outcomes", "rows", "items"])
    if write:
        write_json(outcomes_path, payload_to_write)

    report = {
        "engine": "OUTCOME_EVIDENCE_BACKFILL",
        "outcome_backfill_version": OUTCOME_BACKFILL_VERSION,
        "generated_at": generated_at,
        "runtime_dir": str(runtime),
        "dry_run": not write,
        "outcomes_file": str(outcomes_path),
        "outcome_count": len(outcomes),
        "decision_count": len(decisions),
        "changed_count": changed_count,
        "complete_after_count": sum(
            1 for item in repaired_rows if strategy_performance.outcome_completeness(item).get("complete") is True
        ),
        "field_update_counts": dict(sorted(field_counts.items())),
        "unresolved_field_counts": dict(sorted(unresolved_counts.items())),
        "matched_decision_count": sum(1 for item in repair_summaries if item.get("matched_decision_id")),
        "unmatched_outcome_count": sum(1 for item in repair_summaries if not item.get("matched_decision_id")),
        "tradingview_signal_event_count": len(tv_events),
        "ibkr_diagnostic_present": isinstance(ibkr_diagnostic, dict) and bool(ibkr_diagnostic),
        "repairs": repair_summaries[:100],
        "write_status": "WROTE_OUTCOMES" if write else "DRY_RUN_ONLY",
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    if audit_out:
        write_json(Path(audit_out), report)
    elif write:
        write_json(runtime / DEFAULT_AUDIT_FILE, report)
    return report
