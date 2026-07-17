#!/usr/bin/env python3
"""Run a dependency vulnerability audit for Stock Ultimus.

This wrapper keeps dependency checks separate from the local information
security audit. It notifies only when a vulnerability scan completes and finds
ACTION-level vulnerable packages.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import v32_operator_notify as notify


DEFAULT_OUT = ROOT / "runtime" / "dependency_audit_latest.json"
DEFAULT_STATE = ROOT / "runtime" / "dependency_audit_state.json"
AUDIT_VERSION = "dependency_audit_v1"
PREFERRED_AUDIT_PYTHONS = (
    os.getenv("STOCK_ULTIMUS_DEPENDENCY_AUDIT_PYTHON", ""),
    "/opt/homebrew/bin/python3.11",
    "python3.11",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Stock Ultimus dependency vulnerability audit.")
    parser.add_argument("--json-out", default=str(DEFAULT_OUT))
    parser.add_argument("--state-file", default=str(DEFAULT_STATE))
    parser.add_argument("--requirements", default="requirements.txt,requirements-bridge.txt")
    parser.add_argument("--timeout", type=int, default=int(os.getenv("STOCK_ULTIMUS_DEPENDENCY_AUDIT_TIMEOUT", "180")))
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--no-send", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--pushover", action="store_true")
    parser.add_argument("--macos-notify", action="store_true")
    parser.add_argument("--webhook-url", default=os.getenv("STOCK_ULTIMUS_NOTIFY_WEBHOOK_URL", ""))
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


def requirement_paths(raw: str) -> list[Path]:
    paths = []
    for item in raw.split(","):
        name = item.strip()
        if not name:
            continue
        path = Path(name)
        paths.append(path if path.is_absolute() else ROOT / path)
    return paths


def pip_audit_command(requirements: list[Path]) -> list[str] | None:
    binary = shutil.which("pip-audit")
    audit_python = next(
        (
            candidate
            for candidate in PREFERRED_AUDIT_PYTHONS
            if candidate and (Path(candidate).exists() if candidate.startswith("/") else shutil.which(candidate))
        ),
        "",
    )
    base = [audit_python, "-m", "pip_audit"] if audit_python else ([binary] if binary else [sys.executable, "-m", "pip_audit"])
    existing = [path for path in requirements if path.exists()]
    if not existing:
        return None
    command = [*base, "--format", "json"]
    for path in existing:
        command.extend(["-r", str(path)])
    return command


def parse_pip_audit_json(raw: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw or "{}")
    except Exception:
        return []
    dependencies = payload.get("dependencies") if isinstance(payload, dict) else []
    findings: list[dict[str, Any]] = []
    for dep in dependencies or []:
        if not isinstance(dep, dict):
            continue
        vulns = dep.get("vulns") if isinstance(dep.get("vulns"), list) else []
        for vuln in vulns:
            if not isinstance(vuln, dict):
                continue
            findings.append(
                {
                    "code": "VULNERABLE_DEPENDENCY",
                    "severity": "ACTION",
                    "package": dep.get("name"),
                    "installed_version": dep.get("version"),
                    "vulnerability_id": vuln.get("id"),
                    "fix_versions": vuln.get("fix_versions") or [],
                    "description": str(vuln.get("description") or "")[:500],
                    "execution_authorized": False,
                    "not_order_instruction": True,
                }
            )
    return findings


def run_pip_audit(command: list[str], timeout: int) -> tuple[int, str, str]:
    proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def signature(findings: list[dict[str, Any]]) -> str:
    return "|".join(
        sorted(
            "{package}:{version}:{vuln}".format(
                package=item.get("package") or "",
                version=item.get("installed_version") or "",
                vuln=item.get("vulnerability_id") or "",
            )
            for item in findings
        )
    )


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    requirements = requirement_paths(args.requirements)
    existing = [path for path in requirements if path.exists()]
    missing = [str(path.relative_to(ROOT)) for path in requirements if not path.exists()]
    command = pip_audit_command(requirements)
    findings: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = [
        {
            "name": "requirements_files",
            "ok": bool(existing),
            "existing": [str(path.relative_to(ROOT)) for path in existing],
            "missing": missing,
        }
    ]
    status = "OK"
    alert_level = "OK"
    audit_exit_code: int | None = None
    stderr_tail = ""
    if not existing:
        status = "WATCH"
        alert_level = "WATCH"
        checks.append({"name": "pip_audit_scan", "ok": None, "skipped": True, "reason": "NO_REQUIREMENTS_FILES"})
    elif command is None:
        status = "WATCH"
        alert_level = "WATCH"
        checks.append({"name": "pip_audit_scan", "ok": None, "skipped": True, "reason": "NO_REQUIREMENTS_FILES"})
    else:
        try:
            audit_exit_code, stdout, stderr = run_pip_audit(command, args.timeout)
            stderr_tail = stderr[-1000:]
            findings = parse_pip_audit_json(stdout)
            if findings:
                status = "ACTION_REQUIRED"
                alert_level = "ACTION"
            elif audit_exit_code == 0:
                status = "OK"
                alert_level = "OK"
            else:
                status = "WATCH"
                alert_level = "WATCH"
            checks.append(
                {
                    "name": "pip_audit_scan",
                    "ok": audit_exit_code == 0 and not findings,
                    "exit_code": audit_exit_code,
                    "finding_count": len(findings),
                    "stderr_tail": stderr_tail,
                }
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, ModuleNotFoundError) as exc:
            status = "WATCH"
            alert_level = "WATCH"
            checks.append({"name": "pip_audit_scan", "ok": None, "skipped": True, "reason": type(exc).__name__})

    current_signature = signature(findings)
    previous_state = read_json(Path(args.state_file), {})
    duplicate = bool(current_signature and isinstance(previous_state, dict) and previous_state.get("last_signature") == current_signature)
    action_count = len(findings)
    should_notify = bool(args.force or (action_count and not duplicate))
    return {
        "engine": "STOCK_ULTIMUS_DEPENDENCY_AUDIT",
        "audit_version": AUDIT_VERSION,
        "generated_at": now_iso(),
        "status": status,
        "alert_level": alert_level,
        "ok": status == "OK",
        "checks": checks,
        "findings": findings,
        "action_count": action_count,
        "watch_count": 1 if status == "WATCH" else 0,
        "audit_exit_code": audit_exit_code,
        "state_signature": current_signature,
        "duplicate_suppressed": bool(action_count and duplicate and not args.force),
        "should_notify": should_notify,
        "notification_requested": bool(args.pushover or args.macos_notify or args.webhook_url),
        "notification_sent": False,
        "notification_results": [],
        "next_required_action": (
            "Dependency audit is clean."
            if status == "OK"
            else "Review vulnerable dependencies and update pinned requirements."
            if status == "ACTION_REQUIRED"
            else "Install/configure pip-audit or retry when dependency audit service is reachable."
        ),
        "secrets_printed": False,
        "manual_review_required": status != "OK",
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def notification_payload(report: dict[str, Any]) -> dict[str, Any]:
    findings = report.get("findings") if isinstance(report.get("findings"), list) else []
    packages = ", ".join(
        str(item.get("package"))
        for item in findings[:5]
        if item.get("package")
    )
    return {
        "engine": "STOCK_ULTIMUS_DEPENDENCY_AUDIT_NOTIFY",
        "checked_at": report.get("generated_at"),
        "operator_status": report.get("status"),
        "operator_readiness": report.get("alert_level"),
        "custom_message": f"Dependency ACTION: vulnerable packages {packages or 'review required'}",
        "classification": {
            "should_notify": bool(findings),
            "notify_reason": "DEPENDENCY_VULNERABILITY_ACTION" if findings else "NO_DEPENDENCY_ACTION",
            "actionable_count": len(findings),
            "active_alert_count": len(findings),
            "actionable_alerts": [
                {
                    "ticker": "DEP",
                    "strategy": "DEPENDENCY_AUDIT",
                    "severity": item.get("severity"),
                    "state": item.get("vulnerability_id"),
                    "main_blocker": item.get("package"),
                    "manual_review_ready": False,
                    "execution_authorized": False,
                    "not_order_instruction": True,
                }
                for item in findings[:8]
            ],
        },
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def send_webhook(report: dict[str, Any], webhook_url: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps(notification_payload(report)).encode("utf-8"),
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
    print("Stock Ultimus Dependency Audit")
    print(f"Estado: {report.get('status')} | alert={report.get('alert_level')} | ok={report.get('ok')}")
    print(f"Siguiente accion: {report.get('next_required_action')}")
    for check in report.get("checks") or []:
        marker = "SKIP" if check.get("skipped") else ("OK" if check.get("ok") else "FAIL")
        print(f"- {check.get('name')}: {marker}")
    for item in report.get("findings") or []:
        print(f"  {item.get('severity')} {item.get('package')} {item.get('vulnerability_id')}")
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
