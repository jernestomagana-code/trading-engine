#!/usr/bin/env python3
"""Check V32 proactive nudge readiness from production.

This helper is the quick "are my push nudges ready?" check for the operator.
It reads the production preflight endpoint, writes a redacted local report, and
prints the next GPT prompt. It never places orders and never prints secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
DEFAULT_BASE_URL = "https://trading-engine-p097.onrender.com"
DEFAULT_OUT = RUNTIME / "v32_nudge_preflight_latest.json"
READ_KEYCHAIN_SERVICE = "stock-ultimus-read-access-token"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check Stock Ultimus V32 nudge readiness.")
    parser.add_argument("--base-url", default=os.getenv("PUBLIC_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--read-timeout", type=int, default=int(os.getenv("STOCK_ULTIMUS_READ_TIMEOUT", "30")))
    parser.add_argument("--retries", type=int, default=int(os.getenv("STOCK_ULTIMUS_NUDGE_PREFLIGHT_RETRIES", "2")))
    parser.add_argument("--json-out", default=os.getenv("STOCK_ULTIMUS_NUDGE_PREFLIGHT_OUT", str(DEFAULT_OUT)))
    parser.add_argument("--no-keychain", action="store_true", help="Use env vars only; do not read macOS Keychain.")
    return parser.parse_args()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def keychain_password(service: str, disabled: bool = False) -> str | None:
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


def read_token(no_keychain: bool) -> str | None:
    for name in ["READ_ACCESS_TOKEN", "STOCK_ULTIMUS_READ_TOKEN", "STOCK_ULTIMUS_READ_ACCESS_TOKEN"]:
        value = os.getenv(name)
        if value:
            return value
    return keychain_password(READ_KEYCHAIN_SERVICE, disabled=no_keychain)


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
    except (TimeoutError, socket.timeout) as exc:
        return 0, {"detail": f"TIMEOUT: {exc}"}
    except urllib.error.URLError as exc:
        return 0, {"detail": str(exc)}


def request_json_with_retries(url: str, token: str | None, timeout: int, retries: int) -> tuple[int, dict[str, Any]]:
    attempts = max(1, retries + 1)
    last_status = 0
    last_payload: dict[str, Any] = {}
    for attempt in range(1, attempts + 1):
        last_status, last_payload = request_json(url, token, timeout)
        if last_status:
            return last_status, last_payload
        if attempt < attempts:
            time.sleep(3)
    return last_status, last_payload


def summarize_preflight(payload: dict[str, Any]) -> dict[str, Any]:
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    slots = checks.get("valid_slots") if isinstance(checks.get("valid_slots"), list) else []
    checklist = payload.get("first_business_day_checklist")
    if not isinstance(checklist, list):
        checklist = []
    return {
        "engine": payload.get("engine"),
        "ready": payload.get("ready") is True,
        "next_market_business_day": payload.get("next_market_business_day"),
        "market_session_state": payload.get("market_session_state"),
        "slots": slots,
        "checklist_count": len(checklist),
        "answer_to_user": payload.get("answer_to_user"),
        "execution_authorized": payload.get("execution_authorized") is True,
        "not_order_instruction": payload.get("not_order_instruction") is True,
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    base_url = args.base_url.rstrip("/")
    token = read_token(args.no_keychain)
    report: dict[str, Any] = {
        "engine": "STOCK_ULTIMUS_V32_NUDGE_PREFLIGHT_CHECK",
        "generated_at": now_iso(),
        "base_url": base_url,
        "checks": {
            "read_token_available": {"ok": bool(token), "source": "env_or_keychain" if token else None},
        },
        "secrets_printed": False,
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
        "gpt_prompt": "haz preflight de nudges y dame checklist del lunes",
    }
    if not token:
        report["status"] = "ACTION_REQUIRED"
        report["ok"] = False
        report["next_required_action"] = "Configurar READ_ACCESS_TOKEN en env o Keychain."
        return report

    status, payload = request_json_with_retries(
        f"{base_url}/v32_operator_nudge_preflight",
        token,
        args.read_timeout,
        args.retries,
    )
    report["checks"]["production_nudge_preflight"] = {"ok": status == 200, "status_code": status}
    if status != 200:
        report["status"] = "ACTION_REQUIRED"
        report["ok"] = False
        report["next_required_action"] = "Revisar deploy/read-auth del endpoint /v32_operator_nudge_preflight."
        report["error"] = payload
        return report

    summary = summarize_preflight(payload)
    report["preflight_summary"] = summary
    report["first_business_day_checklist"] = payload.get("first_business_day_checklist") or []
    report["response_playbook"] = payload.get("response_playbook") or {}
    report["status"] = "READY" if summary["ready"] else "ACTION_REQUIRED"
    report["ok"] = summary["ready"] and summary["not_order_instruction"] and not summary["execution_authorized"]
    report["next_required_action"] = (
        "Actualizar GPT Builder si falta la action, luego pedir el prompt sugerido."
        if report["ok"]
        else "Completar checks de preflight antes del proximo dia habil."
    )
    return report


def print_human(report: dict[str, Any]) -> None:
    print("Stock Ultimus V32 Nudge Preflight")
    print(f"Estado: {report.get('status')} | ok={report.get('ok')}")
    print(f"Siguiente accion: {report.get('next_required_action')}")
    checks = report.get("checks") or {}
    for name in ["read_token_available", "production_nudge_preflight"]:
        check = checks.get(name) or {}
        marker = "OK" if check.get("ok") else "FAIL"
        print(f"- {name}: {marker}")
    summary = report.get("preflight_summary") or {}
    if summary:
        print(f"- next_market_business_day={summary.get('next_market_business_day')}")
        print(f"- market_session_state={summary.get('market_session_state')}")
        print(f"- slots={', '.join(summary.get('slots') or [])}")
        print(f"- checklist_items={summary.get('checklist_count')}")
    print(f"Prompt GPT sugerido: {report.get('gpt_prompt')}")
    print("Guardrail: Decision support solamente; execution_authorized=false; not_order_instruction=true.")


def main() -> int:
    args = parse_args()
    report = build_report(args)
    out_path = Path(args.json_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print_human(report)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
