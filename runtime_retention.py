"""Runtime retention policy helpers for Stock Ultimus."""

from __future__ import annotations

from typing import Any


RETENTION_POLICY_VERSION = "runtime_retention_policy_v1"
DEFAULT_DECISION_JOURNAL_MAX = 5000
DEFAULT_OUTCOME_JOURNAL_MAX = 5000
DEFAULT_AUDIT_LOG_MAX = 10000
MIN_RETENTION_ITEMS = 100
MAX_RETENTION_ITEMS = 100000


def bounded_int(value: Any, default: int, *, minimum: int = MIN_RETENTION_ITEMS, maximum: int = MAX_RETENTION_ITEMS) -> int:
    try:
        if value is None or str(value).strip() == "":
            result = default
        else:
            result = int(value)
    except Exception:
        result = default
    return max(minimum, min(maximum, result))


def policy(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or {}
    decision_max = bounded_int(config.get("decision_journal_max"), DEFAULT_DECISION_JOURNAL_MAX)
    outcome_max = bounded_int(config.get("outcome_journal_max"), DEFAULT_OUTCOME_JOURNAL_MAX)
    audit_max = bounded_int(config.get("audit_log_max"), DEFAULT_AUDIT_LOG_MAX)

    return {
        "retention_policy_version": RETENTION_POLICY_VERSION,
        "decision_journal_max": decision_max,
        "outcome_journal_max": outcome_max,
        "audit_log_max": audit_max,
        "runtime_storage_mode": config.get("runtime_storage_mode") or "local_json",
        "durable_storage_required_before_commercial": True,
        "sensitive_values_redacted": True,
    }


def trim_items(items: list[Any], max_items: int) -> list[Any]:
    try:
        limit = int(max_items)
    except Exception:
        limit = len(items or [])
    if limit <= 0:
        return []
    return list(items or [])[-limit:]


def summary(policy_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "retention_policy_version": policy_payload.get("retention_policy_version") or RETENTION_POLICY_VERSION,
        "decision_journal_max": policy_payload.get("decision_journal_max"),
        "outcome_journal_max": policy_payload.get("outcome_journal_max"),
        "audit_log_max": policy_payload.get("audit_log_max"),
        "runtime_storage_mode": policy_payload.get("runtime_storage_mode"),
        "durable_storage_required_before_commercial": True,
        "sensitive_values_redacted": True,
    }
