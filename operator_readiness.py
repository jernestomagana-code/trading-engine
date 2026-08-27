"""Operator readiness reports for market-open and post-open monitoring.

These reports are evidence-only. They do not authorize orders, do not change
strategy parameters, and do not write synthetic market evidence.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import foundation_health
import operational_evidence_gate
import tradingview_operational_health


OPERATOR_READINESS_VERSION = "operator_readiness_v1"
MARKET_OPEN_CHECKLIST_VERSION = "market_open_checklist_v1"
POST_OPEN_MONITOR_VERSION = "post_open_monitor_v1"
DEFAULT_RUNTIME_DIR = Path("runtime")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _capability_allowed(gate: dict[str, Any], name: str) -> bool:
    capabilities = gate.get("capabilities") if isinstance(gate.get("capabilities"), dict) else {}
    capability = capabilities.get(name) if isinstance(capabilities.get(name), dict) else {}
    return capability.get("allowed") is True


def _capability_blockers(gate: dict[str, Any], name: str) -> list[str]:
    capabilities = gate.get("capabilities") if isinstance(gate.get("capabilities"), dict) else {}
    capability = capabilities.get(name) if isinstance(capabilities.get(name), dict) else {}
    return [str(item) for item in capability.get("blockers") or [] if item]


def _ibkr_primary_gap(runtime: Path) -> str:
    payload = read_json(runtime / "v32_ibkr_chain_coverage.json", {})
    if not isinstance(payload, dict):
        return "NO_IBKR_OPTION_DIAGNOSTICS"
    return str(payload.get("primary_gap") or "NO_IBKR_OPTION_DIAGNOSTICS")


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _ibkr_connected(runtime: Path, generated_at: str, max_age_seconds: int = 900) -> bool:
    """Use the fresh multi-account control tower as connection evidence.

    Option-chain coverage and broker connectivity are separate facts.  Missing
    chain diagnostics must not be presented to the operator as a disconnected
    or generally unreviewable IBKR session.
    """
    tower = read_json(runtime / "broker_control_tower_latest.json", {})
    accounts = [item for item in (tower.get("accounts") or []) if isinstance(item, dict)] if isinstance(tower, dict) else []
    tower_time = _parse_timestamp(tower.get("generated_at") if isinstance(tower, dict) else None)
    check_time = _parse_timestamp(generated_at)
    fresh = bool(tower_time and check_time and 0 <= (check_time - tower_time).total_seconds() <= max_age_seconds)
    return bool(
        fresh
        and str(tower.get("status") or "").upper() == "READY"
        and accounts
        and all(str(item.get("refresh_status") or "").upper() == "READY" for item in accounts)
    )


def _classify_go_no_go(
    foundation: dict[str, Any],
    gate: dict[str, Any],
    tv_bundle: dict[str, Any],
    ibkr_gap: str,
) -> tuple[str, str, list[str]]:
    reasons = []
    if foundation.get("status") == "FAIL":
        priorities = foundation.get("priorities") if isinstance(foundation.get("priorities"), list) else []
        return "FOUNDATION_BLOCKED", "Resolver Foundation Health antes de usar el motor.", priorities[:3]
    if gate.get("state") == "FOUNDATION_BLOCKED":
        reasons = gate.get("blocked_reasons") if isinstance(gate.get("blocked_reasons"), list) else []
        return "FOUNDATION_BLOCKED", "Resolver Operational Evidence Gate antes de revisar senales.", reasons[:5]
    if tv_bundle.get("coverage_valid") is not True:
        return "TV_CONFIG_BLOCKED", "Corregir matrices/contratos TradingView antes de apertura.", tv_bundle.get("blockers") or []
    if tv_bundle.get("real_e2e_confirmed") is not True:
        missing = tv_bundle.get("missing_required_event_codes_by_coverage") or {}
        return "WAITING_TV", "Esperar payloads reales de TradingView; no usar evidencia local como confirmacion real.", list(missing.keys())
    if ibkr_gap != "COVERAGE_REVIEWABLE":
        return "WAITING_IBKR", "Refrescar IBKR hasta tener chain coverage reviewable.", [ibkr_gap]
    if not _capability_allowed(gate, "can_create_entry_ready"):
        return "READY_FOR_EVIDENCE", "Recolectar mas evidencia antes de crear ENTRY_READY.", _capability_blockers(gate, "can_create_entry_ready")
    if not _capability_allowed(gate, "can_create_options_entry_ready"):
        return "FUTURES_READY_OPTIONS_WAITING", "Futures pueden revisarse; opciones esperan SPY/QQQ/VIX + IBKR completos.", _capability_blockers(gate, "can_create_options_entry_ready")
    if not _capability_allowed(gate, "can_evaluate_outcomes"):
        return "READY_FOR_MANUAL_REVIEW", "Evidencia lista para revision manual; seguir acumulando paper outcomes.", _capability_blockers(gate, "can_evaluate_outcomes")
    if _capability_allowed(gate, "can_review_parameters"):
        return "PARAMETER_REVIEW_READY", "Preparar paquete humano versionado; no cambiar reglas sin revision.", []
    return "READY_FOR_MANUAL_REVIEW", "Abrir inbox manual y revisar solo estados ENTRY_READY.", []


def build_go_no_go(
    runtime_dir: str | Path = DEFAULT_RUNTIME_DIR,
    *,
    generated_at: str | None = None,
    market_closed_ok: bool = False,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    generated_at = generated_at or now_iso()
    foundation = foundation_health.build_foundation_health(runtime, generated_at=generated_at)
    gate = operational_evidence_gate.build_operational_evidence_gate(
        runtime,
        generated_at=generated_at,
        include_recovery_preview=False,
    )
    tv_bundle = tradingview_operational_health.build_alert_bundle_health(
        runtime,
        generated_at=generated_at,
        market_closed_ok=market_closed_ok,
        allow_local_replay_validation=True,
    )
    ibkr_gap = _ibkr_primary_gap(runtime)
    ibkr_connected = _ibkr_connected(runtime, generated_at)
    status, next_action, reasons = _classify_go_no_go(foundation, gate, tv_bundle, ibkr_gap)
    return {
        "engine": "STOCK_ULTIMUS_OPERATOR_READINESS",
        "operator_readiness_version": OPERATOR_READINESS_VERSION,
        "generated_at": generated_at,
        "runtime_dir": str(runtime),
        "status": status,
        "ok": status in {
            "READY_FOR_EVIDENCE",
            "READY_FOR_MANUAL_REVIEW",
            "FUTURES_READY_OPTIONS_WAITING",
            "PARAMETER_REVIEW_READY",
        },
        "next_required_action": next_action,
        "reasons": reasons,
        "foundation_status": foundation.get("status"),
        "operational_gate_state": gate.get("state"),
        "ibkr_primary_gap": ibkr_gap,
        "ibkr_connected": ibkr_connected,
        "tradingview_bundle": {
            "status": tv_bundle.get("status"),
            "coverage_valid": tv_bundle.get("coverage_valid"),
            "real_e2e_confirmed": tv_bundle.get("real_e2e_confirmed"),
            "total_production_active_alert_count": tv_bundle.get("total_production_active_alert_count"),
            "total_required_logical_event_count": tv_bundle.get("total_required_logical_event_count"),
            "total_logical_event_count": tv_bundle.get("total_logical_event_count"),
            "total_expected_alert_count": tv_bundle.get("total_expected_alert_count"),
            "total_required_alert_count": tv_bundle.get("total_required_alert_count"),
            "total_received_required_event_count": tv_bundle.get("total_received_required_event_count"),
            "total_quarantine_event_count": tv_bundle.get("total_quarantine_event_count"),
            "missing_required_event_codes_by_coverage": tv_bundle.get("missing_required_event_codes_by_coverage") or {},
            "missing_health_event_codes_by_coverage": tv_bundle.get("missing_health_event_codes_by_coverage") or {},
        },
        "capabilities": gate.get("capabilities") or {},
        "evidence_summary": gate.get("evidence_summary") or {},
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def build_market_open_checklist(
    runtime_dir: str | Path = DEFAULT_RUNTIME_DIR,
    *,
    generated_at: str | None = None,
    market_closed_ok: bool = False,
) -> dict[str, Any]:
    readiness = build_go_no_go(
        runtime_dir,
        generated_at=generated_at,
        market_closed_ok=market_closed_ok,
    )
    steps = [
        {
            "name": "tradingview_alerts_visible",
            "command": "Open TradingView alerts panel and confirm 5 consolidated production alerts are active.",
            "expected": "2 MNQ/MES futures alerts and 3 QQQ/SPY/VIX options-underlying alerts; old per-condition and Chris IA alerts remain paused.",
            "status": "PASS" if readiness["tradingview_bundle"]["coverage_valid"] else "OPEN",
        },
        {
            "name": "tradingview_real_payloads",
            "command": "python3 scripts/run_tradingview_alert_bundle_health.py --market-closed-ok --local-replay-validation",
            "expected": "real_e2e_confirmed=true after live alerts fire.",
            "status": "PASS" if readiness["tradingview_bundle"]["real_e2e_confirmed"] else "WAIT_REAL_MARKET",
        },
        {
            "name": "ibkr_chain_coverage",
            "command": "python3 ibkr_bridge.py --once",
            "expected": "v32_ibkr_chain_coverage.primary_gap=COVERAGE_REVIEWABLE.",
            "status": "PASS" if readiness["ibkr_primary_gap"] == "COVERAGE_REVIEWABLE" else "WAIT_IBKR",
        },
        {
            "name": "operator_go_no_go",
            "command": "python3 scripts/run_market_open_readiness.py",
            "expected": "status READY_FOR_EVIDENCE, READY_FOR_MANUAL_REVIEW, or PARAMETER_REVIEW_READY.",
            "status": "PASS" if readiness["ok"] else "OPEN",
        },
        {
            "name": "post_open_monitor",
            "command": "python3 scripts/run_post_open_monitor.py",
            "expected": "alert_level OK or WATCH; ACTION requires operator attention.",
            "status": "READY",
        },
    ]
    return {
        "engine": "STOCK_ULTIMUS_MARKET_OPEN_CHECKLIST",
        "checklist_version": MARKET_OPEN_CHECKLIST_VERSION,
        "generated_at": readiness["generated_at"],
        "runtime_dir": readiness["runtime_dir"],
        "status": "READY_TO_START_OPEN_SEQUENCE" if readiness["status"] != "FOUNDATION_BLOCKED" else "FOUNDATION_BLOCKED",
        "go_no_go_status": readiness["status"],
        "next_required_action": readiness["next_required_action"],
        "steps": steps,
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def build_post_open_monitor(
    runtime_dir: str | Path = DEFAULT_RUNTIME_DIR,
    *,
    generated_at: str | None = None,
    market_closed_ok: bool = False,
) -> dict[str, Any]:
    readiness = build_go_no_go(
        runtime_dir,
        generated_at=generated_at,
        market_closed_ok=market_closed_ok,
    )
    tv = readiness.get("tradingview_bundle") or {}
    findings = []
    if tv.get("coverage_valid") is not True:
        findings.append({"severity": "ACTION", "code": "TV_COVERAGE_INVALID", "detail": "TradingView coverage matrix is invalid."})
    if tv.get("real_e2e_confirmed") is not True:
        findings.append({"severity": "WATCH", "code": "TV_REAL_E2E_PENDING", "detail": "Expected TradingView real payloads have not all arrived."})
    if _safe_int(tv.get("total_quarantine_event_count")):
        findings.append({"severity": "ACTION", "code": "TV_QUARANTINE_EVENTS", "detail": "Unknown or malformed TradingView payloads are present."})
    if readiness.get("ibkr_primary_gap") != "COVERAGE_REVIEWABLE":
        if readiness.get("ibkr_connected") is True:
            findings.append({
                "severity": "INFO",
                "code": "IBKR_OPTION_COVERAGE_PENDING",
                "detail": "IBKR esta conectado; falta completar el diagnostico de cobertura de opciones.",
            })
        else:
            findings.append({"severity": "WATCH", "code": "IBKR_NOT_REVIEWABLE", "detail": readiness.get("ibkr_primary_gap")})
    if not _capability_allowed(readiness, "can_evaluate_outcomes"):
        blockers = _capability_blockers(readiness, "can_evaluate_outcomes")
        findings.append({"severity": "INFO", "code": "PAPER_OUTCOME_LOOP_PENDING", "detail": ", ".join(blockers) or "Outcome sample still accumulating."})

    action_count = sum(1 for item in findings if item["severity"] == "ACTION")
    watch_count = sum(1 for item in findings if item["severity"] == "WATCH")
    alert_level = "ACTION" if action_count else ("WATCH" if watch_count else "OK")
    return {
        "engine": "STOCK_ULTIMUS_POST_OPEN_MONITOR",
        "monitor_version": POST_OPEN_MONITOR_VERSION,
        "generated_at": readiness["generated_at"],
        "runtime_dir": readiness["runtime_dir"],
        "alert_level": alert_level,
        "status": readiness["status"],
        "findings": findings,
        "summary": {
            "action_count": action_count,
            "watch_count": watch_count,
            "info_count": sum(1 for item in findings if item["severity"] == "INFO"),
            "tradingview_real_e2e_confirmed": tv.get("real_e2e_confirmed"),
            "tradingview_total_production_active_alert_count": tv.get("total_production_active_alert_count"),
            "tradingview_total_required_logical_event_count": tv.get("total_required_logical_event_count"),
            "tradingview_total_received_required_event_count": tv.get("total_received_required_event_count"),
            "tradingview_total_required_alert_count": tv.get("total_required_alert_count"),
            "ibkr_primary_gap": readiness.get("ibkr_primary_gap"),
            "ibkr_connected": readiness.get("ibkr_connected") is True,
            "operational_gate_state": readiness.get("operational_gate_state"),
        },
        "next_required_action": readiness["next_required_action"],
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
