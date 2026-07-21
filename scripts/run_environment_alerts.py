#!/usr/bin/env python3
"""Notify on environment-level Stock Ultimus readiness issues."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
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
    finding_codes = ",".join(sorted(str(item.get("code")) for item in monitor.get("findings") or [] if isinstance(item, dict)))
    return "|".join([str(monitor.get("alert_level")), str(monitor.get("status")), finding_codes])


def should_notify(monitor: dict[str, Any], args: argparse.Namespace, previous_state: dict[str, Any]) -> tuple[bool, str]:
    if args.force:
        return True, "FORCED"
    level = str(monitor.get("alert_level") or "UNKNOWN").upper()
    if level == "ACTION":
        reason = "ENVIRONMENT_ACTION"
    elif level == "WATCH" and args.notify_watch:
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


def notification_report(monitor: dict[str, Any], notify_reason: str, should_send: bool) -> dict[str, Any]:
    findings = monitor.get("findings") if isinstance(monitor.get("findings"), list) else []
    level = str(monitor.get("alert_level") or "UNKNOWN").upper()
    is_action = bool(should_send and level == "ACTION")
    display_status = "VALIDATION_IN_PROGRESS" if level == "WATCH" else monitor.get("status")
    message = notification_message(monitor)
    return {
        "engine": "STOCK_ULTIMUS_ENVIRONMENT_ALERTS",
        "notify_version": "environment_alerts_v1",
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
    monitor = operator_readiness.build_post_open_monitor(
        args.runtime_dir,
        market_closed_ok=args.market_closed_ok,
    )
    state_path = Path(args.state_file)
    previous_state = read_json(state_path, {})
    send, reason = should_notify(monitor, args, previous_state if isinstance(previous_state, dict) else {})
    send = bool(send and not args.no_send)
    report_for_channel = notification_report(monitor, reason, send)
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
    payload = {
        "engine": "STOCK_ULTIMUS_ENVIRONMENT_ALERTS",
        "alert_version": "environment_alerts_v1",
        "checked_at": monitor.get("generated_at"),
        "status": "OK",
        "should_notify": bool(send),
        "notify_reason": reason,
        "notification_requested": bool(args.macos_notify or args.pushover or args.webhook_url or args.email_summary),
        "notification_sent": bool(sent),
        "notification_results": results,
        "monitor": monitor,
        "state_signature": signature(monitor),
        "secrets_printed": False,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    if send and not args.no_write:
        write_json(state_path, {"last_signature": payload["state_signature"], "last_notify_reason": reason, "last_checked_at": payload["checked_at"]})
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
