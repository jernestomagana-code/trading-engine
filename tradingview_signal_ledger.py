"""Persistent TradingView signal ledger for Stock Ultimus.

This records webhook evidence only. It does not classify a signal as tradable
and does not authorize orders.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import tradingview_payload_contract


LEDGER_VERSION = "tradingview_signal_ledger_v2"
REQUIRED_CONTEXT_FIELDS = [
    "session_state",
    "vwap",
    "opening_range_high",
    "opening_range_low",
    "breakout_direction",
    "adx",
    "atr",
    "volume_relative",
    "premarket_high",
    "premarket_low",
    "major_event_window",
    "risk_daily_status",
    "portfolio_status",
]
DEFAULT_LEDGER_PATH = Path("runtime/v32_signal_events.json")
MAX_EVENTS = 20000


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_upper(value: Any, default: str = "") -> str:
    text = str(value or "").strip().upper()
    return text or default


def _hash_payload(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read_events(path: Path) -> list[dict[str, Any]]:
    try:
        if not path.exists():
            return []
        data = json.loads(path.read_text())
        if isinstance(data, dict) and isinstance(data.get("events"), list):
            return [item for item in data["events"] if isinstance(item, dict)]
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    except Exception:
        return []
    return []


def _write_events(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(events[-MAX_EVENTS:], indent=2, sort_keys=True, default=str) + "\n")


def normalize_signal_event(payload: dict[str, Any], *, raw_text: str = "", endpoint: str = "", received_at: str | None = None) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    validation = tradingview_payload_contract.validate_payload(payload)
    normalized_payload = validation.get("normalized_payload") if isinstance(validation.get("normalized_payload"), dict) else payload
    received_at = received_at or now_iso()
    ticker = safe_upper(normalized_payload.get("ticker"), "UNKNOWN")
    timeframe = str(normalized_payload.get("timeframe") or "UNKNOWN").strip() or "UNKNOWN"
    strategy_context = safe_upper(normalized_payload.get("strategy_context"), "GENERAL_TECHNICAL")
    raw_preview = raw_text[:1000] if raw_text else json.dumps(payload, sort_keys=True, default=str)[:1000]
    idempotency_seed = {
        "endpoint": endpoint,
        "ticker": ticker,
        "timeframe": timeframe,
        "strategy_context": strategy_context,
        "event": normalized_payload.get("event") or normalized_payload.get("event_code") or normalized_payload.get("action") or normalized_payload.get("signal"),
        "price": normalized_payload.get("price"),
        "received_minute": received_at[:16],
        "payload_hash": _hash_payload(payload)[:16],
    }
    event_id = "TV-" + _hash_payload(idempotency_seed)[:24]
    session_state = normalized_payload.get("session_state")
    event = {
        "id": event_id,
        "event_id": event_id,
        "ledger_version": LEDGER_VERSION,
        "payload_contract_version": tradingview_payload_contract.PAYLOAD_CONTRACT_VERSION,
        "received_at": received_at,
        "endpoint": endpoint,
        "ticker": ticker,
        "timeframe": timeframe,
        "strategy_context": strategy_context,
        "event": normalized_payload.get("event"),
        "event_code": normalized_payload.get("event_code"),
        "action": normalized_payload.get("action") or normalized_payload.get("signal"),
        "price": normalized_payload.get("price"),
        "vwap": normalized_payload.get("vwap"),
        "vwap_position": normalized_payload.get("vwap_position"),
        "opening_range_high": normalized_payload.get("opening_range_high"),
        "opening_range_low": normalized_payload.get("opening_range_low"),
        "breakout_direction": normalized_payload.get("breakout_direction"),
        "session_state": session_state,
        "adx": normalized_payload.get("adx"),
        "atr": normalized_payload.get("atr"),
        "volume_relative": normalized_payload.get("volume_relative"),
        "premarket_high": normalized_payload.get("premarket_high"),
        "premarket_low": normalized_payload.get("premarket_low"),
        "invalidation": normalized_payload.get("invalidation"),
        "logical_stop": normalized_payload.get("logical_stop"),
        "logical_target": normalized_payload.get("logical_target"),
        "risk_daily_status": normalized_payload.get("risk_daily_status"),
        "portfolio_status": normalized_payload.get("portfolio_status"),
        "major_event_window": normalized_payload.get("major_event_window"),
        "payload_hash": _hash_payload(payload),
        "raw_payload": payload,
        "raw_payload_preview": raw_preview,
        "payload_validation": {
            "valid": validation.get("valid"),
            "missing_fields": validation.get("missing_fields") or [],
            "invalid_numeric_fields": validation.get("invalid_numeric_fields") or [],
            "warnings": validation.get("warnings") or [],
            "placeholder_fields": validation.get("placeholder_fields") or [],
        },
        "candidate_source": "TRADINGVIEW_ALERT",
        "confirmation_source": "TRADINGVIEW_ALERT",
        "delivery_status": "RECEIVED",
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    event["missing_context_fields"] = [
        field for field in REQUIRED_CONTEXT_FIELDS
        if event.get(field) in [None, "", "None"]
    ]
    event["context_completeness_pct"] = round(
        ((len(REQUIRED_CONTEXT_FIELDS) - len(event["missing_context_fields"])) / len(REQUIRED_CONTEXT_FIELDS)) * 100,
        2,
    )
    return event


def append_signal_event(
    payload: dict[str, Any],
    *,
    raw_text: str = "",
    endpoint: str = "",
    path: str | Path = DEFAULT_LEDGER_PATH,
) -> dict[str, Any]:
    target = Path(path)
    event = normalize_signal_event(payload, raw_text=raw_text, endpoint=endpoint)
    events = _read_events(target)
    existing_ids = {item.get("event_id") or item.get("id") for item in events}
    duplicate = event["event_id"] in existing_ids
    if not duplicate:
        events.append(event)
        _write_events(target, events)
    return {
        "status": "DUPLICATE" if duplicate else "RECORDED",
        "saved": not duplicate,
        "event_id": event["event_id"],
        "path": str(target),
        "event": event,
        "event_count": len(events),
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def load_signal_events(path: str | Path = DEFAULT_LEDGER_PATH, limit: int = 1000) -> list[dict[str, Any]]:
    try:
        limit = max(1, min(int(limit or 1000), MAX_EVENTS))
    except Exception:
        limit = 1000
    return _read_events(Path(path))[-limit:]
