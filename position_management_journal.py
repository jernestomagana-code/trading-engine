"""Local journal helpers for active position-management reviews."""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


JOURNAL_VERSION = "position_management_journal_v1"
DEFAULT_JOURNAL_PATH = Path("runtime") / "active_position_management_journal.json"
ALLOWED_OPERATOR_ACTIONS = {
    "NO_ACTION_TAKEN",
    "MANUAL_CLOSE_REVIEWED",
    "MANUAL_ROLL_REVIEWED",
    "ASSIGNMENT_REVIEWED",
    "RISK_REDUCTION_REVIEWED",
    "DATA_REFRESHED",
    "REVIEW_COMPLETED",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_journal(path: str | Path = DEFAULT_JOURNAL_PATH) -> dict[str, Any]:
    path = Path(path)
    try:
        payload = json.loads(path.read_text())
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    events = payload.get("events") if isinstance(payload.get("events"), list) else []
    return {
        "journal_version": payload.get("journal_version") or JOURNAL_VERSION,
        "updated_at": payload.get("updated_at"),
        "events": [event for event in events if isinstance(event, dict)],
        "not_order_instruction": True,
        "execution_authorized": False,
    }


def save_journal(payload: dict[str, Any], path: str | Path = DEFAULT_JOURNAL_PATH) -> dict[str, Any]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload or {})
    payload["journal_version"] = JOURNAL_VERSION
    payload["updated_at"] = now_iso()
    payload["not_order_instruction"] = True
    payload["execution_authorized"] = False
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    return payload


def record_event(
    event: dict[str, Any],
    *,
    path: str | Path = DEFAULT_JOURNAL_PATH,
    max_events: int = 500,
) -> dict[str, Any]:
    event = dict(event or {})
    action = str(event.get("operator_action") or "").strip().upper()
    if action not in ALLOWED_OPERATOR_ACTIONS:
        raise ValueError(f"unsupported position management operator_action: {action}")
    recorded = {
        "event_id": event.get("event_id") or f"pm-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
        "recorded_at": event.get("recorded_at") or now_iso(),
        "position_id": event.get("position_id"),
        "ticker": event.get("ticker"),
        "strategy": event.get("strategy"),
        "recommended_action": event.get("recommended_action"),
        "recommended_state": event.get("recommended_state"),
        "management_fingerprint": event.get("management_fingerprint"),
        "operator_action": action,
        "operator_reason": event.get("operator_reason") or "",
        "followup_required": bool(event.get("followup_required")),
        "observed_pnl": event.get("observed_pnl"),
        "premium_capture_pct": event.get("premium_capture_pct"),
        "post_action_state": event.get("post_action_state"),
        "source": event.get("source") or "stock_ultimus_console",
        "not_order_instruction": True,
        "execution_authorized": False,
    }
    journal = load_journal(path)
    events = [recorded] + (journal.get("events") or [])
    journal["events"] = events[:max_events]
    return save_journal(journal, path)


def management_fingerprint(position: dict[str, Any]) -> str:
    alternatives = position.get("management_alternatives") if isinstance(position.get("management_alternatives"), dict) else {}
    recommendation = alternatives.get("recommendation") if isinstance(alternatives.get("recommendation"), dict) else {}
    call = recommendation.get("contract") if isinstance(recommendation.get("contract"), dict) else {}
    put = recommendation.get("put_contract") if isinstance(recommendation.get("put_contract"), dict) else {}
    stable = {
        "position_id": position.get("position_id"),
        "ticker": position.get("ticker"),
        "strategy": position.get("strategy"),
        "position_size": position.get("position_size"),
        "strike": position.get("strike"),
        "expiration": position.get("expiration"),
        "management_action": position.get("management_action"),
        "exit_state": position.get("exit_state"),
        "recommendation": recommendation.get("alternative_id"),
        "contracts": recommendation.get("contracts"),
        "call_strike": call.get("strike"),
        "call_expiration": call.get("expiration"),
        "put_strike": put.get("strike"),
        "put_expiration": put.get("expiration"),
    }
    encoded = json.dumps(stable, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:20]


def acknowledged_position_reviews(
    management_payload: dict[str, Any],
    *,
    path: str | Path = DEFAULT_JOURNAL_PATH,
) -> dict[str, dict[str, Any]]:
    events = load_journal(path).get("events") or []
    positions = management_payload.get("positions") if isinstance(management_payload.get("positions"), list) else []
    acknowledged: dict[str, dict[str, Any]] = {}
    review_actions = {
        "REVIEW_COMPLETED",
        "NO_ACTION_TAKEN",
        "MANUAL_CLOSE_REVIEWED",
        "MANUAL_ROLL_REVIEWED",
        "ASSIGNMENT_REVIEWED",
        "RISK_REDUCTION_REVIEWED",
    }
    for position in positions:
        if not isinstance(position, dict):
            continue
        position_id = str(position.get("position_id") or "")
        if not position_id or str(position.get("management_action") or "").upper() == "REFRESH_DATA":
            continue
        current_fingerprint = management_fingerprint(position)
        latest = next(
            (
                event for event in events
                if isinstance(event, dict)
                and str(event.get("position_id") or "") == position_id
            ),
            None,
        )
        if not latest:
            continue
        if (
            str(latest.get("operator_action") or "").upper() in review_actions
            and str(latest.get("recommended_action") or "") == str(position.get("management_action") or "")
            and str(latest.get("recommended_state") or "") == str(position.get("exit_state") or "")
            and str(latest.get("management_fingerprint") or "") == current_fingerprint
        ):
            acknowledged[position_id] = latest
    return acknowledged


def summary(path: str | Path = DEFAULT_JOURNAL_PATH) -> dict[str, Any]:
    journal = load_journal(path)
    events = journal.get("events") or []
    by_action: dict[str, int] = {}
    for event in events:
        action = str(event.get("operator_action") or "UNKNOWN")
        by_action[action] = by_action.get(action, 0) + 1
    return {
        "journal_version": JOURNAL_VERSION,
        "event_count": len(events),
        "by_operator_action": by_action,
        "latest_event": events[0] if events else None,
        "not_order_instruction": True,
        "execution_authorized": False,
    }


def evaluate_against_management(
    management_payload: dict[str, Any],
    *,
    path: str | Path = DEFAULT_JOURNAL_PATH,
) -> dict[str, Any]:
    journal = load_journal(path)
    events = journal.get("events") or []
    positions = management_payload.get("positions") if isinstance(management_payload.get("positions"), list) else []
    by_id = {
        str(item.get("position_id") or ""): item
        for item in positions
        if isinstance(item, dict) and item.get("position_id")
    }
    by_ticker = {
        str(item.get("ticker") or "").upper(): item
        for item in positions
        if isinstance(item, dict) and item.get("ticker")
    }
    evaluated = []
    pending = []
    for event in events:
        if not isinstance(event, dict):
            continue
        current = by_id.get(str(event.get("position_id") or "")) or by_ticker.get(str(event.get("ticker") or "").upper())
        row = {
            "event_id": event.get("event_id"),
            "ticker": event.get("ticker"),
            "strategy": event.get("strategy"),
            "operator_action": event.get("operator_action"),
            "recommended_action": event.get("recommended_action"),
            "recorded_at": event.get("recorded_at"),
            "current_position_found": bool(current),
            "current_management_action": current.get("management_action") if isinstance(current, dict) else None,
            "current_exit_state": current.get("exit_state") if isinstance(current, dict) else "POSITION_NOT_FOUND",
            "current_premium_capture_pct": current.get("premium_capture_pct") if isinstance(current, dict) else None,
            "followup_required": bool(event.get("followup_required")) or (
                isinstance(current, dict)
                and current.get("manual_review_required") is True
                and current.get("management_action") != event.get("recommended_action")
            ),
            "not_order_instruction": True,
        }
        evaluated.append(row)
        if row["followup_required"]:
            pending.append(row)
    return {
        "evaluation_version": "position_management_journal_evaluation_v1",
        "evaluated_event_count": len(evaluated),
        "pending_followup_count": len(pending),
        "pending_followups": pending[:25],
        "evaluated_events": evaluated[:100],
        "not_order_instruction": True,
        "execution_authorized": False,
    }
