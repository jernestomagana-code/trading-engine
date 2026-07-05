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
    received_at = received_at or now_iso()
    ticker = safe_upper(payload.get("ticker") or payload.get("symbol") or payload.get("chart_ticker"), "UNKNOWN")
    timeframe = str(payload.get("timeframe") or payload.get("interval") or payload.get("tf") or "UNKNOWN").strip() or "UNKNOWN"
    strategy_context = safe_upper(payload.get("strategy_context") or payload.get("strategy") or payload.get("setup"), "GENERAL_TECHNICAL")
    raw_preview = raw_text[:1000] if raw_text else json.dumps(payload, sort_keys=True, default=str)[:1000]
    idempotency_seed = {
        "endpoint": endpoint,
        "ticker": ticker,
        "timeframe": timeframe,
        "strategy_context": strategy_context,
        "event": payload.get("event") or payload.get("event_code") or payload.get("action") or payload.get("signal"),
        "price": payload.get("price") or payload.get("close") or payload.get("last"),
        "received_minute": received_at[:16],
        "payload_hash": _hash_payload(payload)[:16],
    }
    event_id = "TV-" + _hash_payload(idempotency_seed)[:24]
    session_state = payload.get("session_state") or payload.get("market_session")
    event = {
        "id": event_id,
        "event_id": event_id,
        "ledger_version": LEDGER_VERSION,
        "payload_contract_version": "tradingview_signal_payload_v2",
        "received_at": received_at,
        "endpoint": endpoint,
        "ticker": ticker,
        "timeframe": timeframe,
        "strategy_context": strategy_context,
        "event": payload.get("event"),
        "event_code": payload.get("event_code"),
        "action": payload.get("action") or payload.get("signal"),
        "price": payload.get("price") or payload.get("close") or payload.get("last"),
        "vwap": payload.get("vwap") or payload.get("vwap_value"),
        "vwap_position": payload.get("vwap_position"),
        "opening_range_high": payload.get("opening_range_high"),
        "opening_range_low": payload.get("opening_range_low"),
        "breakout_direction": payload.get("breakout_direction") or payload.get("direction"),
        "session_state": session_state,
        "adx": payload.get("adx"),
        "atr": payload.get("atr"),
        "volume_relative": payload.get("volume_relative") or payload.get("relative_volume") or payload.get("rvol"),
        "premarket_high": payload.get("premarket_high"),
        "premarket_low": payload.get("premarket_low"),
        "invalidation": payload.get("invalidation") or payload.get("invalid_above_below") or payload.get("invalidates_at"),
        "logical_stop": payload.get("logical_stop") or payload.get("stop_logical") or payload.get("stop"),
        "logical_target": payload.get("logical_target") or payload.get("target_logical") or payload.get("target"),
        "risk_daily_status": payload.get("risk_daily_status"),
        "portfolio_status": payload.get("portfolio_status"),
        "major_event_window": payload.get("major_event_window"),
        "payload_hash": _hash_payload(payload),
        "raw_payload": payload,
        "raw_payload_preview": raw_preview,
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
