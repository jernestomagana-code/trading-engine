"""State-change alerts for active position management."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATE_ALERT_VERSION = "position_state_alerts_v1"
DEFAULT_STATE_PATH = Path("runtime") / "active_position_state_alerts.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state(path: str | Path = DEFAULT_STATE_PATH) -> dict[str, Any]:
    path = Path(path)
    try:
        payload = json.loads(path.read_text())
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return {
        "state_alert_version": payload.get("state_alert_version") or STATE_ALERT_VERSION,
        "updated_at": payload.get("updated_at"),
        "positions": payload.get("positions") if isinstance(payload.get("positions"), dict) else {},
        "alerts": payload.get("alerts") if isinstance(payload.get("alerts"), list) else [],
        "not_order_instruction": True,
        "execution_authorized": False,
    }


def save_state(payload: dict[str, Any], path: str | Path = DEFAULT_STATE_PATH) -> dict[str, Any]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload or {})
    payload["state_alert_version"] = STATE_ALERT_VERSION
    payload["updated_at"] = now_iso()
    payload["not_order_instruction"] = True
    payload["execution_authorized"] = False
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    return payload


def _position_key(item: dict[str, Any]) -> str:
    return str(item.get("position_id") or "|".join(str(item.get(k) or "") for k in ["ticker", "strategy", "strike", "expiration"]))


def update_from_management(payload: dict[str, Any], path: str | Path = DEFAULT_STATE_PATH) -> dict[str, Any]:
    current_positions = payload.get("positions") if isinstance(payload.get("positions"), list) else []
    state = load_state(path)
    previous = state.get("positions") if isinstance(state.get("positions"), dict) else {}
    next_positions: dict[str, dict[str, Any]] = {}
    new_alerts = []
    for item in current_positions:
        if not isinstance(item, dict):
            continue
        key = _position_key(item)
        current = {
            "ticker": item.get("ticker"),
            "strategy": item.get("strategy"),
            "exit_state": item.get("exit_state"),
            "management_action": item.get("management_action"),
            "manual_review_required": item.get("manual_review_required"),
            "seen_at": now_iso(),
        }
        old = previous.get(key) if isinstance(previous.get(key), dict) else {}
        changed = bool(
            old
            and (
                old.get("exit_state") != current.get("exit_state")
                or old.get("management_action") != current.get("management_action")
            )
        )
        if changed:
            new_alerts.append({
                "alert_id": f"pm-state-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
                "created_at": now_iso(),
                "position_id": key,
                "ticker": current.get("ticker"),
                "strategy": current.get("strategy"),
                "from_exit_state": old.get("exit_state"),
                "to_exit_state": current.get("exit_state"),
                "from_management_action": old.get("management_action"),
                "to_management_action": current.get("management_action"),
                "severity": "RISK" if str(current.get("management_action") or "").startswith("REVIEW_RISK") else "ACTION",
                "not_order_instruction": True,
                "execution_authorized": False,
            })
        next_positions[key] = current
    alerts = new_alerts + (state.get("alerts") or [])
    updated = {
        "positions": next_positions,
        "alerts": alerts[:200],
        "latest_alerts": new_alerts,
    }
    return save_state(updated, path)


def summary(path: str | Path = DEFAULT_STATE_PATH) -> dict[str, Any]:
    state = load_state(path)
    alerts = state.get("alerts") or []
    return {
        "state_alert_version": STATE_ALERT_VERSION,
        "alert_count": len(alerts),
        "latest_alerts": alerts[:10],
        "not_order_instruction": True,
        "execution_authorized": False,
    }
