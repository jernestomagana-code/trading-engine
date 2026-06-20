"""Append-only redacted audit logging for Stock Ultimus."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4


AUDIT_LOG_VERSION = "audit_log_v1"
DEFAULT_AUDIT_LOG_PATH = Path("runtime/stock_ultimus_audit_log.json")
MAX_AUDIT_EVENTS = 10000
SENSITIVE_KEY_MARKERS = [
    "account",
    "acct",
    "authorization",
    "balance",
    "buying_power",
    "cash",
    "cookie",
    "credential",
    "home_dir",
    "local_path",
    "net_liquidation",
    "password",
    "secret",
    "session",
    "supabase_key",
    "token",
    "api_key",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_sensitive_key(key: Any) -> bool:
    text = str(key or "").lower()
    return any(marker in text for marker in SENSITIVE_KEY_MARKERS)


def redact(value: Any, *, max_depth: int = 5) -> Any:
    if max_depth < 0:
        return "[MAX_DEPTH_REDACTED]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            result[str(key)] = "[REDACTED]" if is_sensitive_key(key) else redact(item, max_depth=max_depth - 1)
        return result
    if isinstance(value, list):
        return [redact(item, max_depth=max_depth - 1) for item in value[:200]]
    if isinstance(value, tuple):
        return [redact(item, max_depth=max_depth - 1) for item in value[:200]]
    return value


def read_events(path: str | Path = DEFAULT_AUDIT_LOG_PATH) -> list[dict[str, Any]]:
    try:
        p = Path(path)
        if not p.exists():
            return []
        data = json.loads(p.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def write_events(
    events: list[dict[str, Any]],
    path: str | Path = DEFAULT_AUDIT_LOG_PATH,
    *,
    max_events: int = MAX_AUDIT_EVENTS,
) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(events[-max_events:], indent=2, ensure_ascii=False, default=str))


def append_event(
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    path: str | Path = DEFAULT_AUDIT_LOG_PATH,
    actor: str = "system",
    source: str = "app",
    max_events: int = MAX_AUDIT_EVENTS,
) -> dict[str, Any]:
    recorded_at = now_iso()
    event = {
        "event_id": f"AUD-{int(datetime.now(timezone.utc).timestamp() * 1000)}-{uuid4().hex[:12]}",
        "audit_log_version": AUDIT_LOG_VERSION,
        "event_type": str(event_type or "UNKNOWN"),
        "recorded_at": recorded_at,
        "actor": actor,
        "source": source,
        "payload": redact(payload or {}),
        "sensitive_values_redacted": True,
        "not_order_instruction": True,
    }
    events = read_events(path)
    events.append(event)
    write_events(events, path, max_events=max_events)
    return event
