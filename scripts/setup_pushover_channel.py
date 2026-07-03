#!/usr/bin/env python3
"""Check and optionally smoke-test the Stock Ultimus Pushover channel.

The script never prints Pushover secrets. It reads credentials from environment
variables first, then from macOS Keychain services used by the notifier:

- stock-ultimus-pushover-user-key
- stock-ultimus-pushover-api-token
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import v32_operator_notify as notify  # noqa: E402


DEFAULT_OUT = ROOT / "runtime" / "pushover_channel_status_latest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the Stock Ultimus Pushover push channel.")
    parser.add_argument("--json-out", default=os.getenv("STOCK_ULTIMUS_PUSHOVER_STATUS_OUT", str(DEFAULT_OUT)))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("STOCK_ULTIMUS_PUSHOVER_TIMEOUT", "20")))
    parser.add_argument("--send-test", action="store_true", help="Send a safe test push if credentials are configured.")
    parser.add_argument("--message", default="Stock Ultimus Pushover channel test. No trading action authorized.")
    parser.add_argument("--no-write", action="store_true")
    return parser.parse_args()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def keychain_has_value(service: str) -> bool:
    user = os.getenv("USER") or ""
    if not user:
        try:
            user = subprocess.check_output(["id", "-un"], text=True).strip()
        except Exception:
            user = ""
    if not user:
        return False
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-a", user, "-s", service, "-w"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def source_status(env_name: str, services: tuple[str, ...]) -> dict[str, Any]:
    env_present = bool(os.getenv(env_name))
    service_presence = {service: keychain_has_value(service) for service in services}
    return {
        "env": env_name,
        "env_present": env_present,
        "keychain_services": service_presence,
        "configured": env_present or any(service_presence.values()),
    }


def fake_report(message: str) -> dict[str, Any]:
    return {
        "engine": "PUSHOVER_CHANNEL_PREFLIGHT",
        "operator_status": "CHANNEL_TEST",
        "operator_readiness": "CONFIG_TEST",
        "classification": {
            "should_notify": True,
            "notify_reason": "PUSHOVER_CHANNEL_TEST",
            "actionable_count": 0,
            "actionable_alerts": [],
        },
        "custom_message": message,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def build_status(args: argparse.Namespace) -> dict[str, Any]:
    user_key_status = source_status("PUSHOVER_USER_KEY", notify.PUSHOVER_USER_KEYCHAIN_SERVICES)
    api_token_status = source_status("PUSHOVER_API_TOKEN", notify.PUSHOVER_API_TOKEN_KEYCHAIN_SERVICES)
    ready = bool(user_key_status["configured"] and api_token_status["configured"])
    status: dict[str, Any] = {
        "engine": "PUSHOVER_CHANNEL_PREFLIGHT",
        "checked_at": now_iso(),
        "status": "OK" if ready else "ACTION_REQUIRED",
        "ready": ready,
        "user_key": user_key_status,
        "api_token": api_token_status,
        "send_test_requested": bool(args.send_test),
        "test_result": None,
        "secrets_printed": False,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    if not ready:
        missing = []
        if not user_key_status["configured"]:
            missing.append("PUSHOVER_USER_KEY or stock-ultimus-pushover-user-key")
        if not api_token_status["configured"]:
            missing.append("PUSHOVER_API_TOKEN or stock-ultimus-pushover-api-token")
        status["missing"] = missing
        return status
    if args.send_test:
        report = fake_report(args.message)
        result = notify.send_pushover_notification(
            report,
            os.getenv("PUSHOVER_USER_KEY") or notify.first_keychain_password(notify.PUSHOVER_USER_KEYCHAIN_SERVICES),
            os.getenv("PUSHOVER_API_TOKEN") or notify.first_keychain_password(notify.PUSHOVER_API_TOKEN_KEYCHAIN_SERVICES),
            args.timeout,
        )
        status["test_result"] = result
        status["status"] = "OK" if result.get("sent") else "ACTION_REQUIRED"
    return status


def main() -> int:
    args = parse_args()
    status = build_status(args)
    if not args.no_write:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status.get("status") == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
