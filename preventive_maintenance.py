"""Preventive maintenance health for the local Stock Ultimus runtime."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MAINTENANCE_VERSION = "stock_ultimus_preventive_maintenance_v1"
FILE_POLICIES = {
    "broker_control_tower_latest.json": {"label": "Control Tower", "weekday_hours": 24, "weekend_hours": 72, "required": True},
    "portfolio_risk_latest.json": {"label": "Riesgo de cartera", "weekday_hours": 24, "weekend_hours": 72, "required": True},
    "ibkr_bridge_health_latest.json": {"label": "Conexión IBKR", "weekday_hours": 24, "weekend_hours": 72, "required": True},
    "daily_outcome_evaluation_latest.json": {"label": "Seguimiento de resultados", "weekday_hours": 36, "weekend_hours": 96, "required": True},
    "executive_report_daily_latest.json": {"label": "Reporte ejecutivo diario", "weekday_hours": 36, "weekend_hours": 96, "required": True},
    "executive_report_weekly_latest.json": {"label": "Reporte ejecutivo semanal", "weekday_hours": 192, "weekend_hours": 192, "required": True},
    "security_audit_latest.json": {"label": "Auditoría de seguridad", "weekday_hours": 192, "weekend_hours": 192, "required": True},
    "dependency_audit_latest.json": {"label": "Auditoría de dependencias", "weekday_hours": 192, "weekend_hours": 192, "required": True},
}
EXPECTED_JOBS = [
    "com.stockultimus.local-console-opener",
    "com.stockultimus.portfolio-risk-monitor",
    "com.stockultimus.portfolio-risk-digest",
    "com.stockultimus.portfolio-risk-preflight",
    "com.stockultimus.v32-pushover-postclose",
    "com.stockultimus.executive-report-daily",
    "com.stockultimus.executive-report-weekly",
    "com.stockultimus.preventive-maintenance",
]


def _timestamp(payload: dict[str, Any], path: Path) -> datetime:
    value = payload.get("generated_at") or payload.get("checked_at") or payload.get("updated_at")
    text = str(value or "").replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text) if text else None
    except Exception:
        parsed = None
    if parsed and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed or datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def inspect_file(path: Path, policy: dict[str, Any], reference: datetime) -> dict[str, Any]:
    item = {"file": path.name, "label": policy["label"], "required": bool(policy.get("required"))}
    if not path.exists():
        return {**item, "status": "HIGH" if policy.get("required") else "WARN", "reason": "MISSING", "age_hours": None}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, (dict, list)):
            raise ValueError("JSON root is not an object or list")
    except Exception as exc:
        return {**item, "status": "HIGH", "reason": f"INVALID_JSON:{type(exc).__name__}", "age_hours": None, "size_bytes": path.stat().st_size}
    timestamp = _timestamp(payload if isinstance(payload, dict) else {}, path)
    age_hours = max(0.0, (reference - timestamp).total_seconds() / 3600)
    weekend = reference.weekday() >= 5
    limit = float(policy["weekend_hours"] if weekend else policy["weekday_hours"])
    status = "WARN" if age_hours > limit else "OK"
    return {
        **item,
        "status": status,
        "reason": "STALE" if status == "WARN" else "FRESH",
        "age_hours": round(age_hours, 2),
        "maximum_age_hours": limit,
        "size_bytes": path.stat().st_size,
    }


def build_maintenance_report(
    runtime_dir: Path,
    *,
    launch_agents_dir: Path | None = None,
    reference: datetime | None = None,
    disk_path: Path | None = None,
) -> dict[str, Any]:
    reference = reference or datetime.now(timezone.utc)
    launch_agents_dir = launch_agents_dir or Path.home() / "Library" / "LaunchAgents"
    disk_path = disk_path or runtime_dir
    file_checks = [inspect_file(runtime_dir / name, policy, reference) for name, policy in FILE_POLICIES.items()]
    job_checks = []
    for label in EXPECTED_JOBS:
        installed = (launch_agents_dir / f"{label}.plist").exists()
        job_checks.append({"label": label, "installed": installed, "status": "OK" if installed else "WARN"})
    runtime_files = [path for path in runtime_dir.iterdir() if path.is_file()] if runtime_dir.exists() else []
    total_bytes = sum(path.stat().st_size for path in runtime_files)
    largest = sorted(runtime_files, key=lambda path: path.stat().st_size, reverse=True)[:10]
    large_files = [path for path in runtime_files if path.stat().st_size > 25 * 1024 * 1024]
    disk = shutil.disk_usage(disk_path)
    free_gb = disk.free / (1024 ** 3)
    storage_status = "CRITICAL" if free_gb < 5 else "WARN" if free_gb < 20 or total_bytes > 500 * 1024 * 1024 or large_files else "OK"
    bridge_path = runtime_dir / "ibkr_bridge_health_latest.json"
    try:
        bridge = json.loads(bridge_path.read_text(encoding="utf-8"))
    except Exception:
        bridge = {}
    bridge_connected = bridge.get("connected") is True and str(bridge.get("status") or "").upper() == "CONNECTED"
    bridge_check = {
        "status": "OK" if bridge_connected else "WARN",
        "connected": bridge_connected,
        "broker_status": bridge.get("status") or "UNKNOWN",
        "generated_at": bridge.get("generated_at"),
    }
    high_count = sum(1 for item in file_checks if item["status"] in {"HIGH", "CRITICAL"})
    warning_count = sum(1 for item in file_checks if item["status"] == "WARN")
    missing_jobs = sum(1 for item in job_checks if not item["installed"])
    if storage_status == "CRITICAL" or high_count:
        status = "ACTION_REQUIRED"
    elif storage_status == "WARN" or warning_count or missing_jobs or not bridge_connected:
        status = "WATCH"
    else:
        status = "READY"
    actions = []
    for item in file_checks:
        if item["status"] != "OK":
            actions.append({"priority": item["status"], "title": f"Revisar {item['label']}", "detail": item["reason"]})
    if missing_jobs:
        actions.append({"priority": "WARN", "title": "Restaurar procesos programados", "detail": f"{missing_jobs} proceso(s) esperado(s) no están instalados."})
    if storage_status != "OK":
        actions.append({"priority": storage_status, "title": "Revisar almacenamiento", "detail": f"Espacio libre {free_gb:.1f} GB; runtime {total_bytes / 1024 / 1024:.1f} MB."})
    if not bridge_connected:
        actions.append({"priority": "WARN", "title": "Revisar conexión IBKR", "detail": "El último health check no confirma CONNECTED."})
    day_key = reference.date().isoformat()
    report_id = "maint_" + hashlib.sha256(day_key.encode()).hexdigest()[:18]
    return {
        "maintenance_version": MAINTENANCE_VERSION,
        "report_id": report_id,
        "generated_at": reference.isoformat(),
        "status": status,
        "summary": {
            "file_check_count": len(file_checks),
            "healthy_file_count": sum(1 for item in file_checks if item["status"] == "OK"),
            "stale_or_warning_file_count": warning_count,
            "high_file_count": high_count,
            "expected_job_count": len(job_checks),
            "installed_job_count": len(job_checks) - missing_jobs,
            "missing_job_count": missing_jobs,
            "runtime_file_count": len(runtime_files),
            "runtime_size_mb": round(total_bytes / 1024 / 1024, 2),
            "disk_free_gb": round(free_gb, 2),
            "storage_status": storage_status,
            "bridge_connected": bridge_connected,
            "action_count": len(actions),
        },
        "file_checks": file_checks,
        "job_checks": job_checks,
        "bridge_check": bridge_check,
        "storage": {
            "status": storage_status,
            "runtime_size_bytes": total_bytes,
            "disk_free_bytes": disk.free,
            "large_file_count": len(large_files),
            "largest_files": [{"name": path.name, "size_bytes": path.stat().st_size} for path in largest],
        },
        "actions": actions,
        "automatic_deletion_authorized": False,
        "automatic_restart_authorized": False,
        "sensitive_identifiers_excluded": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def persist_report(runtime_dir: Path, report: dict[str, Any]) -> None:
    latest = runtime_dir / "preventive_maintenance_latest.json"
    history_path = runtime_dir / "preventive_maintenance_history.json"
    latest.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        history = json.loads(history_path.read_text(encoding="utf-8"))
    except Exception:
        history = {"reports": []}
    rows = [item for item in (history.get("reports") or []) if isinstance(item, dict) and item.get("report_id") != report.get("report_id")]
    rows.append(report)
    rows = sorted(rows, key=lambda item: str(item.get("generated_at") or ""))[-400:]
    payload = {
        "history_version": "stock_ultimus_preventive_maintenance_history_v1",
        "updated_at": report.get("generated_at"),
        "report_count": len(rows),
        "reports": rows,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    history_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
