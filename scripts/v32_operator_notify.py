#!/usr/bin/env python3
"""Notify only on actionable V32 operator alerts.

This script reads /gpt_v32_operator_today, classifies the alert set, writes a
redacted notification report, and can optionally trigger a macOS notification.
It intentionally suppresses WAIT_MARKET-only noise.

It never places orders, never authorizes execution, and never prints tokens.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "https://trading-engine-p097.onrender.com"
DEFAULT_OUT = ROOT / "runtime" / "v32_operator_notify_latest.json"
READ_KEYCHAIN_SERVICES = ("stock-ultimus-read-access-token", "stock-ultimus-read-access")
PUSHOVER_USER_KEYCHAIN_SERVICES = ("stock-ultimus-pushover-user-key",)
PUSHOVER_API_TOKEN_KEYCHAIN_SERVICES = ("stock-ultimus-pushover-api-token",)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Notify on actionable V32 operator alerts.")
    parser.add_argument("--base-url", default=os.getenv("PUBLIC_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--token", default=os.getenv("READ_ACCESS_TOKEN") or os.getenv("STOCK_ULTIMUS_READ_TOKEN") or "")
    parser.add_argument("--timeout", type=int, default=int(os.getenv("STOCK_ULTIMUS_READ_TIMEOUT", "30")))
    parser.add_argument("--limit", type=int, default=int(os.getenv("STOCK_ULTIMUS_OPERATOR_ALERT_LIMIT", "12")))
    parser.add_argument("--json-out", default=os.getenv("STOCK_ULTIMUS_V32_NOTIFY_OUT", str(DEFAULT_OUT)))
    parser.add_argument("--macos-notify", action="store_true", help="Show a local macOS notification when actionable.")
    parser.add_argument("--webhook-url", default=os.getenv("STOCK_ULTIMUS_NOTIFY_WEBHOOK_URL", ""), help="Optional generic webhook URL for actionable notifications.")
    parser.add_argument("--pushover", action="store_true", help="Send a mobile push through Pushover when actionable.")
    parser.add_argument("--pushover-user-key", default=os.getenv("PUSHOVER_USER_KEY", ""), help="Pushover user/group key.")
    parser.add_argument("--pushover-api-token", default=os.getenv("PUSHOVER_API_TOKEN", ""), help="Pushover application API token.")
    parser.add_argument("--email-summary", action="store_true", help="Ask the protected backend to send the V32 daily summary email when actionable.")
    parser.add_argument("--to-email", default=os.getenv("STOCK_ULTIMUS_NOTIFY_TO_EMAIL", ""), help="Optional email recipient override for --email-summary.")
    parser.add_argument("--force", action="store_true", help="Notify even when there are no actionable alerts.")
    parser.add_argument("--no-write", action="store_true", help="Do not write the latest JSON report.")
    return parser.parse_args()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def keychain_password(service: str) -> str | None:
    user = os.getenv("USER") or ""
    if not user:
        try:
            user = subprocess.check_output(["id", "-un"], text=True).strip()
        except Exception:
            user = ""
    if not user:
        return None
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-a", user, "-s", service, "-w"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def read_token(args: argparse.Namespace) -> str | None:
    if args.token:
        return args.token
    for service in READ_KEYCHAIN_SERVICES:
        token = keychain_password(service)
        if token:
            return token
    return None


def first_keychain_password(services: tuple[str, ...]) -> str:
    for service in services:
        value = keychain_password(service)
        if value:
            return value
    return ""


def pushover_user_key(args: argparse.Namespace) -> str:
    return args.pushover_user_key or first_keychain_password(PUSHOVER_USER_KEYCHAIN_SERVICES)


def pushover_api_token(args: argparse.Namespace) -> str:
    return args.pushover_api_token or first_keychain_password(PUSHOVER_API_TOKEN_KEYCHAIN_SERVICES)


def request_operator(base_url: str, token: str, timeout: int, limit: int) -> tuple[int, dict[str, Any]]:
    url = f"{base_url.rstrip('/')}/gpt_v32_operator_today?limit={max(1, limit)}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "X-Stock-Ultimus-Read-Token": token,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
        except Exception:
            payload = {"raw": body[:500]}
        return exc.code, payload
    except urllib.error.URLError as exc:
        return 0, {"detail": str(exc)}


def post_json(base_url: str, path: str, token: str, payload: dict[str, Any], timeout: int) -> tuple[int, dict[str, Any]]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
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
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw[:500]}
        return exc.code, payload
    except urllib.error.URLError as exc:
        return 0, {"detail": str(exc)}


def classify(operator: dict[str, Any], force: bool = False) -> dict[str, Any]:
    alerts = operator.get("active_alerts") if isinstance(operator.get("active_alerts"), list) else []
    actionable = []
    wait_market = []
    no_data = []
    for alert in alerts:
        if not isinstance(alert, dict):
            continue
        severity = str(alert.get("severity") or "")
        state = str(alert.get("state") or "")
        manual_ready = alert.get("manual_review_ready") is True
        compact = {
            "alert_id": alert.get("alert_id"),
            "ticker": alert.get("ticker"),
            "strategy": alert.get("strategy"),
            "severity": severity,
            "state": state,
            "main_blocker": alert.get("main_blocker"),
            "manual_review_ready": manual_ready,
            "operator_status": alert.get("operator_status"),
            "execution_authorized": False,
            "not_order_instruction": True,
        }
        if severity in {"ACTION", "RISK"} or manual_ready:
            actionable.append(compact)
        elif state == "WAIT_MARKET":
            wait_market.append(compact)
        elif state == "NO_DATA":
            no_data.append(compact)

    should_notify = force or bool(actionable)
    if actionable:
        reason = "ACTIONABLE_OPERATOR_ALERT"
    elif force:
        reason = "FORCED"
    elif no_data:
        reason = "NO_DATA_SUPPRESSED"
    elif wait_market:
        reason = "WAIT_MARKET_SUPPRESSED"
    else:
        reason = "NO_ACTIONABLE_ALERT"

    return {
        "should_notify": should_notify,
        "notify_reason": reason,
        "actionable_count": len(actionable),
        "wait_market_count": len(wait_market),
        "no_data_count": len(no_data),
        "active_alert_count": len(alerts),
        "actionable_alerts": actionable,
    }


def notification_text(report: dict[str, Any]) -> tuple[str, str]:
    status = report.get("operator_status") or "UNKNOWN"
    classification = report.get("classification") or {}
    custom_message = str(report.get("custom_message") or "").strip()
    actionable = classification.get("actionable_alerts") or []
    title = "Stock Ultimus V32"
    if custom_message:
        body = custom_message
    elif actionable:
        tickers = ", ".join(str(item.get("ticker")) for item in actionable[:5] if item.get("ticker"))
        body = f"{classification.get('actionable_count')} alerta(s) accionables: {tickers}. Estado {status}."
    else:
        body = f"Sin alertas accionables. Estado {status}; razon {classification.get('notify_reason')}."
    return title, body[:220]


def send_macos_notification(report: dict[str, Any]) -> dict[str, Any]:
    title, body = notification_text(report)
    script = f'display notification {json.dumps(body)} with title {json.dumps(title)}'
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {"sent": False, "provider": "macos_notification_center", "error": str(exc)}
    return {
        "sent": result.returncode == 0,
        "provider": "macos_notification_center",
        "returncode": result.returncode,
        "stderr_tail": (result.stderr or "")[-500:],
    }


def send_webhook_notification(report: dict[str, Any], webhook_url: str, timeout: int) -> dict[str, Any]:
    title, body = notification_text(report)
    payload = {
        "source": "stock_ultimus_v32_operator_notify",
        "title": title,
        "body": body,
        "operator_status": report.get("operator_status"),
        "operator_readiness": report.get("operator_readiness"),
        "classification": report.get("classification") or {},
        "execution_authorized": False,
        "not_order_instruction": True,
    }
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
        return {"sent": False, "provider": "webhook", "status_code": exc.code, "error": exc.read().decode("utf-8", errors="replace")[:500]}
    except urllib.error.URLError as exc:
        return {"sent": False, "provider": "webhook", "error": str(exc)}


def send_pushover_notification(report: dict[str, Any], user_key: str, api_token: str, timeout: int) -> dict[str, Any]:
    if not user_key or not api_token:
        missing = []
        if not user_key:
            missing.append("PUSHOVER_USER_KEY")
        if not api_token:
            missing.append("PUSHOVER_API_TOKEN")
        return {"sent": False, "provider": "pushover", "reason": "PUSHOVER_CONFIG_MISSING", "missing": missing}

    title, body = notification_text(report)
    payload = urllib.parse.urlencode({
        "token": api_token,
        "user": user_key,
        "title": title,
        "message": body,
        "priority": "1" if (report.get("classification") or {}).get("actionable_count") else "0",
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.pushover.net/1/messages.json",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            result = json.loads(raw) if raw else {}
            return {
                "sent": 200 <= response.status < 300 and result.get("status") == 1,
                "provider": "pushover",
                "status_code": response.status,
                "response": result,
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            result = json.loads(raw)
        except Exception:
            result = {"raw": raw[:500]}
        return {"sent": False, "provider": "pushover", "status_code": exc.code, "response": result}
    except urllib.error.URLError as exc:
        return {"sent": False, "provider": "pushover", "error": str(exc)}


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    token = read_token(args)
    if not token:
        return {
            "engine": "V32_OPERATOR_NOTIFY",
            "notify_version": "v32_operator_notify_v1",
            "checked_at": now_iso(),
            "status": "ACTION_REQUIRED",
            "error": "MISSING_READ_TOKEN",
            "should_notify": False,
            "notification_sent": False,
            "secrets_printed": False,
            "execution_authorized": False,
            "not_order_instruction": True,
        }

    status_code, operator = request_operator(args.base_url, token, args.timeout, args.limit)
    classification = classify(operator if status_code == 200 else {}, force=args.force)
    report = {
        "engine": "V32_OPERATOR_NOTIFY",
        "notify_version": "v32_operator_notify_v1",
        "checked_at": now_iso(),
        "base_url": args.base_url.rstrip("/"),
        "http_status": status_code,
        "status": "OK" if status_code == 200 else "ACTION_REQUIRED",
        "operator_status": operator.get("status") if status_code == 200 else None,
        "operator_readiness": (operator.get("command_center") or {}).get("operational_readiness") if status_code == 200 else None,
        "classification": classification,
        "should_notify": bool(classification.get("should_notify")),
        "notification_requested": bool(args.macos_notify or args.webhook_url or args.pushover or args.email_summary),
        "notification_sent": False,
        "notification_channel": "multi" if (args.macos_notify or args.webhook_url or args.pushover or args.email_summary) else "json_only",
        "notification_results": [],
        "secrets_printed": False,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    if args.macos_notify and report["should_notify"]:
        result = send_macos_notification(report)
        report["notification_sent"] = bool(result.get("sent"))
        report["notification_results"].append(result)
    if args.webhook_url and report["should_notify"]:
        result = send_webhook_notification(report, args.webhook_url, args.timeout)
        report["notification_results"].append(result)
        report["notification_sent"] = bool(report["notification_sent"] or result.get("sent"))
    if args.pushover and report["should_notify"]:
        result = send_pushover_notification(report, pushover_user_key(args), pushover_api_token(args), args.timeout)
        report["notification_results"].append(result)
        report["notification_sent"] = bool(report["notification_sent"] or result.get("sent"))
    if args.email_summary and report["should_notify"]:
        status, result = post_json(
            args.base_url,
            "/v32_operator_daily_summary_email",
            token,
            {"to_email": args.to_email, "force": args.force, "source": "v32_operator_notify"},
            args.timeout,
        )
        email_result = {"sent": bool(result.get("email_sent")), "provider": "resend_backend", "status_code": status, "result": result}
        report["notification_results"].append(email_result)
        report["notification_sent"] = bool(report["notification_sent"] or email_result.get("sent"))
    return report


def main() -> int:
    args = parse_args()
    report = build_report(args)
    if not args.no_write:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
