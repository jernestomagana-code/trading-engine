"""Sanitized daily and weekly executive reports for Stock Ultimus."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import alert_effectiveness
import decision_outcome_intelligence


REPORT_VERSION = "stock_ultimus_executive_report_v1"


def _load(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {} if default is None else default


def _time(value: Any) -> datetime | None:
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text) if text else None
    except Exception:
        return None
    if parsed and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _rows(payload: Any, key: str) -> list[dict[str, Any]]:
    values = payload if isinstance(payload, list) else payload.get(key) or [] if isinstance(payload, dict) else []
    return [item for item in values if isinstance(item, dict)]


def build_report(runtime_dir: Path, period: str, *, reference: datetime | None = None) -> dict[str, Any]:
    period = str(period or "daily").lower()
    if period not in {"daily", "weekly"}:
        raise ValueError("period must be daily or weekly")
    reference = reference or datetime.now(timezone.utc)
    tower = _load(runtime_dir / "broker_control_tower_latest.json")
    risk = _load(runtime_dir / "portfolio_risk_latest.json")
    stress = _load(runtime_dir / "portfolio_stress_latest.json")
    factors = _load(runtime_dir / "portfolio_factor_latest.json")
    operations = _load(runtime_dir / "portfolio_risk_operations_status.json")
    observation = _load(runtime_dir / "portfolio_risk_observation.json")
    history = _load(runtime_dir / "portfolio_risk_history.json")
    decisions = _rows(_load(runtime_dir / "v32_decision_journal.json", []), "decisions")
    outcomes = _rows(_load(runtime_dir / "v32_outcomes_journal.json", []), "outcomes")
    intelligence = decision_outcome_intelligence.build_intelligence(decisions, outcomes, generated_at=reference.isoformat())
    effectiveness = alert_effectiveness.build_effectiveness(decisions, outcomes, generated_at=reference.isoformat())
    alerts = [item for item in (risk.get("alerts") or []) if isinstance(item, dict)]
    high_alerts = [item for item in alerts if str(item.get("severity") or "").upper() in {"CRITICAL", "HIGH"}]
    cutoff = reference - timedelta(days=7 if period == "weekly" else 1)
    risk_events = [
        item for item in (history.get("events") or [])
        if isinstance(item, dict) and (_time(item.get("generated_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
    ]
    opened_events = [item for item in risk_events if str(item.get("transition") or "").upper() == "OPENED"]
    resolved_events = [item for item in risk_events if str(item.get("transition") or "").upper() == "RESOLVED"]
    pending = []
    if high_alerts:
        pending.append({"priority": "HIGH", "title": "Revisar alertas de riesgo", "detail": f"{len(high_alerts)} alerta(s) CRITICAL/HIGH abiertas."})
    if int(tower.get("stale_account_count") or 0) or int(tower.get("failed_account_count") or 0):
        pending.append({"priority": "HIGH", "title": "Actualizar cuentas", "detail": "Hay cuentas vencidas o no disponibles en el Control Tower."})
    if not intelligence.get("parameter_review_ready"):
        pending.append({"priority": "BUILDING", "title": "Continuar acumulando resultados", "detail": f"{intelligence.get('complete_closed_outcomes') or 0}/30 resultados cerrados completos."})
    if effectiveness.get("status") != "REVIEWABLE":
        pending.append({"priority": "BUILDING", "title": "Mantener seguimiento de alertas", "detail": f"{effectiveness.get('resolved_entry_alert_count') or 0}/30 alertas de entrada resueltas."})
    if int(observation.get("remaining_clean_sessions") or 0):
        pending.append({"priority": "OBSERVE", "title": "Completar observación operativa", "detail": f"Faltan {observation.get('remaining_clean_sessions')} sesiones limpias."})
    status = "ACTION_REQUIRED" if high_alerts or int(tower.get("failed_account_count") or 0) else "BUILDING_EVIDENCE" if pending else "READY"
    account_count = int(tower.get("account_count") or 0)
    headline = (
        f"{len(high_alerts)} alerta(s) prioritaria(s) en {account_count} cuenta(s)."
        if high_alerts else f"Sin alertas CRITICAL/HIGH; evidencia y mantenimiento continúan en {account_count} cuenta(s)."
    )
    period_key = reference.date().isoformat() if period == "daily" else f"{reference.isocalendar().year}-W{reference.isocalendar().week:02d}"
    report_id = "exec_" + hashlib.sha256(f"{period}:{period_key}".encode()).hexdigest()[:18]
    return {
        "report_version": REPORT_VERSION,
        "report_id": report_id,
        "period": period,
        "period_key": period_key,
        "generated_at": reference.isoformat(),
        "status": status,
        "headline": headline,
        "portfolio": {
            "account_count": account_count,
            "ready_account_count": tower.get("ready_account_count") or 0,
            "stale_account_count": tower.get("stale_account_count") or 0,
            "failed_account_count": tower.get("failed_account_count") or 0,
            "risk_status": risk.get("status") or "UNKNOWN",
            "risk_score": risk.get("risk_score"),
            "decision_support": risk.get("decision_support") or "UNKNOWN",
            "critical_high_alert_count": len(high_alerts),
            "stress_status": stress.get("status") or "UNKNOWN",
            "valuation_coverage_ratio": stress.get("valuation_coverage_ratio"),
            "history_coverage_ratio": factors.get("history_coverage_ratio"),
            "greeks_coverage_ratio": factors.get("greeks_coverage_ratio"),
        },
        "decisions_and_results": {
            "decision_count": intelligence.get("decision_count") or 0,
            "actionable_decision_count": intelligence.get("actionable_decision_count") or 0,
            "outcome_count": intelligence.get("outcome_count") or 0,
            "complete_closed_outcomes": intelligence.get("complete_closed_outcomes") or 0,
            "outcome_coverage_pct": intelligence.get("actionable_outcome_coverage_pct"),
            "alert_tracking_coverage_pct": effectiveness.get("entry_tracking_coverage_pct"),
            "verified_precision_pct": effectiveness.get("verified_precision_pct"),
            "effectiveness_status": effectiveness.get("status"),
        },
        "period_activity": {
            "risk_event_count": len(risk_events),
            "risk_events_opened": len(opened_events),
            "risk_events_resolved": len(resolved_events),
        },
        "operations": {
            "latest_status": operations.get("status") or "UNKNOWN",
            "latest_mode": operations.get("mode") or "UNKNOWN",
            "observation_status": observation.get("status") or "UNKNOWN",
            "clean_sessions": observation.get("consecutive_clean_sessions") or 0,
            "target_clean_sessions": observation.get("target_sessions") or 5,
        },
        "pending_actions": pending,
        "pending_action_count": len(pending),
        "sensitive_identifiers_excluded": True,
        "manual_review_required": True,
        "execution_authorized": False,
        "automatic_rule_changes_authorized": False,
        "not_order_instruction": True,
    }


def render_markdown(report: dict[str, Any]) -> str:
    portfolio = report.get("portfolio") or {}
    evidence = report.get("decisions_and_results") or {}
    activity = report.get("period_activity") or {}
    lines = [
        f"# Reporte ejecutivo {str(report.get('period') or '').capitalize()}",
        "",
        f"**Estado:** {report.get('status')}  ",
        f"**Generado:** {report.get('generated_at')}  ",
        f"**Lectura:** {report.get('headline')}",
        "",
        "## Cartera y riesgo",
        f"- Cuentas: {portfolio.get('account_count')} · listas: {portfolio.get('ready_account_count')} · vencidas: {portfolio.get('stale_account_count')}.",
        f"- Riesgo: {portfolio.get('risk_status')} · score: {portfolio.get('risk_score')} · decisión: {portfolio.get('decision_support')}.",
        f"- Alertas CRITICAL/HIGH: {portfolio.get('critical_high_alert_count')}.",
        "",
        "## Decisiones y evidencia",
        f"- Decisiones: {evidence.get('decision_count')} · resultados: {evidence.get('outcome_count')} · completos: {evidence.get('complete_closed_outcomes')}/30.",
        f"- Cobertura de alertas: {evidence.get('alert_tracking_coverage_pct')}% · precisión verificada: {evidence.get('verified_precision_pct') if evidence.get('verified_precision_pct') is not None else 'Sin muestra'}.",
        "",
        "## Actividad del periodo",
        f"- Eventos de riesgo: {activity.get('risk_event_count')} · abiertos: {activity.get('risk_events_opened')} · resueltos: {activity.get('risk_events_resolved')}.",
        "",
        "## Pendientes",
    ]
    for item in report.get("pending_actions") or []:
        lines.append(f"- **{item.get('priority')} · {item.get('title')}** — {item.get('detail')}")
    if not report.get("pending_actions"):
        lines.append("- Sin pendientes operativos.")
    lines.extend(["", "> Soporte de decisión únicamente. No autoriza órdenes ni cambios automáticos."])
    return "\n".join(lines) + "\n"


def persist_report(runtime_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
    period = report["period"]
    json_path = runtime_dir / f"executive_report_{period}_latest.json"
    markdown_path = runtime_dir / f"executive_report_{period}_latest.md"
    history_path = runtime_dir / "executive_report_history.json"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    history = _load(history_path, {"reports": []})
    rows = [item for item in (history.get("reports") or []) if isinstance(item, dict)]
    rows = [item for item in rows if item.get("report_id") != report.get("report_id")]
    rows.append(report)
    rows = sorted(rows, key=lambda item: str(item.get("generated_at") or ""))[-400:]
    history_payload = {
        "history_version": "stock_ultimus_executive_report_history_v1",
        "updated_at": report.get("generated_at"),
        "report_count": len(rows),
        "reports": rows,
        "sensitive_identifiers_excluded": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    history_path.write_text(json.dumps(history_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path), "history_path": str(history_path)}
