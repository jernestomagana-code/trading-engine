"""Production readiness checks for Stock Ultimus deployments."""

from __future__ import annotations

from typing import Any


READINESS_VERSION = "production_readiness_v1"
SAFE_OPERATING_MODE = "ANALYSIS_ONLY"


def _is_placeholder(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return True
    return any(marker in text for marker in [
        "replace-with",
        "must-match",
        "your-service",
        "example",
        "changeme",
        "placeholder",
    ])


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _int(value: Any, default: int = 0) -> int:
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(value)
    except Exception:
        return default


def _check(name: str, ok: bool, severity: str, detail: str) -> dict[str, Any]:
    return {
        "name": name,
        "ok": bool(ok),
        "severity": severity,
        "detail": detail,
    }


def assess(config: dict[str, Any]) -> dict[str, Any]:
    deployment_env = str(config.get("deployment_env") or "local").strip().lower()
    production_like = deployment_env in {"prod", "production", "render"}
    operating_mode = str(config.get("operating_mode") or "").strip().upper()

    snapshot_required = _bool(config.get("require_snapshot_ingest_token"))
    snapshot_token_configured = not _is_placeholder(config.get("snapshot_ingest_token"))
    webhook_required = _bool(config.get("require_webhook_secret"))
    webhook_secret_configured = not _is_placeholder(config.get("webhook_secret"))
    public_base_url = str(config.get("public_base_url") or "").strip()
    resend_api_configured = not _is_placeholder(config.get("resend_api_key"))
    resend_plan_limit = _int(config.get("resend_daily_plan_limit"), 0)
    resend_limit_percent = _int(config.get("resend_daily_limit_percent"), 100)

    checks = [
        _check(
            "operating_mode_analysis_only",
            operating_mode == SAFE_OPERATING_MODE,
            "blocker",
            "Production must remain decision-support only; automatic/live execution modes are not allowed.",
        ),
        _check(
            "snapshot_ingest_token_required",
            snapshot_required,
            "blocker",
            "Snapshot ingest endpoints must require a token.",
        ),
        _check(
            "snapshot_ingest_token_configured",
            snapshot_token_configured,
            "blocker",
            "Snapshot ingest token must be configured with a non-placeholder value.",
        ),
        _check(
            "webhook_secret_required",
            webhook_required,
            "blocker",
            "TradingView/webhook ingestion must require a secret.",
        ),
        _check(
            "webhook_secret_configured",
            webhook_secret_configured,
            "blocker",
            "Webhook secret must be configured with a non-placeholder value.",
        ),
        _check(
            "execution_authorized_false",
            config.get("execution_authorized") is False,
            "blocker",
            "The production app must not authorize order execution.",
        ),
    ]

    if production_like:
        checks.append(_check(
            "public_base_url_https",
            public_base_url.startswith("https://") and not _is_placeholder(public_base_url),
            "blocker",
            "Production deployments must expose a concrete HTTPS public base URL.",
        ))

    if resend_api_configured:
        checks.append(_check(
            "resend_daily_limit_configured",
            resend_plan_limit > 0 and 0 < resend_limit_percent <= 100,
            "blocker",
            "Resend usage limits must be configured when RESEND_API_KEY is present.",
        ))

    blockers = [item for item in checks if item.get("severity") == "blocker" and not item.get("ok")]
    warnings = [item for item in checks if item.get("severity") == "warning" and not item.get("ok")]
    status = "READY" if not blockers else "BLOCKED"

    return {
        "readiness_version": READINESS_VERSION,
        "status": status,
        "production_like": production_like,
        "deployment_env": deployment_env,
        "operating_mode": operating_mode,
        "blockers": blockers,
        "warnings": warnings,
        "checks": checks,
        "not_order_instruction": True,
        "execution_authorized": False,
        "sensitive_values_excluded": True,
    }
