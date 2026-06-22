#!/usr/bin/env python3
"""Record or inspect V31 manual review decisions in production.

This tool is intentionally small and conservative:
- it never places orders,
- it never prints read tokens,
- it reads READ_ACCESS_TOKEN from the environment or macOS Keychain,
- and it sends only protected requests to the deployed Stock Ultimus service.
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
from typing import Any


DEFAULT_BASE_URL = "https://trading-engine-p097.onrender.com"
DEFAULT_READ_TOKEN_SERVICE = "stock-ultimus-read-access"
ALLOWED_STATUSES = (
    "RECEIVED",
    "REVIEWING",
    "APPROVED_FOR_MANUAL_TRADE",
    "REJECTED",
    "WATCHLIST",
    "EXPIRED",
)


def keychain_secret(service: str, account: str | None = None) -> str:
    cmd = ["security", "find-generic-password"]
    if account:
        cmd.extend(["-a", account])
    cmd.extend(["-s", service, "-w"])
    return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()


def read_token(args: argparse.Namespace) -> str:
    token = args.token or os.getenv("READ_ACCESS_TOKEN", "")
    if token:
        return token
    return keychain_secret(args.read_token_service, args.keychain_account or None)


def review_payload(args: argparse.Namespace) -> dict[str, Any]:
    ticker = str(args.ticker or "").upper().strip()
    status = str(args.status or "").upper().strip()
    reason = str(args.reason or "").strip()
    return {
        "ticker": ticker,
        "status": status,
        "reason": reason,
        "actor": args.actor,
        "source": "tools/record_v31_manual_review.py",
        "client_recorded_at": datetime.now(timezone.utc).isoformat(),
        "manual_trade_review_only": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def request_json(
    url: str,
    *,
    token: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: int = 20,
) -> tuple[int, dict[str, Any]]:
    body = None
    headers = {"X-Stock-Ultimus-Read-Token": token}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"raw": raw[:500]}
        return exc.code, parsed


def manual_reviews_url(base_url: str, limit: int) -> str:
    query = urllib.parse.urlencode({"limit": limit})
    return f"{base_url.rstrip('/')}/v31_manual_reviews?{query}"


def manual_review_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/v31_manual_review"


def run(args: argparse.Namespace) -> dict[str, Any]:
    base_url = args.base_url.rstrip("/")

    if args.list:
        if args.dry_run:
            return {
                "engine": "V31_MANUAL_REVIEW_CLI",
                "dry_run": True,
                "method": "GET",
                "url": manual_reviews_url(base_url, args.limit),
                "token_read": False,
                "request_sent": False,
                "not_order_instruction": True,
                "execution_authorized": False,
            }
        token = read_token(args)
        status_code, response = request_json(
            manual_reviews_url(base_url, args.limit),
            token=token,
            timeout=args.timeout,
        )
        return {
            "engine": "V31_MANUAL_REVIEW_CLI",
            "operation": "list",
            "status_code": status_code,
            "ok": status_code == 200,
            "response": response,
            "token_printed": False,
            "not_order_instruction": True,
            "execution_authorized": False,
        }

    payload = review_payload(args)
    if not payload["ticker"]:
        raise ValueError("ticker is required unless --list is used")

    if args.dry_run:
        return {
            "engine": "V31_MANUAL_REVIEW_CLI",
            "dry_run": True,
            "method": "POST",
            "url": manual_review_url(base_url),
            "payload": payload,
            "token_read": False,
            "request_sent": False,
            "not_order_instruction": True,
            "execution_authorized": False,
        }

    token = read_token(args)
    status_code, response = request_json(
        manual_review_url(base_url),
        token=token,
        method="POST",
        payload=payload,
        timeout=args.timeout,
    )
    return {
        "engine": "V31_MANUAL_REVIEW_CLI",
        "operation": "record",
        "status_code": status_code,
        "ok": status_code == 200,
        "response": response,
        "token_printed": False,
        "not_order_instruction": True,
        "execution_authorized": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record a protected V31 manual review decision.")
    parser.add_argument("--base-url", default=os.getenv("PUBLIC_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--token", default=os.getenv("READ_ACCESS_TOKEN", ""))
    parser.add_argument("--read-token-service", default=DEFAULT_READ_TOKEN_SERVICE)
    parser.add_argument("--keychain-account", default="")
    parser.add_argument("--ticker", default="")
    parser.add_argument("--status", choices=ALLOWED_STATUSES, default="REVIEWING")
    parser.add_argument("--reason", default="")
    parser.add_argument("--actor", default=os.getenv("USER", "user"))
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--list", action="store_true", help="List recent manual review records instead of posting one.")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = run(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except subprocess.CalledProcessError:
        print("Could not read READ_ACCESS_TOKEN from Keychain. Pass --token or set READ_ACCESS_TOKEN.", file=sys.stderr)
        return 2

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok", True) or result.get("dry_run") else 1


if __name__ == "__main__":
    raise SystemExit(main())
