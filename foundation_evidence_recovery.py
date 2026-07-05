"""Recover foundation evidence from existing Stock Ultimus runtime files.

The recovery flow is evidence-only. It does not fetch live market data, does
not synthesize alerts, and does not authorize orders.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import foundation_health
import ibkr_diagnostics
import outcome_backfill
import source_attribution
import tradingview_signal_ledger


RECOVERY_VERSION = "foundation_evidence_recovery_v1"
DEFAULT_AUDIT_FILE = "foundation_evidence_recovery_latest.json"


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
    for key in keys or ["items", "rows", "decisions", "outcomes", "events", "signals"]:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def replace_list(original: Any, rows: list[dict[str, Any]], keys: list[str] | None = None) -> Any:
    if isinstance(original, list):
        return rows
    if isinstance(original, dict):
        clone = dict(original)
        for key in keys or ["decisions", "rows", "items"]:
            if isinstance(clone.get(key), list):
                clone[key] = rows
                return clone
        clone["items"] = rows
        return clone
    return rows


def has_value(value: Any) -> bool:
    return outcome_backfill.has_value(value)


def missing_source(value: Any) -> bool:
    return not has_value(value)


def backfill_decision_sources(
    runtime_dir: str | Path,
    *,
    generated_at: str | None = None,
    write: bool = False,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    generated_at = generated_at or now_iso()
    path = runtime / "v32_decision_journal.json"
    payload = read_json(path, [])
    decisions = list_from_payload(payload, ["decisions", "rows", "items"])
    repaired_rows = []
    changed_count = 0
    field_counts: Counter[str] = Counter()
    unresolved_count = 0
    samples = []

    for decision in decisions:
        repaired = dict(decision)
        attribution = source_attribution.build_source_attribution(repaired, repaired.get("source_decision"))
        repaired_fields = []
        for field in [
            "candidate_source",
            "confirmation_source",
            "signal_source",
            "source_confidence",
            "signal_id",
            "snapshot_id",
            "data_lineage",
        ]:
            if missing_source(repaired.get(field)) and has_value(attribution.get(field)):
                repaired[field] = attribution.get(field)
                repaired_fields.append(field)
                field_counts[field] += 1
        if not isinstance(repaired.get("source_attribution"), dict):
            repaired["source_attribution"] = attribution
            repaired_fields.append("source_attribution")
            field_counts["source_attribution"] += 1

        gaps = source_attribution.entry_ready_evidence_gaps(repaired) if repaired.get("final_state") == "ENTRY_READY" else []
        if repaired_fields or not isinstance(decision.get("source_backfill_audit"), dict):
            repaired["source_backfill_audit"] = {
                "recovery_version": RECOVERY_VERSION,
                "generated_at": generated_at,
                "repaired_fields": repaired_fields,
                "entry_ready_evidence_gaps": gaps,
                "manual_review_required": True,
                "execution_authorized": False,
                "not_order_instruction": True,
            }
        repaired["not_order_instruction"] = True
        repaired["execution_authorized"] = False
        if repaired_fields:
            changed_count += 1
        if gaps:
            unresolved_count += 1
        if repaired_fields and len(samples) < 20:
            samples.append(
                {
                    "decision_id": repaired.get("decision_id"),
                    "ticker": repaired.get("ticker"),
                    "strategy": repaired.get("strategy"),
                    "final_state": repaired.get("final_state"),
                    "repaired_fields": repaired_fields,
                    "entry_ready_evidence_gaps": gaps,
                }
            )
        repaired_rows.append(repaired)

    if write:
        write_json(path, replace_list(payload, repaired_rows, ["decisions", "rows", "items"]))

    return {
        "engine": "SOURCE_ATTRIBUTION_HISTORICAL_BACKFILL",
        "recovery_version": RECOVERY_VERSION,
        "generated_at": generated_at,
        "dry_run": not write,
        "decision_count": len(decisions),
        "changed_count": changed_count,
        "field_update_counts": dict(sorted(field_counts.items())),
        "entry_ready_with_unresolved_gaps": unresolved_count,
        "samples": samples,
        "write_status": "WROTE_DECISION_JOURNAL" if write else "DRY_RUN_ONLY",
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def _contract_has_any_value(contract: dict[str, Any]) -> bool:
    return any(has_value(contract.get(field)) for field in ["strike", "expiration", "dte", "bid", "ask", "mid", "delta", "iv"])


def _decision_contract_row(decision: dict[str, Any], origin: str) -> dict[str, Any] | None:
    contract = decision.get("selected_contract") if isinstance(decision.get("selected_contract"), dict) else {}
    if not _contract_has_any_value(contract):
        return None
    row = dict(contract)
    row["ticker"] = row.get("ticker") or decision.get("ticker")
    row["strategy"] = row.get("strategy") or decision.get("strategy")
    row["decision_id"] = decision.get("decision_id") or decision.get("id")
    row["signal_id"] = decision.get("signal_id")
    row["decision"] = decision.get("final_state") or decision.get("decision")
    row["market_data_source"] = row.get("option_market_data_source") or row.get("market_data_source") or origin
    row["runtime_recovery_origin"] = origin
    row["not_order_instruction"] = True
    return row


def _runtime_decision_rows(runtime: Path) -> list[dict[str, Any]]:
    rows = []
    for filename, keys, origin in [
        ("v32_decision_journal.json", ["decisions", "rows", "items"], "v32_decision_journal"),
        ("daily_radar_latest.json", ["items", "all_ranked", "top_recommendations", "blocked_or_waiting"], "daily_radar_latest"),
    ]:
        payload = read_json(runtime / filename, [])
        for item in list_from_payload(payload, keys):
            row = _decision_contract_row(item, origin)
            if row:
                rows.append(row)
    deduped = []
    seen = set()
    for row in rows:
        key = (
            str(row.get("ticker") or ""),
            str(row.get("strategy") or ""),
            str(row.get("expiration") or ""),
            str(row.get("strike") or ""),
            str(row.get("decision_id") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def recover_ibkr_diagnostics(
    runtime_dir: str | Path,
    *,
    generated_at: str | None = None,
    write: bool = False,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    generated_at = generated_at or now_iso()
    option_rows = _runtime_decision_rows(runtime)
    symbols = sorted({str(row.get("ticker") or "").upper() for row in option_rows if row.get("ticker")})
    chain_events = [
        {
            "ticker": symbol,
            "status": "CHAIN_RECOVERED_FROM_RUNTIME_EVIDENCE",
            "source": "v32_decision_journal_or_daily_radar",
            "not_order_instruction": True,
        }
        for symbol in symbols
    ]
    diagnostic = ibkr_diagnostics.build_cycle_diagnostic(
        symbols=symbols,
        chain_events=chain_events,
        option_rows=option_rows,
        generated_at=generated_at,
    )
    diagnostic["runtime_recovery"] = {
        "recovery_version": RECOVERY_VERSION,
        "source": "local_runtime_saved_contracts",
        "write_mode": bool(write),
        "does_not_fetch_live_market_data": True,
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    saved = None
    if write:
        saved = ibkr_diagnostics.write_cycle_diagnostic(diagnostic, runtime / "v32_ibkr_chain_coverage.json")
    return {
        "engine": "IBKR_DIAGNOSTICS_RUNTIME_RECOVERY",
        "recovery_version": RECOVERY_VERSION,
        "generated_at": generated_at,
        "dry_run": not write,
        "symbols_recovered": symbols,
        "option_row_count": len(option_rows),
        "primary_gap": diagnostic.get("primary_gap"),
        "missing_execution_field_counts": diagnostic.get("missing_execution_field_counts") or {},
        "discard_reason_counts": diagnostic.get("discard_reason_counts") or {},
        "diagnostic": diagnostic,
        "saved": saved,
        "write_status": "WROTE_IBKR_DIAGNOSTIC" if write else "DRY_RUN_ONLY",
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def _looks_like_tradingview_payload(item: dict[str, Any]) -> bool:
    haystack = json.dumps(item, sort_keys=True, default=str).upper()
    if "TRADINGVIEW" in haystack or "TRADING_VIEW" in haystack:
        return True
    technical_fields = {"vwap", "opening_range_high", "opening_range_low", "adx", "atr", "volume_relative"}
    return bool(item.get("ticker") or item.get("symbol")) and any(field in item for field in technical_fields)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text().splitlines():
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def replay_tradingview_ledger(
    runtime_dir: str | Path,
    *,
    generated_at: str | None = None,
    write: bool = False,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    generated_at = generated_at or now_iso()
    candidates = []
    source_files = []
    for filename in ["intraday_futures_alert_events.json", "signals_history.json", "technical_alert_events.json"]:
        path = runtime / filename
        if path.exists():
            source_files.append(str(path))
            candidates.extend(list_from_payload(read_json(path, []), ["events", "signals", "items", "rows"]))
    audit_jsonl = runtime / "daily_radar_audit.jsonl"
    if audit_jsonl.exists():
        source_files.append(str(audit_jsonl))
        candidates.extend(_load_jsonl(audit_jsonl))

    replayable = [item for item in candidates if _looks_like_tradingview_payload(item)]
    results = []
    if write:
        for item in replayable:
            results.append(
                tradingview_signal_ledger.append_signal_event(
                    item,
                    raw_text=json.dumps(item, sort_keys=True, default=str),
                    endpoint="runtime_replay",
                    path=runtime / "v32_signal_events.json",
                )
            )
    existing = tradingview_signal_ledger.load_signal_events(runtime / "v32_signal_events.json", limit=20000)
    return {
        "engine": "TRADINGVIEW_LEDGER_RUNTIME_REPLAY",
        "recovery_version": RECOVERY_VERSION,
        "generated_at": generated_at,
        "dry_run": not write,
        "source_files": source_files,
        "candidate_payload_count": len(candidates),
        "replayable_payload_count": len(replayable),
        "recorded_count": sum(1 for item in results if item.get("status") == "RECORDED"),
        "duplicate_count": sum(1 for item in results if item.get("status") == "DUPLICATE"),
        "existing_event_count": len(existing),
        "write_status": "WROTE_TRADINGVIEW_LEDGER" if write else "DRY_RUN_ONLY",
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def collection_readiness(payload: dict[str, Any]) -> dict[str, Any]:
    health = payload.get("foundation_health") if isinstance(payload.get("foundation_health"), dict) else {}
    outcome_report = payload.get("outcome_backfill") if isinstance(payload.get("outcome_backfill"), dict) else {}
    source_report = payload.get("source_attribution_backfill") if isinstance(payload.get("source_attribution_backfill"), dict) else {}
    tv_report = payload.get("tradingview_ledger_replay") if isinstance(payload.get("tradingview_ledger_replay"), dict) else {}
    ibkr_report = payload.get("ibkr_diagnostics_recovery") if isinstance(payload.get("ibkr_diagnostics_recovery"), dict) else {}
    blockers = []
    if health.get("status") != "OK":
        blockers.append("FOUNDATION_HEALTH_NOT_OK")
    if int(outcome_report.get("complete_after_count") or 0) < 30:
        blockers.append("INSUFFICIENT_COMPLETE_OUTCOMES")
    if int(tv_report.get("existing_event_count") or 0) <= 0:
        blockers.append("NO_TRADINGVIEW_LEDGER_EVENTS")
    if ibkr_report.get("primary_gap") != "COVERAGE_REVIEWABLE":
        blockers.append("IBKR_CHAIN_COVERAGE_NOT_REVIEWABLE")
    if int(source_report.get("entry_ready_with_unresolved_gaps") or 0) > 0:
        blockers.append("ENTRY_READY_SOURCE_GAPS_REMAIN")
    return {
        "engine": "FOUNDATION_EVIDENCE_COLLECTION_READINESS",
        "recovery_version": RECOVERY_VERSION,
        "status": "READY_FOR_SAMPLE_COLLECTION" if not blockers else "COLLECT_MORE_EVIDENCE",
        "blockers": blockers,
        "minimum_complete_outcomes_per_strategy_regime": 30,
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def recover_foundation_evidence(
    runtime_dir: str | Path,
    *,
    generated_at: str | None = None,
    write: bool = False,
    audit_out: str | Path | None = None,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    generated_at = generated_at or now_iso()
    source_report = backfill_decision_sources(runtime, generated_at=generated_at, write=write)
    ibkr_report = recover_ibkr_diagnostics(runtime, generated_at=generated_at, write=write)
    tv_report = replay_tradingview_ledger(runtime, generated_at=generated_at, write=write)
    outcome_report = outcome_backfill.build_backfill_report(
        runtime,
        generated_at=generated_at,
        write=write,
        audit_out=runtime / "outcome_backfill_audit_latest.json" if write else None,
    )
    health = foundation_health.build_foundation_health(runtime, generated_at=generated_at)
    payload = {
        "engine": "FOUNDATION_EVIDENCE_RECOVERY",
        "recovery_version": RECOVERY_VERSION,
        "generated_at": generated_at,
        "runtime_dir": str(runtime),
        "dry_run": not write,
        "source_attribution_backfill": source_report,
        "ibkr_diagnostics_recovery": {
            key: value for key, value in ibkr_report.items() if key != "diagnostic"
        },
        "tradingview_ledger_replay": tv_report,
        "outcome_backfill": outcome_report,
        "foundation_health": {
            "status": health.get("status"),
            "priorities": health.get("priorities") or [],
            "performance_summary": health.get("performance_summary") or {},
            "outcome_completeness_summary": health.get("outcome_completeness_summary") or {},
            "parameter_review_summary": health.get("parameter_review_summary") or {},
        },
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    payload["collection_readiness"] = collection_readiness(payload)
    if audit_out:
        write_json(Path(audit_out), payload)
    elif write:
        write_json(runtime / DEFAULT_AUDIT_FILE, payload)
    return payload
