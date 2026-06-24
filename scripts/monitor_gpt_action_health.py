#!/usr/bin/env python3
"""Monitor the Super Engine Bolsa GPT Action read surface.

This script checks the deployed read-auth behavior and the GPT daily-ranking
contract without printing secrets. It is meant for cron/launchd or a quick
operator health check after token/schema changes.
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
DEFAULT_PUBLIC_BASE_URL = "https://trading-engine-p097.onrender.com"
READ_KEYCHAIN_SERVICE = "stock-ultimus-read-access-token"
DEFAULT_HEALTH_OUT = ROOT / "runtime" / "gpt_action_health_latest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check Stock Ultimus GPT Action health.")
    parser.add_argument("--base-url", default=os.getenv("PUBLIC_BASE_URL", DEFAULT_PUBLIC_BASE_URL))
    parser.add_argument("--token", default=os.getenv("READ_ACCESS_TOKEN") or os.getenv("STOCK_ULTIMUS_READ_TOKEN") or "")
    parser.add_argument("--timeout", type=int, default=int(os.getenv("STOCK_ULTIMUS_READ_TIMEOUT", "30")))
    parser.add_argument("--health-out", default=os.getenv("STOCK_ULTIMUS_GPT_ACTION_HEALTH_OUT", str(DEFAULT_HEALTH_OUT)))
    parser.add_argument("--no-write", action="store_true", help="Do not write the latest health JSON file.")
    return parser.parse_args()


def keychain_password(service: str) -> str | None:
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


def request_json(url: str, token: str | None, timeout: int) -> tuple[int, dict[str, Any]]:
    headers = {"Accept": "application/json"}
    if token:
        headers["X-Stock-Ultimus-Read-Token"] = token
    request = urllib.request.Request(url, headers=headers)
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


def compact_health(
    base_url: str,
    unauthorized_status: int,
    authorized_status: int,
    payload: dict[str, Any],
    daily_now_status: int,
    daily_now_payload: dict[str, Any],
) -> dict[str, Any]:
    readiness = payload.get("data_readiness") if isinstance(payload.get("data_readiness"), dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    top = payload.get("top_recommendations")
    if not isinstance(top, list):
        top = payload.get("top_manual_review") if isinstance(payload.get("top_manual_review"), list) else []
    blocked = payload.get("blocked_or_waiting")
    if not isinstance(blocked, list):
        blocked = payload.get("blocked") if isinstance(payload.get("blocked"), list) else []

    checks = {
        "unauthorized_request_rejected": unauthorized_status in {401, 503},
        "authorized_request_ok": authorized_status == 200,
        "has_no_order_guardrail": payload.get("execution_authorized") is False and payload.get("not_order_instruction") is True,
        "has_data_readiness": bool(readiness.get("status")),
        "has_manual_review_bucket": isinstance(top, list),
        "has_blocked_or_waiting_bucket": isinstance(blocked, list),
        "daily_now_ok": (
            daily_now_status == 200
            and daily_now_payload.get("response_mode") == "copy_answer_to_user_exactly"
            and bool(daily_now_payload.get("answer_to_user"))
            and bool(daily_now_payload.get("first_line"))
        ),
        "daily_now_no_order_guardrail": (
            daily_now_payload.get("execution_authorized") is False
            and daily_now_payload.get("not_order_instruction") is True
        ),
        "daily_now_first_line_safe": (
            "no autoriza ordenes" in str(daily_now_payload.get("first_line") or "").lower()
            and "ready_for_decision_review" not in str(daily_now_payload.get("first_line") or "").lower()
        ),
    }
    healthy = all(checks.values())
    return {
        "health_version": "gpt_action_health_v1",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url.rstrip("/"),
        "status": "OK" if healthy else "FAIL",
        "checks": checks,
        "http": {
            "unauthorized_daily_rankings": unauthorized_status,
            "authorized_daily_rankings": authorized_status,
            "authorized_daily_now": daily_now_status,
        },
        "engine": payload.get("engine"),
        "generated_at": payload.get("generated_at"),
        "summary": summary,
        "data_readiness": {
            "status": readiness.get("status"),
            "operational_readiness": readiness.get("operational_readiness"),
            "main_blocker": readiness.get("main_blocker"),
            "option_rows_found": readiness.get("option_rows_found"),
            "technical_count": readiness.get("technical_count"),
            "decision_state_counts": readiness.get("decision_state_counts"),
        },
        "top_manual_review_count": len(top),
        "blocked_or_waiting_count": len(blocked),
        "daily_now": {
            "response_mode": daily_now_payload.get("response_mode"),
            "first_line": daily_now_payload.get("first_line"),
            "answer_length": len(str(daily_now_payload.get("answer_to_user") or "")),
        },
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def main() -> int:
    args = parse_args()
    token = args.token or keychain_password(READ_KEYCHAIN_SERVICE)
    if not token:
        print("Falta READ_ACCESS_TOKEN o token Keychain de lectura.", file=sys.stderr)
        return 2

    base = args.base_url.rstrip("/")
    url = f"{base}/gpt_v31_daily_rankings"
    daily_now_url = f"{base}/gpt_v31_daily_now?limit=5"
    unauthorized_status, _ = request_json(url, None, args.timeout)
    authorized_status, payload = request_json(url, token, args.timeout)
    daily_now_status, daily_now_payload = request_json(daily_now_url, token, args.timeout)
    health = compact_health(base, unauthorized_status, authorized_status, payload, daily_now_status, daily_now_payload)

    if not args.no_write:
        out_path = Path(args.health_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(health, indent=2, sort_keys=True) + "\n")

    print(json.dumps(health, indent=2, sort_keys=True))
    return 0 if health["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
