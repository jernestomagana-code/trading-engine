#!/usr/bin/env python3
"""Run a local Stock Ultimus information-security audit.

The audit is intentionally local-first: it scans repository/runtime files and
static guardrail configuration without contacting external services. Optional
notifications are only sent for ACTION findings.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import v32_operator_notify as notify


DEFAULT_OUT = ROOT / "runtime" / "security_audit_latest.json"
DEFAULT_STATE = ROOT / "runtime" / "security_audit_state.json"
AUDIT_VERSION = "security_audit_v1"

SECRET_NAMES = (
    "READ_ACCESS_TOKEN",
    "STOCK_ULTIMUS_READ_ACCESS_TOKEN",
    "STOCK_ULTIMUS_READ_TOKEN",
    "SNAPSHOT_INGEST_TOKEN",
    "TRADING_ENGINE_INGEST_TOKEN",
    "PUSHOVER_API_TOKEN",
    "PUSHOVER_USER_KEY",
    "WEBHOOK_SECRET",
    "ADMIN_DEBUG_TOKEN",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_KEY",
    "RESEND_API_KEY",
    "OPENAI_API_KEY",
    "GITHUB_TOKEN",
)
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b("
    + "|".join(re.escape(name) for name in SECRET_NAMES)
    + r")\b\s*[:=]\s*[\"']?([^\"'\s,#}]+)"
)
PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
SKIP_DIRS = {".git", "__pycache__", ".pycache_tmp", ".mypy_cache", ".pytest_cache", "node_modules"}
TEXT_SUFFIXES = {
    ".command",
    ".conf",
    ".css",
    ".env",
    ".html",
    ".ini",
    ".json",
    ".log",
    ".md",
    ".plist",
    ".py",
    ".sh",
    ".sql",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run local Stock Ultimus security audit.")
    parser.add_argument("--runtime-dir", default=str(ROOT / "runtime"))
    parser.add_argument("--json-out", default=str(DEFAULT_OUT))
    parser.add_argument("--state-file", default=str(DEFAULT_STATE))
    parser.add_argument("--max-file-bytes", type=int, default=int(os.getenv("STOCK_ULTIMUS_SECURITY_AUDIT_MAX_FILE_BYTES", "250000")))
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--no-send", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--pushover", action="store_true")
    parser.add_argument("--macos-notify", action="store_true")
    parser.add_argument("--webhook-url", default=os.getenv("STOCK_ULTIMUS_NOTIFY_WEBHOOK_URL", ""))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("STOCK_ULTIMUS_READ_TIMEOUT", "30")))
    return parser


def read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        return default
    return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return str(path)


def is_text_candidate(path: Path) -> bool:
    if path.name in {".env", ".env.local", ".env.production", ".env.development"}:
        return True
    return path.suffix.lower() in TEXT_SUFFIXES


def iter_audit_files(root: Path, runtime_dir: Path, max_file_bytes: int) -> Iterable[Path]:
    roots = [root]
    try:
        if runtime_dir.resolve() != root.resolve() and runtime_dir.exists():
            roots.append(runtime_dir)
    except Exception:
        pass
    seen: set[Path] = set()
    for base in roots:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if not path.is_file() or not is_text_candidate(path):
                continue
            try:
                resolved = path.resolve()
                size = path.stat().st_size
            except OSError:
                continue
            if resolved in seen or size > max_file_bytes:
                continue
            seen.add(resolved)
            yield path


def placeholder_value(value: str) -> bool:
    normalized = value.strip().strip("\"'").lower()
    if not normalized:
        return True
    if normalized in {
        "none",
        "null",
        "true",
        "false",
        "0",
        "1",
        "read-secret",
        "ingest-secret",
        "user-secret",
        "api-secret",
    }:
        return True
    if normalized in {"...", "$(", "$"}:
        return True
    return any(
        marker in normalized
        for marker in (
            "...",
            "$(",
            "replace",
            "placeholder",
            "example",
            "must-match",
            "${",
            "<",
            "keychain",
            "redacted",
        )
    )


def finding(code: str, severity: str, detail: str, *, path: str | None = None, line: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": code,
        "severity": severity,
        "detail": detail,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    if path:
        payload["path"] = path
    if line:
        payload["line"] = line
    return payload


def scan_for_secret_exposure(root: Path, runtime_dir: Path, max_file_bytes: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    scanned = 0
    for path in iter_audit_files(root, runtime_dir, max_file_bytes):
        scanned += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        relative = relpath(path, root)
        for line_number, line in enumerate(text.splitlines(), start=1):
            if PRIVATE_KEY_RE.search(line):
                findings.append(
                    finding(
                        "PRIVATE_KEY_MATERIAL_IN_REPO",
                        "ACTION",
                        "Private key material marker found in a project file.",
                        path=relative,
                        line=line_number,
                    )
                )
            for match in SECRET_ASSIGNMENT_RE.finditer(line):
                name, value = match.group(1).upper(), match.group(2)
                if placeholder_value(value):
                    continue
                findings.append(
                    finding(
                        "SENSITIVE_VALUE_IN_FILE",
                        "ACTION",
                        f"Sensitive-looking value assigned to {name}; move it to Keychain or the deployment secret store.",
                        path=relative,
                        line=line_number,
                    )
                )
    return (
        {
            "name": "secret_exposure_scan",
            "ok": not findings,
            "scanned_file_count": scanned,
            "finding_count": len(findings),
        },
        findings,
    )


def validate_gitignore(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = root / ".gitignore"
    findings: list[dict[str, Any]] = []
    required = ["runtime/", ".env", ".env.*", "!.env.example", "*.log"]
    try:
        lines = path.read_text().splitlines()
    except OSError:
        lines = []
    for entry in required:
        if entry not in lines:
            findings.append(
                finding(
                    "SENSITIVE_PATH_NOT_GITIGNORED",
                    "ACTION",
                    f"Missing {entry} in .gitignore.",
                    path=".gitignore",
                )
            )
    return ({"name": "sensitive_paths_gitignored", "ok": not findings, "required": required}, findings)


def validate_static_auth(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    app_path = root / "app" / "main.py"
    findings: list[dict[str, Any]] = []
    try:
        source = app_path.read_text()
    except OSError:
        source = ""
    checks = {
        "read_auth_middleware": "sensitive_read_auth_middleware" in source and "_path_requires_read_auth" in source,
        "constant_time_read_auth": "hmac.compare_digest" in source,
        "snapshot_ingest_verifier": "def verify_snapshot_ingest_token" in source,
        "snapshot_ingest_default_required": 'REQUIRE_SNAPSHOT_INGEST_TOKEN", "true"' in source
        or "REQUIRE_SNAPSHOT_INGEST_TOKEN', 'true'" in source,
        "read_auth_status_surface": "critical_endpoints_protected" in source,
    }
    for name, ok in checks.items():
        if not ok:
            findings.append(
                finding(
                    "STATIC_AUTH_GUARD_MISSING",
                    "ACTION",
                    f"Static auth guard check failed: {name}.",
                    path="app/main.py",
                )
            )
    return ({"name": "static_auth_guards", "ok": all(checks.values()), "checks": checks}, findings)


def validate_launchd_templates(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        from scripts import install_market_environment_launchd
    except Exception as exc:
        return (
            {"name": "launchd_templates", "ok": False, "error": str(exc)},
            [finding("LAUNCHD_TEMPLATE_IMPORT_FAILED", "ACTION", "Could not import launchd installer.")],
        )
    jobs = install_market_environment_launchd.selected_jobs(
        "auth-preflight,daily-snapshot-refresh,market-open-readiness,post-open-monitor,environment-alerts,local-dashboard,security-audit"
    )
    sensitive_terms = set(SECRET_NAMES)
    findings: list[dict[str, Any]] = []
    inspected = 0
    for name, job in jobs.items():
        inspected += 1
        raw = json.dumps(install_market_environment_launchd.plist_payload(job), sort_keys=True)
        leaked_terms = sorted(term for term in sensitive_terms if term in raw)
        if leaked_terms:
            findings.append(
                finding(
                    "LAUNCHD_TEMPLATE_EMBEDS_SECRET_NAME",
                    "ACTION",
                    f"Launchd job {name} embeds secret env names; keep secrets in Keychain/env lookup only.",
                )
            )
    return ({"name": "launchd_templates", "ok": not findings, "inspected_job_count": inspected}, findings)


def validate_guardrail_defaults(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    inspected_paths = ["app/main.py", "ibkr_bridge.py", "durable_storage.py"]
    for relative in inspected_paths:
        path = root / relative
        try:
            source = path.read_text()
        except OSError:
            findings.append(finding("GUARDRAIL_SOURCE_MISSING", "ACTION", "Guardrail source file is missing.", path=relative))
            continue
        if '"execution_authorized": True' in source or "'execution_authorized': True" in source:
            findings.append(
                finding(
                    "EXECUTION_AUTHORIZATION_TRUE_IN_CORE",
                    "ACTION",
                    "Core source contains execution_authorized=true.",
                    path=relative,
                )
            )
        if "not_order_instruction" not in source:
            findings.append(
                finding(
                    "NO_ORDER_GUARDRAIL_MISSING_IN_CORE",
                    "ACTION",
                    "Core source is missing not_order_instruction guardrail references.",
                    path=relative,
                )
            )
    return ({"name": "no_order_guardrails", "ok": not findings, "inspected_paths": inspected_paths}, findings)


def signature(findings: list[dict[str, Any]]) -> str:
    return "|".join(
        sorted(
            "{code}:{severity}:{path}:{line}".format(
                code=item.get("code"),
                severity=item.get("severity"),
                path=item.get("path") or "",
                line=item.get("line") or "",
            )
            for item in findings
        )
    )


def status_from_findings(findings: list[dict[str, Any]]) -> tuple[str, str]:
    if any(item.get("severity") == "ACTION" for item in findings):
        return "ACTION_REQUIRED", "ACTION"
    if any(item.get("severity") == "WATCH" for item in findings):
        return "WATCH", "WATCH"
    return "OK", "OK"


def notification_payload(report: dict[str, Any]) -> dict[str, Any]:
    findings = report.get("findings") if isinstance(report.get("findings"), list) else []
    action_findings = [item for item in findings if item.get("severity") == "ACTION"]
    codes = ", ".join(str(item.get("code")) for item in action_findings[:4])
    return {
        "engine": "STOCK_ULTIMUS_SECURITY_AUDIT_NOTIFY",
        "checked_at": report.get("generated_at"),
        "operator_status": report.get("status"),
        "operator_readiness": report.get("alert_level"),
        "custom_message": f"Security ACTION: {codes or 'review required'}",
        "classification": {
            "should_notify": bool(action_findings),
            "notify_reason": "SECURITY_ACTION" if action_findings else "NO_SECURITY_ACTION",
            "actionable_count": len(action_findings),
            "active_alert_count": len(findings),
            "actionable_alerts": [
                {
                    "ticker": "SEC",
                    "strategy": "SECURITY_AUDIT",
                    "severity": item.get("severity"),
                    "state": item.get("code"),
                    "main_blocker": item.get("detail"),
                    "manual_review_ready": False,
                    "execution_authorized": False,
                    "not_order_instruction": True,
                }
                for item in action_findings[:8]
            ],
        },
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def send_webhook(report: dict[str, Any], webhook_url: str, timeout: int) -> dict[str, Any]:
    payload = notification_payload(report)
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
            return {"sent": 200 <= response.status < 300, "provider": "webhook", "status_code": response.status}
    except urllib.error.HTTPError as exc:
        return {"sent": False, "provider": "webhook", "status_code": exc.code}
    except (TimeoutError, socket.timeout) as exc:
        return {"sent": False, "provider": "webhook", "error": f"TIMEOUT: {exc}"}
    except urllib.error.URLError as exc:
        return {"sent": False, "provider": "webhook", "error": str(exc)}


def build_report(args: argparse.Namespace, *, root: Path = ROOT) -> dict[str, Any]:
    runtime_dir = Path(args.runtime_dir)
    checks: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for check, new_findings in [
        scan_for_secret_exposure(root, runtime_dir, args.max_file_bytes),
        validate_gitignore(root),
        validate_static_auth(root),
        validate_launchd_templates(root),
        validate_guardrail_defaults(root),
    ]:
        checks.append(check)
        findings.extend(new_findings)

    status, alert_level = status_from_findings(findings)
    action_count = sum(1 for item in findings if item.get("severity") == "ACTION")
    watch_count = sum(1 for item in findings if item.get("severity") == "WATCH")
    current_signature = signature(findings)
    previous_state = read_json(Path(args.state_file), {})
    duplicate = bool(current_signature and isinstance(previous_state, dict) and previous_state.get("last_signature") == current_signature)
    should_notify = bool(args.force or (action_count and not duplicate))
    report = {
        "engine": "STOCK_ULTIMUS_SECURITY_AUDIT",
        "audit_version": AUDIT_VERSION,
        "generated_at": now_iso(),
        "status": status,
        "alert_level": alert_level,
        "ok": status == "OK",
        "checks": checks,
        "findings": findings,
        "action_count": action_count,
        "watch_count": watch_count,
        "state_signature": current_signature,
        "duplicate_suppressed": bool(action_count and duplicate and not args.force),
        "should_notify": should_notify,
        "notification_requested": bool(args.pushover or args.macos_notify or args.webhook_url),
        "notification_sent": False,
        "notification_results": [],
        "next_required_action": (
            "Security audit is clean."
            if status == "OK"
            else "Review ACTION security findings before relying on automation."
        ),
        "secrets_printed": False,
        "manual_review_required": status != "OK",
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    return report


def maybe_notify(report: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    if args.no_send or not report.get("should_notify"):
        return report
    channel_payload = notification_payload(report)
    if args.macos_notify:
        report["notification_results"].append(notify.send_macos_notification(channel_payload))
    if args.pushover:
        report["notification_results"].append(
            notify.send_pushover_notification(
                channel_payload,
                notify.first_keychain_password(notify.PUSHOVER_USER_KEYCHAIN_SERVICES),
                notify.first_keychain_password(notify.PUSHOVER_API_TOKEN_KEYCHAIN_SERVICES),
                args.timeout,
            )
        )
    if args.webhook_url:
        report["notification_results"].append(send_webhook(report, args.webhook_url, args.timeout))
    report["notification_sent"] = any(item.get("sent") for item in report["notification_results"])
    return report


def print_human(report: dict[str, Any]) -> None:
    print("Stock Ultimus Security Audit")
    print(f"Estado: {report.get('status')} | alert={report.get('alert_level')} | ok={report.get('ok')}")
    print(f"Siguiente accion: {report.get('next_required_action')}")
    for check in report.get("checks") or []:
        marker = "OK" if check.get("ok") else "FAIL"
        print(f"- {check.get('name')}: {marker}")
    for item in report.get("findings") or []:
        where = f" {item.get('path')}:{item.get('line')}" if item.get("path") else ""
        print(f"  {item.get('severity')} {item.get('code')}{where}")
    print("Guardrail: secrets_printed=false; execution_authorized=false; not_order_instruction=true.")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = maybe_notify(build_report(args), args)
    if not args.no_write:
        write_json(Path(args.json_out), report)
        if report.get("should_notify") and not args.no_send:
            write_json(
                Path(args.state_file),
                {
                    "last_signature": report.get("state_signature"),
                    "last_checked_at": report.get("generated_at"),
                    "last_status": report.get("status"),
                },
            )
    print_human(report)
    return 0 if report.get("status") in {"OK", "WATCH"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
