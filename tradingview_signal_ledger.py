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

import tradingview_alert_coverage
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
OPTIONS_CONTEXT_FIELDS = [
    "rsi",
    "rsi_state",
    "trend_state",
    "market_regime",
    "underlying_signal",
]
DEFAULT_LEDGER_PATH = Path("runtime/v32_signal_events.json")
DEFAULT_WEBHOOK_STATUS_PATH = Path("runtime/v32_tradingview_webhook_status.json")
MAX_EVENTS = 20000
DEFAULT_COVERAGE_PATH = tradingview_alert_coverage.DEFAULT_COVERAGE_PATH
DEFAULT_EXTRA_COVERAGE_PATHS = [
    Path("config/tradingview_options_underlying_alert_coverage_v1.json"),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_upper(value: Any, default: str = "") -> str:
    text = str(value or "").strip().upper()
    return text or default


def _hash_payload(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _known_event_codes(coverage_path: str | Path = DEFAULT_COVERAGE_PATH) -> set[str]:
    paths = [Path(coverage_path)]
    if Path(coverage_path) == DEFAULT_COVERAGE_PATH:
        paths.extend(path for path in DEFAULT_EXTRA_COVERAGE_PATHS if path.exists())
    codes: set[str] = set()
    for path in paths:
        try:
            coverage = tradingview_alert_coverage.load_coverage(path)
        except Exception:
            continue
        codes.update(
            safe_upper(item.get("event_code"))
            for item in tradingview_alert_coverage.alerts(coverage)
            if safe_upper(item.get("event_code"))
        )
    return codes


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


def _read_webhook_status(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text())
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {
        "status_version": "tradingview_webhook_status_v1",
        "webhook_attempt_count": 0,
        "accepted_count": 0,
        "quarantined_count": 0,
        "duplicate_count": 0,
        "last_webhook": None,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def _write_webhook_status(
    path: Path,
    *,
    result_status: str,
    event: dict[str, Any],
    duplicate: bool,
    event_count: int,
) -> dict[str, Any]:
    status = _read_webhook_status(path)
    status["status_version"] = "tradingview_webhook_status_v1"
    status["webhook_attempt_count"] = int(status.get("webhook_attempt_count") or 0) + 1
    if duplicate:
        status["duplicate_count"] = int(status.get("duplicate_count") or 0) + 1
    elif event.get("accepted_for_engine"):
        status["accepted_count"] = int(status.get("accepted_count") or 0) + 1
    else:
        status["quarantined_count"] = int(status.get("quarantined_count") or 0) + 1
    status["last_webhook"] = {
        "received_at": event.get("received_at"),
        "endpoint": event.get("endpoint"),
        "status": result_status,
        "event_id": event.get("event_id"),
        "ticker": event.get("ticker"),
        "timeframe": event.get("timeframe"),
        "strategy_context": event.get("strategy_context"),
        "event_code": event.get("event_code"),
        "accepted_for_engine": event.get("accepted_for_engine"),
        "quarantine_reasons": event.get("quarantine_reasons") or [],
        "payload_valid": (event.get("payload_validation") or {}).get("valid"),
        "missing_fields": (event.get("payload_validation") or {}).get("missing_fields") or [],
    }
    status["ledger_event_count"] = event_count
    status["updated_at"] = now_iso()
    status["execution_authorized"] = False
    status["not_order_instruction"] = True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, indent=2, sort_keys=True, default=str) + "\n")
    return status


def _required_context_fields(strategy_context: str) -> list[str]:
    fields = list(REQUIRED_CONTEXT_FIELDS)
    if safe_upper(strategy_context) == tradingview_payload_contract.OPTIONS_UNDERLYING_CONTEXT:
        fields.extend(field for field in OPTIONS_CONTEXT_FIELDS if field not in fields)
    return fields


def normalize_signal_event(
    payload: dict[str, Any],
    *,
    raw_text: str = "",
    endpoint: str = "",
    received_at: str | None = None,
    coverage_path: str | Path = DEFAULT_COVERAGE_PATH,
) -> dict[str, Any]:
    original_is_dict = isinstance(payload, dict)
    payload = payload if original_is_dict else {}
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
    known_codes = _known_event_codes(coverage_path)
    event_code = safe_upper(normalized_payload.get("event_code"))
    action = safe_upper(normalized_payload.get("action") or normalized_payload.get("signal"))
    quarantine_reasons = []
    if not validation.get("valid"):
        quarantine_reasons.append("PAYLOAD_CONTRACT_FAILED")
    if not event_code:
        quarantine_reasons.append("MISSING_EVENT_CODE")
    elif known_codes and event_code not in known_codes:
        quarantine_reasons.append("UNKNOWN_EVENT_CODE")
    if action and action != "ALERT_ONLY":
        quarantine_reasons.append("NON_ALERT_ONLY_ACTION")
    if not original_is_dict:
        quarantine_reasons.append("NON_DICT_PAYLOAD")
    accepted_for_engine = not quarantine_reasons
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
        "event_code": event_code or normalized_payload.get("event_code"),
        "action": action or normalized_payload.get("action") or normalized_payload.get("signal"),
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
        "rsi": normalized_payload.get("rsi"),
        "rsi_state": normalized_payload.get("rsi_state"),
        "rsi_divergence": normalized_payload.get("rsi_divergence"),
        "ema_fast": normalized_payload.get("ema_fast"),
        "ema_slow": normalized_payload.get("ema_slow"),
        "trend_state": normalized_payload.get("trend_state"),
        "trend_strength": normalized_payload.get("trend_strength"),
        "market_regime": normalized_payload.get("market_regime"),
        "underlying_signal": normalized_payload.get("underlying_signal"),
        "volatility_state": normalized_payload.get("volatility_state"),
        "confirmation_bias": normalized_payload.get("confirmation_bias"),
        "payload_hash": _hash_payload(payload),
        "idempotency_key": event_id,
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
        "alert_contract_status": "ACCEPTED" if accepted_for_engine else "QUARANTINED",
        "delivery_status": "RECEIVED" if accepted_for_engine else "QUARANTINED",
        "accepted_for_engine": accepted_for_engine,
        "quarantine_reasons": quarantine_reasons,
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    required_context_fields = _required_context_fields(strategy_context)
    event["missing_context_fields"] = [
        field for field in required_context_fields
        if event.get(field) in [None, "", "None"]
    ]
    event["context_completeness_pct"] = round(
        ((len(required_context_fields) - len(event["missing_context_fields"])) / len(required_context_fields)) * 100,
        2,
    )
    return event


def append_signal_event(
    payload: dict[str, Any],
    *,
    raw_text: str = "",
    endpoint: str = "",
    path: str | Path = DEFAULT_LEDGER_PATH,
    status_path: str | Path = DEFAULT_WEBHOOK_STATUS_PATH,
    coverage_path: str | Path = DEFAULT_COVERAGE_PATH,
) -> dict[str, Any]:
    target = Path(path)
    event = normalize_signal_event(payload, raw_text=raw_text, endpoint=endpoint, coverage_path=coverage_path)
    events = _read_events(target)
    existing_ids = {item.get("event_id") or item.get("id") for item in events}
    duplicate = event["event_id"] in existing_ids
    if not duplicate:
        events.append(event)
        _write_events(target, events)
    result_status = "DUPLICATE" if duplicate else event["delivery_status"]
    webhook_status = _write_webhook_status(
        Path(status_path),
        result_status=result_status,
        event=event,
        duplicate=duplicate,
        event_count=len(events),
    )
    return {
        "status": result_status,
        "saved": not duplicate,
        "event_id": event["event_id"],
        "path": str(target),
        "status_path": str(status_path),
        "event": event,
        "webhook_status": webhook_status,
        "accepted_for_engine": event["accepted_for_engine"],
        "quarantine_reasons": event["quarantine_reasons"],
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


def load_webhook_status(path: str | Path = DEFAULT_WEBHOOK_STATUS_PATH) -> dict[str, Any]:
    return _read_webhook_status(Path(path))
