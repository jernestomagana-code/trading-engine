#!/usr/bin/env python3
"""Validate local environment credentials and production read-auth.

This check never prints secrets. It verifies whether the local environment has
the tokens/channels needed for the interactive Stock Ultimus loop.
"""

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
DEFAULT_BASE_URL = "https://trading-engine-p097.onrender.com"
DEFAULT_OUT = ROOT / "runtime" / "environment_auth_check_latest.json"
READ_KEYCHAIN_SERVICES = ("stock-ultimus-read-access-token", "stock-ultimus-read-access")
INGEST_KEYCHAIN_SERVICES = ("stock-ultimus-snapshot-ingest",)
PUSHOVER_USER_KEYCHAIN_SERVICES = ("stock-ultimus-pushover-user-key",)
PUSHOVER_API_TOKEN_KEYCHAIN_SERVICES = ("stock-ultimus-pushover-api-token",)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate Stock Ultimus environment auth.")
    parser.add_argument("--base-url", default=os.getenv("PUBLIC_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("STOCK_ULTIMUS_READ_TIMEOUT", "30")))
    parser.add_argument("--json-out", default=str(DEFAULT_OUT))
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--json-only", action="store_true")
    parser.add_argument("--local-only", action="store_true", help="Skip production HTTP checks.")
    parser.add_argument("--no-keychain", action="store_true", help="Use environment variables only.")
    return parser


def keychain_password(service: str, *, disabled: bool = False) -> str | None:
    if disabled:
        return None
    user = os.getenv("USER") or ""
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


def secret_status(env_names: list[str], keychain_services: tuple[str, ...], *, no_keychain: bool) -> dict[str, Any]:
    for name in env_names:
        if os.getenv(name):
            return {"ok": True, "source": "env", "env_name": name}
    for service in keychain_services:
        if keychain_password(service, disabled=no_keychain):
            return {"ok": True, "source": "keychain", "service": service}
    return {"ok": False, "source": None}


def secret_value(env_names: list[str], keychain_services: tuple[str, ...], *, no_keychain: bool) -> str:
    for name in env_names:
        value = os.getenv(name)
        if value:
            return value
    for service in keychain_services:
        value = keychain_password(service, disabled=no_keychain)
        if value:
            return value
    return ""


def request_json(url: str, token: str | None, timeout: int) -> tuple[int, dict[str, Any]]:
    headers = {"Accept": "application/json"}
    if token:
        headers["X-Stock-Ultimus-Read-Token"] = token
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
        except Exception:
            payload = {"raw": body[:500]}
        return exc.code, payload
    except urllib.error.URLError as exc:
        return 0, {"detail": str(exc)}


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    base = args.base_url.rstrip("/")
    read_status = secret_status(
        ["READ_ACCESS_TOKEN", "STOCK_ULTIMUS_READ_TOKEN", "STOCK_ULTIMUS_READ_ACCESS_TOKEN"],
        READ_KEYCHAIN_SERVICES,
        no_keychain=args.no_keychain,
    )
    ingest_status = secret_status(
        ["TRADING_ENGINE_INGEST_TOKEN", "SNAPSHOT_INGEST_TOKEN"],
        INGEST_KEYCHAIN_SERVICES,
        no_keychain=args.no_keychain,
    )
    pushover_user_status = secret_status(
        ["PUSHOVER_USER_KEY"],
        PUSHOVER_USER_KEYCHAIN_SERVICES,
        no_keychain=args.no_keychain,
    )
    pushover_api_status = secret_status(
        ["PUSHOVER_API_TOKEN"],
        PUSHOVER_API_TOKEN_KEYCHAIN_SERVICES,
        no_keychain=args.no_keychain,
    )
    checks: dict[str, Any] = {
        "read_token": read_status,
        "ingest_token": ingest_status,
        "pushover_user_key": pushover_user_status,
        "pushover_api_token": pushover_api_status,
        "pushover_channel_configured": {
            "ok": pushover_user_status["ok"] and pushover_api_status["ok"],
        },
    }
    if args.local_only:
        checks["production_read_auth"] = {"ok": None, "skipped": True}
        checks["gpt_operator_today"] = {"ok": None, "skipped": True}
    else:
        read_token = secret_value(
            ["READ_ACCESS_TOKEN", "STOCK_ULTIMUS_READ_TOKEN", "STOCK_ULTIMUS_READ_ACCESS_TOKEN"],
            READ_KEYCHAIN_SERVICES,
            no_keychain=args.no_keychain,
        )
        denied_status, _ = request_json(f"{base}/v31_system_status", None, args.timeout)
        allowed_status, allowed = request_json(f"{base}/v31_system_status", read_token or None, args.timeout)
        checks["production_read_auth"] = {
            "ok": bool(read_token) and denied_status in {401, 403, 503} and allowed_status == 200 and allowed.get("not_order_instruction") is True,
            "unauthorized_status": denied_status,
            "authorized_status": allowed_status,
        }
        operator_status, operator = request_json(f"{base}/gpt_v32_operator_today?limit=3", read_token or None, args.timeout)
        checks["gpt_operator_today"] = {
            "ok": operator_status == 200 and operator.get("not_order_instruction") is True,
            "status_code": operator_status,
            "operator_status": operator.get("status"),
        }
    required_ok = checks["read_token"]["ok"] and checks["ingest_token"]["ok"]
    production_ok = all(
        check.get("ok") is not False
        for name, check in checks.items()
        if name in {"production_read_auth", "gpt_operator_today"}
    )
    return {
        "engine": "STOCK_ULTIMUS_ENVIRONMENT_AUTH_CHECK",
        "check_version": "environment_auth_check_v1",
        "generated_at": now_iso(),
        "base_url": base,
        "status": "OK" if required_ok and production_ok else "ACTION_REQUIRED",
        "ok": bool(required_ok and production_ok),
        "checks": checks,
        "next_required_action": (
            "Environment auth is ready."
            if required_ok and production_ok
            else "Configure missing tokens/channels or fix production read-auth before relying on automation."
        ),
        "secrets_printed": False,
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def print_human(report: dict[str, Any]) -> None:
    print("Stock Ultimus Environment Auth Check")
    print(f"Estado: {report.get('status')} | ok={report.get('ok')}")
    print(f"Siguiente accion: {report.get('next_required_action')}")
    for name, check in (report.get("checks") or {}).items():
        marker = "SKIP" if check.get("skipped") else ("OK" if check.get("ok") else "FAIL")
        detail = check.get("source") or check.get("status_code") or check.get("authorized_status") or ""
        print(f"- {name}: {marker} {detail}")
    print("Guardrail: secrets_printed=false; execution_authorized=false; not_order_instruction=true.")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_report(args)
    if not args.no_write:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    if args.json_only:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        print_human(report)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
