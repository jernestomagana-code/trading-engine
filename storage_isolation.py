"""Storage durability and tenant/account isolation gates."""

from __future__ import annotations

from typing import Any


ISOLATION_VERSION = "storage_isolation_v1"
PERSONAL_SCOPE = "personal"
COMMERCIAL_SCOPES = {"commercial", "multi_user", "customer", "third_party"}
DURABLE_STORAGE_MODES = {"supabase", "postgres", "managed_postgres", "render_disk_encrypted"}


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _check(name: str, ok: bool, severity: str, detail: str) -> dict[str, Any]:
    return {
        "name": name,
        "ok": bool(ok),
        "severity": severity,
        "detail": detail,
    }


def assess(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or {}
    deployment_scope = str(config.get("deployment_scope") or PERSONAL_SCOPE).strip().lower()
    storage_mode = str(config.get("runtime_storage_mode") or "local_json").strip().lower()
    commercial_like = deployment_scope in COMMERCIAL_SCOPES

    durable_storage_enabled = _bool(config.get("durable_storage_enabled")) or storage_mode in DURABLE_STORAGE_MODES
    tenant_isolation_enabled = _bool(config.get("tenant_isolation_enabled"))
    account_isolation_enabled = _bool(config.get("account_isolation_enabled"))
    audit_log_enabled = _bool(config.get("audit_log_enabled"))
    retention_policy_enabled = _bool(config.get("retention_policy_enabled"))

    checks = [
        _check(
            "audit_log_enabled",
            audit_log_enabled,
            "blocker",
            "Audit logging must be enabled before production operation.",
        ),
        _check(
            "retention_policy_enabled",
            retention_policy_enabled,
            "blocker",
            "Runtime retention policy must be enabled before production operation.",
        ),
    ]

    if commercial_like:
        checks.extend([
            _check(
                "durable_storage_enabled",
                durable_storage_enabled,
                "blocker",
                "Commercial or multi-user scope requires durable managed storage; local JSON is personal-use only.",
            ),
            _check(
                "tenant_isolation_enabled",
                tenant_isolation_enabled,
                "blocker",
                "Commercial or multi-user scope requires explicit tenant isolation.",
            ),
            _check(
                "account_isolation_enabled",
                account_isolation_enabled,
                "blocker",
                "Commercial or multi-user scope requires account-level isolation.",
            ),
        ])
    else:
        checks.append(_check(
            "local_json_personal_only",
            storage_mode == "local_json" or durable_storage_enabled,
            "warning",
            "Local JSON storage is acceptable only for personal/single-user operation.",
        ))

    blockers = [item for item in checks if item.get("severity") == "blocker" and not item.get("ok")]
    warnings = [item for item in checks if item.get("severity") == "warning" and not item.get("ok")]

    return {
        "isolation_version": ISOLATION_VERSION,
        "status": "READY" if not blockers else "BLOCKED",
        "deployment_scope": deployment_scope,
        "runtime_storage_mode": storage_mode,
        "commercial_like": commercial_like,
        "durable_storage_enabled": durable_storage_enabled,
        "tenant_isolation_enabled": tenant_isolation_enabled,
        "account_isolation_enabled": account_isolation_enabled,
        "blockers": blockers,
        "warnings": warnings,
        "checks": checks,
        "personal_use_only": not commercial_like and not durable_storage_enabled,
        "commercial_ready": commercial_like and not blockers,
        "sensitive_values_excluded": True,
        "not_order_instruction": True,
        "execution_authorized": False,
    }
