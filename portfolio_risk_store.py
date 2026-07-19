"""Atomic persistence and lifecycle history for portfolio risk evaluations."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import broker_control_tower as control_tower


LATEST_FILENAME = "portfolio_risk_latest.json"
HISTORY_FILENAME = "portfolio_risk_history.json"
HISTORY_VERSION = "stock_ultimus_portfolio_risk_history_v1"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _event_id(alert_id: str, transition: str, generated_at: str) -> str:
    value = f"{alert_id}|{transition}|{generated_at}"
    return "prevt_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def persist_evaluation(
    runtime_dir: Path,
    evaluation: dict[str, Any],
    *,
    latest_path: Path | None = None,
    history_path: Path | None = None,
    max_events: int = 1000,
) -> dict[str, Any]:
    latest_path = latest_path or runtime_dir / LATEST_FILENAME
    history_path = history_path or runtime_dir / HISTORY_FILENAME
    previous = _read_json(latest_path)
    history = _read_json(history_path)
    previous_alerts = {
        str(alert.get("alert_id") or ""): alert
        for alert in (previous.get("alerts") or [])
        if isinstance(alert, dict) and alert.get("alert_id")
    }
    generated_at = str(evaluation.get("generated_at") or control_tower.now_iso())
    current = deepcopy(evaluation)
    current_alerts = {}
    events = []

    for alert in current.get("alerts") or []:
        if not isinstance(alert, dict) or not alert.get("alert_id"):
            continue
        alert_id = str(alert["alert_id"])
        old = previous_alerts.get(alert_id)
        alert["first_seen_at"] = old.get("first_seen_at") if old else generated_at
        alert["last_seen_at"] = generated_at
        alert["lifecycle_status"] = "OPEN"
        current_alerts[alert_id] = alert
        transition = "OPENED" if not old else "SEVERITY_CHANGED" if old.get("severity") != alert.get("severity") else ""
        if transition:
            events.append({
                "event_id": _event_id(alert_id, transition, generated_at),
                "generated_at": generated_at,
                "transition": transition,
                "alert_id": alert_id,
                "rule": alert.get("rule"),
                "scope": alert.get("scope"),
                "account_alias": alert.get("account_alias") or "",
                "previous_severity": old.get("severity") if old else "NONE",
                "severity": alert.get("severity"),
                "sensitive_identifiers_excluded": True,
            })

    for alert_id, old in previous_alerts.items():
        if alert_id in current_alerts:
            continue
        events.append({
            "event_id": _event_id(alert_id, "RESOLVED", generated_at),
            "generated_at": generated_at,
            "transition": "RESOLVED",
            "alert_id": alert_id,
            "rule": old.get("rule"),
            "scope": old.get("scope"),
            "account_alias": old.get("account_alias") or "",
            "previous_severity": old.get("severity"),
            "severity": "NONE",
            "sensitive_identifiers_excluded": True,
        })

    existing_events = [item for item in (history.get("events") or []) if isinstance(item, dict)]
    event_ids = {str(item.get("event_id") or "") for item in existing_events}
    merged_events = existing_events + [event for event in events if event["event_id"] not in event_ids]
    merged_events = merged_events[-max(1, int(max_events)):]
    history_payload = {
        "history_version": HISTORY_VERSION,
        "updated_at": generated_at,
        "event_count": len(merged_events),
        "events": merged_events,
        "sensitive_identifiers_excluded": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    control_tower.write_control_tower(latest_path, current)
    control_tower.write_control_tower(history_path, history_payload)
    return {
        "latest_path": str(latest_path),
        "history_path": str(history_path),
        "new_event_count": len(events),
        "opened_count": sum(1 for event in events if event["transition"] == "OPENED"),
        "changed_count": sum(1 for event in events if event["transition"] == "SEVERITY_CHANGED"),
        "resolved_count": sum(1 for event in events if event["transition"] == "RESOLVED"),
    }
