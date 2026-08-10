#!/usr/bin/env python3
"""Notify on environment-level Stock Ultimus readiness issues."""

from __future__ import annotations

import argparse
import json
import os
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

import operator_readiness
from scripts import v32_operator_notify as notify


DEFAULT_OUT = ROOT / "runtime" / "environment_alerts_latest.json"
DEFAULT_STATE = ROOT / "runtime" / "environment_alerts_state.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Notify on Stock Ultimus environment issues.")
    parser.add_argument("--runtime-dir", default=str(ROOT / "runtime"))
    parser.add_argument("--json-out", default=str(DEFAULT_OUT))
    parser.add_argument("--state-file", default=str(DEFAULT_STATE))
    parser.add_argument("--market-closed-ok", action="store_true")
    parser.add_argument("--notify-watch", action="store_true", help="Notify WATCH, not only ACTION.")
    parser.add_argument("--auto-repair", action="store_true", help="Attempt a safe refresh/publish before escalating ACTION incidents.")
    parser.add_argument("--repair-timeout", type=int, default=int(os.getenv("STOCK_ULTIMUS_REPAIR_TIMEOUT", "420")))
    parser.add_argument("--min-persistent-minutes", type=int, default=int(os.getenv("STOCK_ULTIMUS_ALERT_MIN_PERSISTENT_MINUTES", "15")))
    parser.add_argument("--min-repair-attempts", type=int, default=int(os.getenv("STOCK_ULTIMUS_ALERT_MIN_REPAIR_ATTEMPTS", "2")))
    parser.add_argument("--repeat-alert-minutes", type=int, default=int(os.getenv("STOCK_ULTIMUS_ALERT_REPEAT_MINUTES", "1440")))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--no-send", action="store_true", help="Classify only; do not send even if channel flags are present.")
    parser.add_argument("--macos-notify", action="store_true")
    parser.add_argument("--pushover", action="store_true")
    parser.add_argument("--webhook-url", default=os.getenv("STOCK_ULTIMUS_NOTIFY_WEBHOOK_URL", ""))
    parser.add_argument("--email-summary", action="store_true")
    parser.add_argument("--to-email", default=os.getenv("STOCK_ULTIMUS_NOTIFY_TO_EMAIL", ""))
    parser.add_argument("--base-url", default=os.getenv("PUBLIC_BASE_URL", notify.DEFAULT_BASE_URL))
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


def signature(monitor: dict[str, Any]) -> str:
    findings = [item for item in monitor.get("findings") or [] if isinstance(item, dict)]
    level = str(monitor.get("alert_level") or "UNKNOWN").upper()
    all_codes = sorted(str(item.get("code")) for item in findings if item.get("code"))
    action_codes = sorted(
        str(item.get("code"))
        for item in findings
        if item.get("code") and str(item.get("severity") or "").upper() == "ACTION"
    )
    if level == "ACTION" and action_codes:
        return "|".join([level, "TECHNICAL_INCIDENT", ",".join(action_codes)])
    return "|".join([level, str(monitor.get("status")), ",".join(all_codes)])


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def run_auto_repair(args: argparse.Namespace) -> dict[str, Any]:
    """Run the existing safe refresh/publish path without exposing its output."""
    command = [
        sys.executable,
        str(ROOT / "scripts" / "daily_open_checklist.py"),
        "--refresh",
        "--publish",
        "--allow-stale-publish",
        "--soft-exit",
        "--bridge-timeout",
        "180",
        "--rsp-bridge-timeout",
        "90",
        "--capacity-timeout",
        "20",
        "--control-tower-timeout",
        "90",
        "--read-timeout",
        "30",
    ]
    attempted_at = now_utc().isoformat()
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=max(1, int(getattr(args, "repair_timeout", 420))),
        )
        return {
            "attempted": True,
            "attempted_at": attempted_at,
            "status": "COMPLETED" if completed.returncode == 0 else "FAILED",
            "returncode": completed.returncode,
            "command": "daily_open_checklist --refresh --publish",
            "output_captured_not_exposed": True,
            "execution_authorized": False,
            "not_order_instruction": True,
        }
    except subprocess.TimeoutExpired:
        return {
            "attempted": True,
            "attempted_at": attempted_at,
            "status": "TIMEOUT",
            "returncode": None,
            "command": "daily_open_checklist --refresh --publish",
            "output_captured_not_exposed": True,
            "execution_authorized": False,
            "not_order_instruction": True,
        }
    except Exception as exc:
        return {
            "attempted": True,
            "attempted_at": attempted_at,
            "status": "ERROR",
            "returncode": None,
            "error_type": type(exc).__name__,
            "command": "daily_open_checklist --refresh --publish",
            "output_captured_not_exposed": True,
            "execution_authorized": False,
            "not_order_instruction": True,
        }


def advance_incident_state(
    monitor: dict[str, Any],
    previous_state: dict[str, Any],
    *,
    repair_attempted: bool,
    min_repair_attempts: int,
    min_persistent_minutes: int,
    repeat_alert_minutes: int,
    current_time: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Track a technical incident and decide when human escalation adds value."""
    current_time = current_time or now_utc()
    now_text = current_time.isoformat()
    current_signature = signature(monitor)
    previous_incident = previous_state.get("active_incident")
    if not isinstance(previous_incident, dict):
        previous_incident = {}

    level = str(monitor.get("alert_level") or "UNKNOWN").upper()
    if level != "ACTION":
        recovered_signature = previous_incident.get("signature")
        next_state = {
            "state_version": "environment_incident_state_v2",
            "active_incident": None,
            "last_signature": current_signature,
            "last_checked_at": now_text,
        }
        if recovered_signature:
            next_state["last_recovery"] = {
                "signature": recovered_signature,
                "recovered_at": now_text,
                "notification_sent": False,
            }
        return next_state, {
            "active": False,
            "should_escalate": False,
            "reason": "RECOVERED_SILENTLY" if recovered_signature else "NO_ACTION_INCIDENT",
            "repair_attempts": 0,
            "persistent_minutes": 0.0,
        }

    current_action_codes = {
        str(item.get("code"))
        for item in monitor.get("findings") or []
        if isinstance(item, dict)
        and item.get("code")
        and str(item.get("severity") or "").upper() == "ACTION"
    }
    previous_codes = {
        str(code)
        for code in previous_incident.get("finding_codes") or []
        if code
    }
    same_incident = bool(
        previous_incident.get("signature") == current_signature
        or (
            level == "ACTION"
            and current_action_codes
            and current_action_codes.issubset(previous_codes)
        )
    )
    first_seen_at = previous_incident.get("first_seen_at") if same_incident else now_text
    first_seen = parse_timestamp(first_seen_at) or current_time
    persistent_minutes = max(0.0, (current_time - first_seen).total_seconds() / 60.0)
    repair_attempts = int(previous_incident.get("repair_attempts") or 0) if same_incident else 0
    if repair_attempted:
        repair_attempts += 1
    notified_at = previous_incident.get("notified_at") if same_incident else None
    notified_time = parse_timestamp(notified_at)
    minutes_since_notification = (
        max(0.0, (current_time - notified_time).total_seconds() / 60.0)
        if notified_time
        else None
    )
    enough_attempts = repair_attempts >= max(1, int(min_repair_attempts))
    persistent_long_enough = persistent_minutes >= max(0, int(min_persistent_minutes))
    repeat_window_open = notified_time is None or (
        minutes_since_notification is not None
        and minutes_since_notification >= max(1, int(repeat_alert_minutes))
    )
    should_escalate = bool(enough_attempts and persistent_long_enough and repeat_window_open)
    if not enough_attempts:
        reason = "AUTOREPAIR_ATTEMPTS_PENDING"
    elif not persistent_long_enough:
        reason = "PERSISTENCE_WINDOW_PENDING"
    elif not repeat_window_open:
        reason = "DUPLICATE_24H_SUPPRESSED"
    else:
        reason = "PERSISTENT_AFTER_AUTOREPAIR"

    incident = {
        "signature": current_signature,
        "first_seen_at": first_seen.isoformat(),
        "last_seen_at": now_text,
        "repair_attempts": repair_attempts,
        "persistent_minutes": round(persistent_minutes, 2),
        "notified_at": notified_at,
        "finding_codes": sorted(current_action_codes) if current_action_codes else sorted(
            str(item.get("code"))
            for item in monitor.get("findings") or []
            if isinstance(item, dict) and item.get("code")
        ),
    }
    next_state = {
        "state_version": "environment_incident_state_v2",
        "active_incident": incident,
        "last_signature": current_signature,
        "last_checked_at": now_text,
    }
    return next_state, {
        "active": True,
        "should_escalate": should_escalate,
        "reason": reason,
        "repair_attempts": repair_attempts,
        "persistent_minutes": round(persistent_minutes, 2),
        "minutes_since_notification": None if minutes_since_notification is None else round(minutes_since_notification, 2),
    }


def should_notify(monitor: dict[str, Any], args: argparse.Namespace, previous_state: dict[str, Any]) -> tuple[bool, str]:
    if getattr(args, "force", False):
        return True, "FORCED"
    level = str(monitor.get("alert_level") or "UNKNOWN").upper()
    if level == "ACTION":
        reason = "ENVIRONMENT_ACTION"
    elif level == "WATCH" and getattr(args, "notify_watch", False):
        reason = "ENVIRONMENT_WATCH"
    else:
        return False, "NO_NOTIFY_LEVEL"
    current_signature = signature(monitor)
    if previous_state.get("last_signature") == current_signature:
        return False, "DUPLICATE_SUPPRESSED"
    return True, reason


def notification_message(monitor: dict[str, Any]) -> str:
    level = str(monitor.get("alert_level") or "UNKNOWN").upper()
    findings = monitor.get("findings") if isinstance(monitor.get("findings"), list) else []
    codes = {str(item.get("code") or "") for item in findings if isinstance(item, dict)}
    if level != "ACTION" and codes.intersection({
        "TV_REAL_E2E_PENDING",
        "IBKR_OPTION_COVERAGE_PENDING",
        "PAPER_OUTCOME_LOOP_PENDING",
    }):
        message = "Validación operativa en progreso: esperando eventos reales de TradingView y acumulando una muestra de resultados."
        if "IBKR_OPTION_COVERAGE_PENDING" in codes:
            message += " IBKR conectado; cobertura de opciones pendiente de completar."
        elif "IBKR_NOT_REVIEWABLE" in codes:
            message += " IBKR requiere completar la revisión de opciones."
        return message
    message = "{level} {status}: {next_action}".format(
        level=monitor.get("alert_level"),
        status=monitor.get("status"),
        next_action=monitor.get("next_required_action"),
    )
    if findings:
        message += " | " + "; ".join(str(item.get("code")) for item in findings[:4] if isinstance(item, dict))
    return message


def notification_report(
    monitor: dict[str, Any],
    notify_reason: str,
    should_send: bool,
    incident: dict[str, Any] | None = None,
) -> dict[str, Any]:
    findings = monitor.get("findings") if isinstance(monitor.get("findings"), list) else []
    level = str(monitor.get("alert_level") or "UNKNOWN").upper()
    is_action = bool(should_send and level == "ACTION")
    display_status = "VALIDATION_IN_PROGRESS" if level == "WATCH" else monitor.get("status")
    message = notification_message(monitor)
    incident = incident if isinstance(incident, dict) else {}
    if level == "ACTION" and incident.get("repair_attempts"):
        message += " | Autocorrección: {attempts} intentos; persiste {minutes} min.".format(
            attempts=incident.get("repair_attempts"),
            minutes=incident.get("persistent_minutes"),
        )
    return {
        "engine": "STOCK_ULTIMUS_ENVIRONMENT_ALERTS",
        "notify_version": "environment_alerts_v2",
        "checked_at": monitor.get("generated_at"),
        "status": display_status,
        "operator_status": display_status,
        "operator_readiness": monitor.get("alert_level"),
        "custom_message": message[:220],
        "classification": {
            "should_notify": should_send,
            "notify_reason": notify_reason,
            "actionable_count": 1 if is_action else 0,
            "informational_count": 1 if should_send and not is_action else 0,
            "active_alert_count": len(findings),
            "notification_priority": "high" if is_action else "normal",
            "actionable_alerts": [
                {
                    "ticker": "ENV",
                    "strategy": "OPERATIONS",
                    "severity": monitor.get("alert_level"),
                    "state": monitor.get("status"),
                    "main_blocker": notify_reason,
                    "manual_review_ready": False,
                    "execution_authorized": False,
                    "not_order_instruction": True,
                }
            ] if is_action else [],
        },
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def post_email_summary(base_url: str, token: str, timeout: int, to_email: str, source: str) -> dict[str, Any]:
    body = json.dumps({"to_email": to_email, "force": True, "source": source}).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/v32_operator_daily_summary_email",
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Stock-Ultimus-Read-Token": token,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            payload = json.loads(raw) if raw else {}
            return {"sent": bool(payload.get("email_sent")), "provider": "resend_backend", "status_code": response.status}
    except urllib.error.HTTPError as exc:
        return {"sent": False, "provider": "resend_backend", "status_code": exc.code}
    except urllib.error.URLError as exc:
        return {"sent": False, "provider": "resend_backend", "error": str(exc)}


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    initial_monitor = operator_readiness.build_post_open_monitor(
        args.runtime_dir,
        market_closed_ok=args.market_closed_ok,
    )
    state_path = Path(args.state_file)
    previous_state = read_json(state_path, {})
    previous_state = previous_state if isinstance(previous_state, dict) else {}
    remediation = {
        "attempted": False,
        "status": "NOT_REQUIRED",
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    initial_level = str(initial_monitor.get("alert_level") or "UNKNOWN").upper()
    if initial_level == "ACTION" and getattr(args, "auto_repair", False):
        remediation = run_auto_repair(args)
        monitor = operator_readiness.build_post_open_monitor(
            args.runtime_dir,
            market_closed_ok=args.market_closed_ok,
        )
    else:
        monitor = initial_monitor

    next_state, incident = advance_incident_state(
        monitor,
        previous_state,
        repair_attempted=bool(remediation.get("attempted")),
        min_repair_attempts=int(getattr(args, "min_repair_attempts", 2)),
        min_persistent_minutes=int(getattr(args, "min_persistent_minutes", 15)),
        repeat_alert_minutes=int(getattr(args, "repeat_alert_minutes", 1440)),
    )
    send, reason = should_notify(monitor, args, previous_state)
    if str(monitor.get("alert_level") or "UNKNOWN").upper() == "ACTION" and not getattr(args, "force", False):
        send = bool(incident.get("should_escalate"))
        reason = str(incident.get("reason") or "AUTOREPAIR_PENDING")
    send = bool(send and not args.no_send)
    report_for_channel = notification_report(monitor, reason, send, incident)
    results = []
    if send and args.macos_notify:
        results.append(notify.send_macos_notification(report_for_channel))
    if send and args.pushover:
        results.append(
            notify.send_pushover_notification(
                report_for_channel,
                notify.first_keychain_password(notify.PUSHOVER_USER_KEYCHAIN_SERVICES),
                notify.first_keychain_password(notify.PUSHOVER_API_TOKEN_KEYCHAIN_SERVICES),
                args.timeout,
            )
        )
    if send and args.webhook_url:
        results.append(notify.send_webhook_notification(report_for_channel, args.webhook_url, args.timeout))
    if send and args.email_summary:
        token = notify.keychain_password(notify.READ_KEYCHAIN_SERVICES[0]) or os.getenv("READ_ACCESS_TOKEN", "")
        results.append(post_email_summary(args.base_url, token, args.timeout, args.to_email, "environment_alerts"))
    sent = any(result.get("sent") for result in results)
    if sent and isinstance(next_state.get("active_incident"), dict):
        next_state["active_incident"]["notified_at"] = now_utc().isoformat()
        next_state["last_notify_reason"] = reason
    payload = {
        "engine": "STOCK_ULTIMUS_ENVIRONMENT_ALERTS",
        "alert_version": "environment_alerts_v2",
        "checked_at": monitor.get("generated_at"),
        "status": "OK",
        "should_notify": bool(send),
        "notify_reason": reason,
        "notification_requested": bool(args.macos_notify or args.pushover or args.webhook_url or args.email_summary),
        "notification_sent": bool(sent),
        "notification_results": results,
        "initial_monitor": initial_monitor,
        "monitor": monitor,
        "remediation": remediation,
        "incident": incident,
        "state_signature": signature(monitor),
        "secrets_printed": False,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    if not args.no_write:
        write_json(state_path, next_state)
    return payload


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_report(args)
    if not args.no_write:
        write_json(Path(args.json_out), report)
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
