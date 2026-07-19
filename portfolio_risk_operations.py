"""Human-in-the-loop operations for portfolio risk alerts.

The module manages acknowledgement, snoozing, escalation, a local notification
outbox, and daily digests.  It never places orders and does not send externally.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import broker_control_tower as control_tower


OPERATIONS_VERSION = "stock_ultimus_portfolio_risk_operations_v1"
ACTIONS_VERSION = "stock_ultimus_portfolio_risk_actions_v1"
OUTBOX_VERSION = "stock_ultimus_portfolio_risk_outbox_v1"
OBSERVATION_VERSION = "stock_ultimus_portfolio_risk_observation_v1"
VALID_ACTIONS = {"ACKNOWLEDGE", "SNOOZE", "REOPEN"}
DEFAULT_CONFIG: dict[str, Any] = {
    "operations_version": OPERATIONS_VERSION,
    "timezone": "America/New_York",
    "weekday_monitoring_only": True,
    "monitor_window": {"start": "07:00", "end": "17:30"},
    "notification_severities": ["CRITICAL", "HIGH"],
    "notification_cooldown_minutes": 60,
    "acknowledgement_minutes": 240,
    "default_snooze_minutes": 60,
    "escalation_minutes": {"CRITICAL": 15, "HIGH": 60},
    "outbox_max_items": 500,
    "local_notifications_enabled": False,
    "observation_target_sessions": 5,
}


def parse_datetime(value: Any) -> datetime | None:
    return control_tower.parse_datetime(value)


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def load_config(path: Path | None = None) -> dict[str, Any]:
    config = deepcopy(DEFAULT_CONFIG)
    if not path:
        return config
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("operations config must be an object")
    except Exception as exc:
        config["config_warnings"] = [f"OPERATIONS_CONFIG_LOAD_FAILED:{type(exc).__name__}"]
        return config
    for key, value in payload.items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key].update(value)
        else:
            config[key] = value
    config["config_warnings"] = []
    return config


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _actions_payload(actions: dict[str, Any], updated_at: str) -> dict[str, Any]:
    return {
        "actions_version": ACTIONS_VERSION,
        "updated_at": updated_at,
        "actions": actions,
        "sensitive_identifiers_excluded": True,
        "execution_authorized": False,
        "automatic_liquidation_authorized": False,
        "not_order_instruction": True,
    }


def record_action(
    path: Path,
    *,
    alert_id: str,
    action: str,
    actor: str = "stock_ultimus_console",
    reason: str = "",
    snooze_minutes: int | None = None,
    acknowledgement_minutes: int = 240,
    alert_severity: str = "",
    known_alert_ids: set[str] | None = None,
    reference: datetime | None = None,
) -> dict[str, Any]:
    reference = reference or datetime.now(timezone.utc)
    alert_id = str(alert_id or "").strip()
    action = str(action or "").strip().upper()
    if not alert_id:
        raise ValueError("alert_id is required")
    if action not in VALID_ACTIONS:
        raise ValueError("unsupported portfolio risk action")
    if known_alert_ids is not None and alert_id not in known_alert_ids:
        raise ValueError("portfolio risk alert is not active")
    payload = load_json(path)
    actions = payload.get("actions") if isinstance(payload.get("actions"), dict) else {}
    now = reference.isoformat()
    previous = actions.get(alert_id) if isinstance(actions.get(alert_id), dict) else {}
    item: dict[str, Any] = {
        "alert_id": alert_id,
        "status": action,
        "actor": str(actor or "stock_ultimus_console")[:80],
        "reason": str(reason or "")[:300],
        "updated_at": now,
        "action_count": int(previous.get("action_count") or 0) + 1,
        "sensitive_identifiers_excluded": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    if alert_severity:
        item["alert_severity"] = str(alert_severity).upper()
    if action == "ACKNOWLEDGE":
        item["acknowledged_at"] = now
        item["expires_at"] = (reference + timedelta(minutes=max(1, int(acknowledgement_minutes)))).isoformat()
    elif action == "SNOOZE":
        minutes = max(1, min(1440, int(snooze_minutes or 60)))
        item["snoozed_at"] = now
        item["expires_at"] = (reference + timedelta(minutes=minutes)).isoformat()
        item["snooze_minutes"] = minutes
    else:
        item["reopened_at"] = now
        item["expires_at"] = None
    actions[alert_id] = item
    control_tower.write_control_tower(path, _actions_payload(actions, now))
    return item


def decorate_evaluation(
    evaluation: dict[str, Any],
    action_state: dict[str, Any] | None = None,
    *,
    reference: datetime | None = None,
) -> dict[str, Any]:
    reference = reference or datetime.now(timezone.utc)
    result = deepcopy(evaluation)
    actions = (action_state or {}).get("actions") if isinstance((action_state or {}).get("actions"), dict) else {}
    lifecycle_counts = {"open": 0, "acknowledged": 0, "snoozed": 0}
    for alert in result.get("alerts") or []:
        if not isinstance(alert, dict):
            continue
        state = actions.get(str(alert.get("alert_id") or ""))
        state = state if isinstance(state, dict) else {}
        status = str(state.get("status") or "OPEN").upper()
        expires = parse_datetime(state.get("expires_at"))
        severity_matches = not state.get("alert_severity") or str(state.get("alert_severity")).upper() == str(alert.get("severity") or "").upper()
        active_action = status in {"ACKNOWLEDGE", "SNOOZE"} and expires is not None and expires > reference and severity_matches
        if status == "ACKNOWLEDGE" and active_action:
            operational_status = "ACKNOWLEDGED"
            lifecycle_counts["acknowledged"] += 1
        elif status == "SNOOZE" and active_action:
            operational_status = "SNOOZED"
            lifecycle_counts["snoozed"] += 1
        else:
            operational_status = "OPEN"
            lifecycle_counts["open"] += 1
        alert["operational_status"] = operational_status
        alert["notification_eligible"] = operational_status == "OPEN"
        alert["operator_reason"] = state.get("reason") or ""
        alert["operator_action_expires_at"] = state.get("expires_at") if active_action else None
    result["alert_lifecycle_counts"] = lifecycle_counts
    result["operations_version"] = OPERATIONS_VERSION
    return result


def _outbox_id(alert_id: str, severity: str, notification_type: str, bucket: str) -> str:
    raw = "|".join([OPERATIONS_VERSION, alert_id, severity, notification_type, bucket])
    return "prmsg_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _age_minutes(value: Any, reference: datetime) -> float | None:
    parsed = parse_datetime(value)
    if not parsed:
        return None
    return max(0.0, (reference - parsed).total_seconds() / 60)


def build_outbox(
    evaluation: dict[str, Any],
    previous: dict[str, Any] | None,
    config: dict[str, Any] | None = None,
    *,
    reference: datetime | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    reference = reference or datetime.now(timezone.utc)
    config = config or DEFAULT_CONFIG
    allowed = {str(value).upper() for value in (config.get("notification_severities") or [])}
    cooldown = max(1, int(config.get("notification_cooldown_minutes") or 60))
    escalation = config.get("escalation_minutes") if isinstance(config.get("escalation_minutes"), dict) else {}
    previous_items = [item for item in ((previous or {}).get("items") or []) if isinstance(item, dict)]
    new_items = []
    eligible_keys: set[tuple[str, str, str]] = set()
    eligible_alerts: list[tuple[dict[str, Any], str, str, float]] = []

    for alert in evaluation.get("alerts") or []:
        if not isinstance(alert, dict) or not alert.get("notification_eligible"):
            continue
        severity = str(alert.get("severity") or "").upper()
        if severity not in allowed:
            continue
        alert_id = str(alert.get("alert_id") or "")
        age = _age_minutes(alert.get("first_seen_at") or evaluation.get("generated_at"), reference) or 0.0
        escalation_after = control_tower.safe_float(escalation.get(severity))
        notification_type = "ESCALATION" if escalation_after is not None and age >= escalation_after else "RISK_ALERT"
        eligible_keys.add((alert_id, severity, notification_type))
        eligible_alerts.append((alert, alert_id, notification_type, age))

    for item in previous_items:
        if item.get("status") != "PENDING":
            continue
        key = (str(item.get("alert_id") or ""), str(item.get("severity") or ""), str(item.get("notification_type") or ""))
        if key not in eligible_keys:
            item["status"] = "CANCELLED"
            item["cancelled_at"] = reference.isoformat()
            item["cancel_reason"] = "ALERT_NOT_NOTIFICATION_ELIGIBLE"

    for alert, alert_id, notification_type, age in eligible_alerts:
        severity = str(alert.get("severity") or "").upper()
        active_existing = any(
            item.get("alert_id") == alert_id
            and item.get("severity") == severity
            and item.get("notification_type") == notification_type
            and item.get("status") == "PENDING"
            for item in previous_items
        )
        if active_existing:
            continue
        latest = max(
            [parse_datetime(item.get("created_at")) for item in previous_items if item.get("alert_id") == alert_id and item.get("severity") == severity] + [None],
            key=lambda value: value or datetime.min.replace(tzinfo=timezone.utc),
        )
        if latest and (reference - latest).total_seconds() < cooldown * 60:
            continue
        bucket = reference.strftime("%Y%m%d%H%M")
        item = {
            "message_id": _outbox_id(alert_id, severity, notification_type, bucket),
            "created_at": reference.isoformat(),
            "status": "PENDING",
            "notification_type": notification_type,
            "severity": severity,
            "alert_id": alert_id,
            "account_alias": alert.get("account_alias") or "",
            "rule": alert.get("rule"),
            "title": alert.get("title"),
            "body": alert.get("message"),
            "recommended_action": alert.get("recommended_action"),
            "channels": ["LOCAL_OUTBOX"],
            "sensitive_identifiers_excluded": True,
            "execution_authorized": False,
            "automatic_liquidation_authorized": False,
            "not_order_instruction": True,
        }
        previous_items.append(item)
        new_items.append(item)

    max_items = max(10, int(config.get("outbox_max_items") or 500))
    items = previous_items[-max_items:]
    payload = {
        "outbox_version": OUTBOX_VERSION,
        "updated_at": reference.isoformat(),
        "pending_count": sum(1 for item in items if item.get("status") == "PENDING"),
        "item_count": len(items),
        "items": items,
        "sensitive_identifiers_excluded": True,
        "execution_authorized": False,
        "automatic_liquidation_authorized": False,
        "not_order_instruction": True,
    }
    return payload, new_items


def mark_outbox_delivery(outbox: dict[str, Any], message_ids: set[str], *, reference: datetime | None = None) -> dict[str, Any]:
    reference = reference or datetime.now(timezone.utc)
    result = deepcopy(outbox)
    for item in result.get("items") or []:
        if isinstance(item, dict) and item.get("message_id") in message_ids:
            item["status"] = "DELIVERED_LOCAL"
            item["delivered_at"] = reference.isoformat()
            item["delivered_channel"] = "MACOS_NOTIFICATION_CENTER"
    result["updated_at"] = reference.isoformat()
    result["pending_count"] = sum(1 for item in (result.get("items") or []) if item.get("status") == "PENDING")
    return result


def record_observation_session(
    path: Path,
    *,
    tower: dict[str, Any],
    evaluation: dict[str, Any],
    outbox: dict[str, Any],
    cycle: dict[str, Any],
    config: dict[str, Any] | None = None,
    reference: datetime | None = None,
) -> dict[str, Any]:
    """Record one idempotent weekday observation for notification calibration."""
    reference = reference or datetime.now(timezone.utc)
    config = config or DEFAULT_CONFIG
    try:
        local = reference.astimezone(ZoneInfo(str(config.get("timezone") or "America/New_York")))
    except Exception:
        local = reference.astimezone(timezone.utc)
    target = max(1, int(config.get("observation_target_sessions") or 5))
    previous = load_json(path)
    sessions = [item for item in (previous.get("sessions") or []) if isinstance(item, dict)]
    if local.weekday() >= 5:
        result = dict(previous) if previous else {
            "observation_version": OBSERVATION_VERSION,
            "sessions": sessions,
        }
        result.update({
            "updated_at": reference.isoformat(),
            "status": result.get("status") or "OBSERVING",
            "recorded": False,
            "record_reason": "NON_TRADING_WEEKDAY",
            "target_sessions": target,
            "observed_session_count": len(sessions),
            "consecutive_clean_sessions": int(result.get("consecutive_clean_sessions") or 0),
            "remaining_clean_sessions": max(0, target - int(result.get("consecutive_clean_sessions") or 0)),
            "ready_to_enable_local_notifications": False,
            "local_notifications_enabled": False,
            "external_notifications_enabled": False,
            "execution_authorized": False,
            "automatic_liquidation_authorized": False,
            "not_order_instruction": True,
        })
        control_tower.write_control_tower(path, result)
        return result

    pending = [item for item in (outbox.get("items") or []) if isinstance(item, dict) and item.get("status") == "PENDING"]
    pending_keys = [
        (str(item.get("alert_id") or ""), str(item.get("severity") or ""), str(item.get("notification_type") or ""))
        for item in pending
    ]
    account_count = int(tower.get("account_count") or 0)
    checks = {
        "cycle_completed": cycle.get("status") == "COMPLETED",
        "control_tower_ready": tower.get("status") == "READY",
        "all_accounts_ready": account_count > 0 and int(tower.get("ready_account_count") or 0) == account_count,
        "no_failed_accounts": int(tower.get("failed_account_count") or 0) == 0,
        "no_stale_accounts": int(tower.get("stale_account_count") or 0) == 0,
        "no_pending_duplicates": len(pending_keys) == len(set(pending_keys)),
        "sensitive_identifiers_excluded": bool(
            tower.get("sensitive_identifiers_excluded")
            and evaluation.get("sensitive_identifiers_excluded")
            and outbox.get("sensitive_identifiers_excluded")
        ),
        "execution_disabled": not bool(
            tower.get("execution_authorized")
            or evaluation.get("execution_authorized")
            or outbox.get("execution_authorized")
            or cycle.get("execution_authorized")
        ),
        "automatic_liquidation_disabled": not bool(
            evaluation.get("automatic_liquidation_authorized")
            or outbox.get("automatic_liquidation_authorized")
            or cycle.get("automatic_liquidation_authorized")
        ),
        "notifications_disabled": not bool(
            cycle.get("local_notifications_enabled") or cycle.get("external_notification_sent")
        ),
    }
    session_date = local.date().isoformat()
    session = {
        "session_date": session_date,
        "recorded_at": reference.isoformat(),
        "clean": all(checks.values()),
        "checks": checks,
        "account_count": account_count,
        "risk_status": evaluation.get("status"),
        "risk_score": evaluation.get("risk_score"),
        "pending_outbox_count": int(outbox.get("pending_count") or 0),
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    sessions = [item for item in sessions if item.get("session_date") != session_date]
    sessions.append(session)
    sessions = sorted(sessions, key=lambda item: str(item.get("session_date") or ""))[-30:]
    latest = sessions[-target:]
    ready = len(latest) >= target and all(item.get("clean") for item in latest)
    consecutive_clean = 0
    for item in reversed(sessions):
        if not item.get("clean"):
            break
        consecutive_clean += 1
    result = {
        "observation_version": OBSERVATION_VERSION,
        "updated_at": reference.isoformat(),
        "status": "READY_TO_ENABLE_LOCAL_NOTIFICATIONS" if ready else "OBSERVING",
        "recorded": True,
        "record_reason": "WEEKDAY_DIGEST",
        "target_sessions": target,
        "observed_session_count": len(sessions),
        "consecutive_clean_sessions": consecutive_clean,
        "remaining_clean_sessions": max(0, target - consecutive_clean),
        "ready_to_enable_local_notifications": ready,
        "sessions": sessions,
        "local_notifications_enabled": False,
        "external_notifications_enabled": False,
        "sensitive_identifiers_excluded": True,
        "execution_authorized": False,
        "automatic_liquidation_authorized": False,
        "not_order_instruction": True,
    }
    control_tower.write_control_tower(path, result)
    return result


def build_digest(evaluation: dict[str, Any], outbox: dict[str, Any], *, reference: datetime | None = None) -> tuple[dict[str, Any], str]:
    reference = reference or datetime.now(timezone.utc)
    alerts = [item for item in (evaluation.get("alerts") or []) if isinstance(item, dict)]
    lifecycle = evaluation.get("alert_lifecycle_counts") if isinstance(evaluation.get("alert_lifecycle_counts"), dict) else {}
    digest = {
        "digest_version": "stock_ultimus_portfolio_risk_digest_v1",
        "generated_at": reference.isoformat(),
        "status": evaluation.get("status"),
        "decision_support": evaluation.get("decision_support"),
        "risk_score": evaluation.get("risk_score"),
        "alert_counts": evaluation.get("alert_counts") or {},
        "alert_lifecycle_counts": lifecycle,
        "pending_notification_count": int(outbox.get("pending_count") or 0),
        "top_alerts": [{
            "severity": item.get("severity"),
            "account_alias": item.get("account_alias") or "",
            "title": item.get("title"),
            "operational_status": item.get("operational_status") or "OPEN",
            "recommended_action": item.get("recommended_action"),
        } for item in alerts[:10]],
        "sensitive_identifiers_excluded": True,
        "execution_authorized": False,
        "automatic_liquidation_authorized": False,
        "not_order_instruction": True,
    }
    lines = [
        "# Stock Ultimus · Riesgo de cartera",
        "",
        f"Generado: {digest['generated_at']}",
        f"Estado: {digest.get('status')} · decisión: {digest.get('decision_support')} · score: {digest.get('risk_score')}/100",
        f"Alertas abiertas: {lifecycle.get('open', 0)} · confirmadas: {lifecycle.get('acknowledged', 0)} · silenciadas: {lifecycle.get('snoozed', 0)}",
        f"Notificaciones pendientes: {digest.get('pending_notification_count')}",
        "",
        "## Prioridades",
        "",
    ]
    if digest["top_alerts"]:
        for item in digest["top_alerts"]:
            lines.append(f"- [{item.get('severity')}] {item.get('account_alias') or 'SISTEMA'} · {item.get('title')} · {item.get('operational_status')}")
            lines.append(f"  - {item.get('recommended_action')}")
    else:
        lines.append("- Sin alertas activas.")
    lines.extend(["", "Decision support solamente; no autoriza órdenes ni liquidaciones automáticas.", ""])
    return digest, "\n".join(lines)


def write_digest(json_path: Path, markdown_path: Path, digest: dict[str, Any], markdown: str) -> None:
    control_tower.write_control_tower(json_path, digest)
    _atomic_text(markdown_path, markdown)
